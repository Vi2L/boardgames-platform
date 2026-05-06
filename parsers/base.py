from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .models import ParsedProduct, StoreInfo

if TYPE_CHECKING:
    from .db import PriceDatabase
    import httpx


@dataclass
class ParserMetrics:
    """Метрики последнего вызова parser.search() — заполняются самим парсером.

    Сервис читает их через `parser.last_metrics` и передаёт в `db.log_parser()`.
    Все поля Optional, чтобы парсер мог отрапортовать только то, что измеряет
    (например, у CrowdGames нет enrich-этапа — `enrich_ms` будет None).
    """
    search_ms: int | None = None
    enrich_ms: int | None = None
    http_requests: int = 0
    result_after_enrich: int = 0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SnapshotRecorder:
    """Записывает raw HTTP-ответы парсера в parser_snapshot — только при ENABLE_RAW_SNAPSHOTS=1.

    Используется как event hook httpx:
        recorder = SnapshotRecorder(self.store.slug, query, self._db)
        async with httpx.AsyncClient(event_hooks=recorder.merged_hooks(other_hooks)) as client:
            ...

    При выключенном флаге `merged_hooks` возвращает только `other_hooks` без дополнений —
    то есть оверхед нулевой.
    """

    def __init__(self, store_slug: str, query: str | None, db: "PriceDatabase | None") -> None:
        self._store_slug = store_slug
        self._query = query
        self._db = db
        self._enabled = (
            db is not None
            and os.getenv("ENABLE_RAW_SNAPSHOTS") == "1"
        )
        self._search_url_seen = False  # первый запрос считаем search, остальные enrich

    @property
    def enabled(self) -> bool:
        return self._enabled

    def merged_hooks(self, other: dict | None = None) -> dict:
        """Объединить расходящиеся event_hooks в один dict для httpx.AsyncClient."""
        hooks: dict[str, list] = {"request": [], "response": []}
        if other:
            for key, fns in other.items():
                hooks.setdefault(key, []).extend(fns)
        if self._enabled:
            hooks["response"].append(self._on_response)
        # Убираем пустые ключи — httpx требует не пустые списки
        return {k: v for k, v in hooks.items() if v}

    async def _on_response(self, response: "httpx.Response") -> None:
        if not self._enabled or self._db is None:
            return

        # На первый запрос помечаем kind='search', далее 'enrich'.
        # CrowdGames делает несколько search-запросов (страницы каталога), но в нашей
        # модели всё это всё ещё поиск — пометим первую как 'search', далее 'enrich'.
        kind = "search" if not self._search_url_seen else "enrich"
        self._search_url_seen = True

        try:
            await response.aread()  # обязательно: иначе stream может быть пустым
            body = response.content
        except Exception:
            body = b""

        elapsed_ms = None
        try:
            elapsed_ms = int(response.elapsed.total_seconds() * 1000)
        except Exception:
            pass

        try:
            await self._db.save_snapshot(
                store_slug=self._store_slug,
                query=self._query,
                url=str(response.request.url),
                method=response.request.method,
                status_code=response.status_code,
                encoding=response.encoding,
                content_type=response.headers.get("content-type"),
                body=body,
                duration_ms=elapsed_ms,
                ts=_utcnow_iso(),
                kind=kind,
            )
        except Exception:
            # Snapshot — диагностический инструмент, не должен ломать парсер
            pass


class StoreParser(ABC):
    """Базовый класс для всех парсеров магазинов.

    Чтобы добавить новый магазин:
    1. Создать модуль в parsers/stores/<slug>.py
    2. Унаследоваться от StoreParser
    3. Задать атрибут store: StoreInfo
    4. Реализовать метод search() — возвращает list[ParsedProduct]
       и устанавливает self.last_metrics для аналитики dashboard'а
    5. Зарегистрировать экземпляр в parsers/api.py:lifespan()

    Контракт метрик (опционально, но желательно):
    - В начале search() сбросить self._http_counter = 0 и self.last_metrics = None
    - Передать `event_hooks={"request": [self._count_request]}` в httpx.AsyncClient
      (метод _count_request есть в этом классе)
    - Замерить `time.monotonic()` вокруг search-запроса → search_ms
    - Замерить вокруг asyncio.gather(*enrich) → enrich_ms (если enrich есть)
    - В конце установить self.last_metrics = ParserMetrics(...)
    """

    store: StoreInfo

    def __init__(self) -> None:
        self.last_metrics: ParserMetrics | None = None
        self._http_counter: int = 0
        # Инжектируется в lifespan() приложения после создания парсера; используется
        # SnapshotRecorder'ом для записи raw HTTP-ответов
        self._db: "PriceDatabase | None" = None

    async def _count_request(self, request) -> None:
        """httpx event hook для подсчёта HTTP-вызовов внутри search()."""
        self._http_counter += 1

    def _make_recorder(self, query: str | None) -> SnapshotRecorder:
        """Создать SnapshotRecorder для текущего вызова search()."""
        return SnapshotRecorder(self.store.slug, query, self._db)

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        """Найти товары по запросу.

        Должен вернуть пустой список при отсутствии результатов.
        При сетевой или парсинговой ошибке — поднять исключение
        (PriceService поймает его и запишет в SearchResult.errors).
        """
        ...
