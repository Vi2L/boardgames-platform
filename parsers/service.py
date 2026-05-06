from __future__ import annotations

import asyncio
import logging

from .base import StoreParser
from .db import PriceDatabase
from .models import SearchResult

logger = logging.getLogger(__name__)


class PriceService:
    """Оркестратор: TTL-кеш per-store + параллельный запуск парсеров.

    Логика search():
      1. Читаем кеш из БД — берём результаты только по свежим магазинам.
      2. Определяем «протухшие» магазины (нет свежих данных по запросу).
      3. Если все свежие → возвращаем source="cache", сеть не трогаем.
      4. Параллельно (asyncio.gather) парсим протухшие магазины.
      5. Сохраняем новые наблюдения в БД.
      6. Graceful degradation:
           - были ошибки, но хоть что-то сохранили → source="network"
           - все упали, кеш есть                  → source="partial-cache"
           - все упали, кеша нет                  → RuntimeError
    """

    def __init__(
        self,
        db: PriceDatabase,
        parsers: list[StoreParser],
        cache_ttl_hours: float = 4.0,
    ) -> None:
        self._db = db
        # словарь slug → parser для быстрого доступа
        self._parsers: dict[str, StoreParser] = {p.store.slug: p for p in parsers}
        self._ttl = cache_ttl_hours

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

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
            return SearchResult(products=cached[:limit], source="cache")

        # 3. Параллельно парсим устаревшие магазины
        errors: dict[str, str] = {}
        saved_count = 0

        tasks = {slug: self._parsers[slug].search(query, limit) for slug in stale_slugs if slug in self._parsers}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for slug, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning("Парсер %s упал: %s", slug, result)
                errors[slug] = str(result)
                continue
            for product in result:
                try:
                    await self._db.upsert_product(product)
                    saved_count += 1
                except Exception as e:
                    logger.error("Ошибка сохранения товара из %s: %s", slug, e)

        # 4. Читаем итоговый результат из БД (свежие + только что обновлённые)
        products = await self._db.search_cached(query, target_slugs, self._ttl)

        # 5. Graceful degradation
        if errors and saved_count == 0:
            # Все новые запросы упали — ищем любые данные в БД без TTL-ограничения
            products = await self._db.search_cached(query, target_slugs, max_age_hours=float("inf"))
            if not products:
                raise RuntimeError(
                    f"Все магазины вернули ошибку и кеша нет. Ошибки: {errors}"
                )
            source = "partial-cache"
        elif not products:
            raise RuntimeError(
                f"Все магазины вернули ошибку и кеша нет. Ошибки: {errors}"
            )
        else:
            source = "network"

        return SearchResult(products=products[:limit], source=source, errors=errors)

    async def get_stores(self):
        return await self._db.list_stores()

    async def get_history(self, product_id: int):
        return await self._db.get_history(product_id)
