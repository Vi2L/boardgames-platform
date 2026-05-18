"""Per-store Circuit Breaker для парсеров (PRS-7).

WB / Ozon / Avito периодически отдают 429/403 пачкой — Angie дросселирует,
Qrator поднимает challenge. Без breaker'а парсер каждый запрос тыкает в
забор, шумит в логах и UI. Идея breaker'а: после N подряд провалов
открыть цепь на ~5 минут — `search()` сразу падает с понятной ошибкой,
вместо того чтобы делать новые HTTP. Через open_for секунд — half-open
проба: один запрос идёт реально, успех закрывает цепь, провал снова
открывает.

Per-process state, без БД. Достаточно для одного uvicorn-worker'а; в
multi-worker деплое каждый держит свой breaker — это OK, потому что
цель — погасить шум на ближайшие минуты, не координировать инстансы.

Использование (см. wildberries.py / ozon.py / avito.py):

    breaker = get_breaker("wildberries")
    if not breaker.is_available():
        raise RuntimeError(f"WB circuit open until {breaker.opens_until_iso}")
    try:
        result = await self._fetch_json(...)
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        raise

Паттерн взят из ``catalog.matching.v2.health.OllamaHealth`` — там
breaker для Ollama моделей. Здесь — упрощённая sliding-window версия
без отдельного scheduler-job'а для probe (lazy probe «по запросу»).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

State = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Sliding-window breaker per store.

    Параметры:
      store: slug магазина (для логов и identity).
      failure_threshold: 0..1, доля failures в окне для перехода в open.
      window_sec: размер скользящего окна для подсчёта failure rate.
      open_for_sec: сколько секунд держим цепь открытой до half-open пробы.
      min_samples: минимум событий в окне, чтобы failure_rate имел смысл.
        Защита от одного-двух провалов сразу после старта.
    """

    def __init__(
        self,
        store: str,
        *,
        failure_threshold: float = 0.5,
        window_sec: int = 60,
        open_for_sec: int = 300,
        min_samples: int = 5,
    ) -> None:
        self.store = store
        self.failure_threshold = failure_threshold
        self.window_sec = window_sec
        self.open_for_sec = open_for_sec
        self.min_samples = min_samples
        # `deque[(monotonic_ts, is_success)]`. Длину не ограничиваем — обрезаем
        # старые события при каждом доступе (см. `_prune_old`).
        self._events: deque[tuple[float, bool]] = deque()
        self._opened_at: float | None = None  # set при переходе closed→open
        self._last_failure_reason: str | None = None

    # ── State helpers ────────────────────────────────────────────────────

    def _prune_old(self, now: float) -> None:
        """Снимает события старше window_sec — sliding-window."""
        cutoff = now - self.window_sec
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    @property
    def state(self) -> State:
        """Текущее состояние без побочных эффектов (не двигает open→half_open)."""
        if self._opened_at is None:
            return "closed"
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self.open_for_sec:
            return "half_open"
        return "open"

    def is_available(self) -> bool:
        """True если можно делать запрос. В half_open — один probe в TR.

        Lazy probe: при первом вызове в half_open возвращаем True, но
        состояние внутренне остаётся «ожидаем результат пробы». Следующий
        вызов до получения record_* ещё попадёт в half_open (это OK для
        sync-флоу одного парсера, который делает запрос и сразу записывает
        результат).
        """
        return self.state != "open"

    @property
    def opens_until_iso(self) -> str | None:
        """ISO-строка момента, до которого цепь закрыта. None если closed."""
        if self._opened_at is None:
            return None
        unix = time.time() + (self.open_for_sec - (time.monotonic() - self._opened_at))
        return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat()

    # ── Recording ────────────────────────────────────────────────────────

    def record_success(self) -> None:
        """Успешный запрос. Если были в half_open — закрываем цепь."""
        now = time.monotonic()
        self._prune_old(now)
        self._events.append((now, True))
        if self._opened_at is not None:
            # Половина secent был half_open, успех закрывает.
            elapsed = now - self._opened_at
            if elapsed >= self.open_for_sec:
                logger.info(
                    "[breaker:%s] half_open probe success → closed (was open %.1fs)",
                    self.store, elapsed,
                )
                self._opened_at = None
                self._last_failure_reason = None
                self._events.clear()  # reset window после восстановления

    def record_failure(self, reason: str | None = None) -> None:
        """Неуспех. Если failure rate в окне > threshold — открываем цепь."""
        now = time.monotonic()
        self._prune_old(now)
        self._events.append((now, False))
        if reason is not None:
            self._last_failure_reason = reason[:200]

        # Half-open probe failed → снова open.
        if self._opened_at is not None and (now - self._opened_at) >= self.open_for_sec:
            logger.warning(
                "[breaker:%s] half_open probe failed → open again (reason=%s)",
                self.store, reason,
            )
            self._opened_at = now
            return

        # Closed → open transition.
        if self._opened_at is None:
            total = len(self._events)
            if total < self.min_samples:
                return
            failures = sum(1 for _, ok in self._events if not ok)
            rate = failures / total
            if rate >= self.failure_threshold:
                self._opened_at = now
                logger.warning(
                    "[breaker:%s] OPEN (failure_rate=%.2f over %d events, "
                    "fail-fast until +%ds, last_reason=%s)",
                    self.store, rate, total, self.open_for_sec, reason,
                )

    # ── Diagnostics ──────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Состояние для аналитики/UI (dashboard breakers)."""
        now = time.monotonic()
        self._prune_old(now)
        total = len(self._events)
        failures = sum(1 for _, ok in self._events if not ok)
        return {
            "store": self.store,
            "state": self.state,
            "failure_rate": (failures / total) if total else 0.0,
            "events_in_window": total,
            "failure_threshold": self.failure_threshold,
            "window_sec": self.window_sec,
            "open_for_sec": self.open_for_sec,
            "opens_until": self.opens_until_iso,
            "last_failure_reason": self._last_failure_reason,
        }


# ── Per-process registry ─────────────────────────────────────────────────

_BREAKERS: dict[str, CircuitBreaker] = {}


def get_breaker(store: str, **kwargs) -> CircuitBreaker:
    """Возвращает shared CircuitBreaker для store. Создаёт если нет.

    `kwargs` действуют только при первом вызове — повторные вызовы для
    того же store возвращают существующий инстанс. Если нужны разные
    параметры — это запах смешения ответственности; лучше использовать
    разные store-slug'и.
    """
    if store not in _BREAKERS:
        _BREAKERS[store] = CircuitBreaker(store, **kwargs)
    return _BREAKERS[store]


def all_breakers() -> list[CircuitBreaker]:
    """Список всех зарегистрированных breaker'ов — для diagnostics-endpoint."""
    return list(_BREAKERS.values())


def reset_for_tests() -> None:
    """Снимок registry для тестов с независимым state."""
    _BREAKERS.clear()
