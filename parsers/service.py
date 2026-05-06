from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from .base import StoreParser
from .db import PriceDatabase
from .models import SearchResult

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PriceService:
    """Оркестратор: TTL-кеш per-store + параллельный запуск парсеров."""

    def __init__(
        self,
        db: PriceDatabase,
        parsers: list[StoreParser],
        cache_ttl_hours: float = 4.0,
    ) -> None:
        self._db = db
        self._parsers: dict[str, StoreParser] = {p.store.slug: p for p in parsers}
        self._ttl = cache_ttl_hours

    async def search(
        self,
        query: str,
        limit: int = 10,
        force_refresh: bool = False,
        store_slugs: list[str] | None = None,
    ) -> SearchResult:
        target_slugs = store_slugs or list(self._parsers)

        # 1. Определяем какие магазины уже свежие
        if force_refresh:
            stale_slugs = target_slugs
        else:
            fresh = await self._db.get_fresh_store_slugs(query, target_slugs, self._ttl)
            stale_slugs = [s for s in target_slugs if s not in fresh]

        # 2. Ранний выход: все данные свежие
        if not stale_slugs:
            cached = await self._db.search_cached(query, target_slugs, self._ttl)
            # Логируем cache-hit
            asyncio.create_task(self._db.log_request(
                query=query, source="cache",
                result_count=len(cached), error_count=0,
                duration_ms=0, errors={}, ts=_utcnow_iso(),
            ))
            return SearchResult(products=cached[:limit], source="cache")

        # 3. Параллельно парсим устаревшие магазины с замером времени
        errors: dict[str, str] = {}
        saved_count = 0
        t0 = time.monotonic()

        tasks = {
            slug: self._parsers[slug].search(query, limit)
            for slug in stale_slugs if slug in self._parsers
        }
        # Замеряем время каждого парсера отдельно
        per_parser_t0 = time.monotonic()
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        per_parser_elapsed = int((time.monotonic() - per_parser_t0) * 1000)

        for slug, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning("Парсер %s упал: %s", slug, result)
                errors[slug] = str(result)
                asyncio.create_task(self._db.log_parser(
                    store_slug=slug, success=False, result_count=0,
                    duration_ms=per_parser_elapsed, error_msg=str(result),
                    ts=_utcnow_iso(),
                ))
                continue

            asyncio.create_task(self._db.log_parser(
                store_slug=slug, success=True, result_count=len(result),
                duration_ms=per_parser_elapsed, error_msg=None,
                ts=_utcnow_iso(),
            ))
            for product in result:
                try:
                    await self._db.upsert_product(product)
                    saved_count += 1
                except Exception as e:
                    logger.error("Ошибка сохранения товара из %s: %s", slug, e)

        # 4. Читаем итоговый результат из БД
        products = await self._db.search_cached(query, target_slugs, self._ttl)
        total_ms = int((time.monotonic() - t0) * 1000)

        # 5. Graceful degradation
        if errors and saved_count == 0:
            products = await self._db.search_cached(query, target_slugs, max_age_hours=float("inf"))
            if not products:
                asyncio.create_task(self._db.log_request(
                    query=query, source="partial-cache",
                    result_count=0, error_count=len(errors),
                    duration_ms=total_ms, errors=errors, ts=_utcnow_iso(),
                ))
                raise RuntimeError(
                    f"Все магазины вернули ошибку и кеша нет. Ошибки: {errors}"
                )
            source = "partial-cache"
        elif not products:
            asyncio.create_task(self._db.log_request(
                query=query, source="partial-cache",
                result_count=0, error_count=len(errors),
                duration_ms=total_ms, errors=errors, ts=_utcnow_iso(),
            ))
            raise RuntimeError(
                f"Все магазины вернули ошибку и кеша нет. Ошибки: {errors}"
            )
        else:
            source = "network"

        asyncio.create_task(self._db.log_request(
            query=query, source=source,
            result_count=len(products), error_count=len(errors),
            duration_ms=total_ms, errors=errors, ts=_utcnow_iso(),
        ))
        return SearchResult(products=products[:limit], source=source, errors=errors)

    async def get_stores(self):
        return await self._db.list_stores()

    async def get_history(self, product_id: int):
        return await self._db.get_history(product_id)
