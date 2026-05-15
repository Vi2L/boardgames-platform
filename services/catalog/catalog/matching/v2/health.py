"""OllamaHealth + Circuit Breaker — мониторинг доступности Ollama.

Singleton-класс, читает /api/tags Ollama раз в N секунд (через APScheduler-job)
и кэширует статус каждой нужной модели в памяти. Tier'ы T2/T3 проверяют
`is_available_for(model)` синхронно — кэшированное значение, без HTTP.

Circuit Breaker логика:
  - closed: всё ок, запросы идут.
  - open: после consecutive_failures Ollama-вызов отказался — отдаём False
    немедленно. Через recovery_timeout проба (half-open).
  - half-open: даём один шанс. Успех → closed; провал → open.

Этот класс держит состояние per-model: bge-m3 и qwen2.5 могут быть в разных
состояниях (Ollama может разгрузить одну, оставив другую).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from catalog.config import get_settings

logger = logging.getLogger(__name__)


class OllamaHealth:
    """Singleton, инициализируется в lifespan, опрашивается scheduler-job'ом.

    `is_available_for(model)` — sync-метод, безопасен для частых вызовов
    (никаких HTTP). `check()` — async, делает HTTP к Ollama.
    """

    _instance: "OllamaHealth | None" = None

    def __init__(self) -> None:
        self._status: dict[str, bool] = {}  # model_name → available
        self._failures: dict[str, int] = {}  # consecutive failures per model
        self._last_failure_at: dict[str, float] = {}  # timestamp перехода в open
        self._last_check_at: float = 0.0
        self._last_success_at: float = 0.0
        self._lock = asyncio.Lock()

        # Circuit breaker thresholds.
        # closed → open: после N consecutive failures.
        # open → half-open: автоматически по таймеру; пробная попытка
        # происходит при следующем `is_available_for(model)` (но не через
        # отдельный таймер — мы lazy probe'имся «по запросу», иначе пришлось бы
        # держать второй background-job).
        self._failure_threshold = 3
        self._recovery_timeout = 60.0  # сек до half-open пробы

    @classmethod
    def get_instance(cls) -> "OllamaHealth":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """Снимок singleton'а — для тестов с независимым состоянием."""
        cls._instance = None

    def is_available_for(self, model: str) -> bool:
        """True если модель готова. Sync, читает кэшированный статус.

        Half-open semantics: если модель в `open` и с момента последнего
        провала прошло `_recovery_timeout` секунд — возвращаем True (probe).
        Worker сделает попытку реального вызова Ollama; при успехе следующий
        `check()` или сам успешный embed/llm-call вернёт нас в closed; при
        провале `_record_failure` сбросит timestamp и снова уйдём в open.

        Lazy probe — без отдельного background-таймера. Альтернатива (active
        probe раз в N сек) была бы дорогой: HTTP-запрос к Ollama в холостую,
        даже если никто не обрабатывает очередь.
        """
        status = self._status.get(model)
        if status is None:
            # Никогда не проверяли — пусть scheduler-job `ml_health_check` сходит
            # первым. Без active check возвращаем False (консервативно).
            return False
        if status is True:
            return True
        # status is False → open. Проверяем не пора ли в half-open.
        last_fail = self._last_failure_at.get(model)
        if last_fail is None:
            return False
        if (time.time() - last_fail) >= self._recovery_timeout:
            logger.info(
                "OllamaHealth: %s — half-open probe (open for %.0fs)",
                model, time.time() - last_fail,
            )
            return True
        return False

    @property
    def status_summary(self) -> dict:
        """Для GET /matching/ml-status и UI badge.

        `circuit_state` per-model: 'closed' (всё ок), 'open' (отказ N подряд),
        'half_open' (open + прошёл recovery_timeout, следующий запрос — probe).
        """
        now = time.time()
        circuit_state: dict[str, str] = {}
        for model, status in self._status.items():
            if status is True:
                circuit_state[model] = "closed"
            else:
                last_fail = self._last_failure_at.get(model)
                if last_fail is not None and (now - last_fail) >= self._recovery_timeout:
                    circuit_state[model] = "half_open"
                else:
                    circuit_state[model] = "open"
        return {
            "models": dict(self._status),
            "circuit_state": circuit_state,
            "last_check_at": (
                datetime.fromtimestamp(self._last_check_at, tz=timezone.utc).isoformat()
                if self._last_check_at else None
            ),
            "last_success_at": (
                datetime.fromtimestamp(self._last_success_at, tz=timezone.utc).isoformat()
                if self._last_success_at else None
            ),
            "failures": dict(self._failures),
        }

    async def check(self) -> None:
        """HTTP-poll: GET /api/tags. Обновляет статус моделей.

        Безопасен к ошибкам (catch all) — никогда не пробрасывает наружу.
        Запускается scheduler-job'ом раз в N секунд.
        """
        settings = get_settings()
        async with self._lock:
            self._last_check_at = time.time()

            try:
                async with httpx.AsyncClient(
                    base_url=settings.ollama_base_url, timeout=5.0,
                ) as client:
                    resp = await client.get("/api/tags")
                    if resp.status_code != 200:
                        self._mark_all_failed(f"http_{resp.status_code}")
                        return
                    data = resp.json()
                    # Ollama имена моделей могут быть как "bge-m3" или "bge-m3:latest".
                    # Считаем модель доступной, если её префикс есть в списке.
                    available_names = {m.get("name", "") for m in data.get("models", [])}
                    for model in (settings.ml_embed_model, settings.ml_llm_model):
                        ok = any(
                            name == model or name.startswith(model + ":")
                            for name in available_names
                        )
                        if ok:
                            self._status[model] = True
                            self._failures[model] = 0
                            self._last_success_at = time.time()
                        else:
                            self._record_failure(model, "model_not_loaded")
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                self._mark_all_failed(f"connect_error: {type(e).__name__}")
            except Exception as e:  # noqa: BLE001
                logger.exception("OllamaHealth.check failed")
                self._mark_all_failed(f"unexpected: {type(e).__name__}")

    def _mark_all_failed(self, reason: str) -> None:
        """Все модели — недоступны (Ollama unreachable)."""
        settings = get_settings()
        for model in (settings.ml_embed_model, settings.ml_llm_model):
            self._record_failure(model, reason)

    def record_success(self, model: str) -> None:
        """Closed-семантика: успешный реальный вызов модели (embed/llm) сбрасывает
        счётчик провалов и закрывает цепь.

        Вызывается из `embedder.embed_one` и `llm_arbiter.tier_3_llm` после
        успешного HTTP-ответа. Без этого: после half-open probe цепь оставалась
        бы в open до следующего фонового `check()` (до 30 сек), и воркер каждые
        10 сек делал бы новый probe на одну и ту же модель — лишний overhead.
        """
        if not self._status.get(model):
            logger.info("OllamaHealth: model %s → closed (probe success)", model)
        self._status[model] = True
        self._failures[model] = 0
        self._last_failure_at.pop(model, None)
        self._last_success_at = time.time()

    def _record_failure(self, model: str, reason: str) -> None:
        self._failures[model] = self._failures.get(model, 0) + 1
        if self._failures[model] >= self._failure_threshold:
            was_open = self._status.get(model) is False
            self._status[model] = False
            # Каждый провал двигает таймер recovery — half-open probe
            # отсчитывается от ПОСЛЕДНЕГО провала, не от момента первого
            # перехода в open. Это правильно: если Ollama флапает, мы не
            # хотим пускать probe сразу после каждого провального ответа.
            self._last_failure_at[model] = time.time()
            if not was_open:
                logger.warning(
                    "OllamaHealth: model %s → open (failures=%d, reason=%s)",
                    model, self._failures[model], reason,
                )
            else:
                logger.debug(
                    "OllamaHealth: model %s still open (failures=%d, reason=%s)",
                    model, self._failures[model], reason,
                )
