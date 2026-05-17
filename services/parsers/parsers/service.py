from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from .base import StoreParser
from .catalog_publisher import CatalogPublisher
from .db import PriceDatabase
from .models import SearchResult

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _per_parser_timeout_seconds() -> float:
    """Таймаут на одного парсера в /search (default 25 сек).

    Зачем это: `asyncio.gather` ждёт всех парсеров, поэтому самый медленный
    диктует latency. Когда browser-зависимый парсер (Ozon/OnlineTrade)
    залипает на browser-service'е (Camoufox challenge), он может
    блокировать gather на десятки секунд. Это приводит к тому, что
    upstream-клиент (web-test parsers_client, timeout 30 сек) рвёт
    соединение раньше, чем parsers успевают ответить — и пользователь
    видит «parsers API недоступен» с пустым detail, хотя 5 из 7 парсеров
    отдают данные за секунды.

    25 сек = 30 сек (web-test timeout) − 5 сек запас на сериализацию и
    транзит. Зависший парсер получает `asyncio.TimeoutError`, фолбэкает
    в `errors[slug]`, остальные продолжают работать как обычно.
    """
    raw = os.getenv("PARSERS_PER_PARSER_TIMEOUT_SECONDS", "25").strip()
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "PARSERS_PER_PARSER_TIMEOUT_SECONDS=%r не float, использую 25", raw
        )
        value = 25.0
    return max(5.0, value)  # минимум 5с — защита от опечатки в env


_PER_PARSER_TIMEOUT = _per_parser_timeout_seconds()


class PriceService:
    """Оркестратор: TTL-кеш per-store + параллельный запуск парсеров."""

    def __init__(
        self,
        db: PriceDatabase,
        parsers: list[StoreParser],
        cache_ttl_hours: float = 4.0,
        catalog_publisher: CatalogPublisher | None = None,
    ) -> None:
        self._db = db
        self._parsers: dict[str, StoreParser] = {p.store.slug: p for p in parsers}
        self._ttl = cache_ttl_hours
        # Опциональный канал отправки оффер'ов в boardgames-catalog. None или
        # disabled — search работает без изменений.
        self._catalog_publisher = catalog_publisher

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

        # Каждый парсер замеряем индивидуально через wrapper. Раньше использовался
        # общий per_parser_elapsed, в результате в parser_log писалось одинаковое
        # время для всех — это давало некорректную аналитику.
        async def _run_one(slug: str):
            t = time.monotonic()
            try:
                # asyncio.wait_for отменит coro по таймауту и поднимет
                # TimeoutError — попадает в общий except ниже как обычная
                # ошибка парсера, без особой обработки. Зависший Ozon
                # перестаёт блокировать остальных.
                products = await asyncio.wait_for(
                    self._parsers[slug].search(query, limit),
                    timeout=_PER_PARSER_TIMEOUT,
                )
                elapsed = int((time.monotonic() - t) * 1000)
                return slug, products, elapsed, None
            except asyncio.TimeoutError:
                elapsed = int((time.monotonic() - t) * 1000)
                # Явный message — пустой str() у TimeoutError даёт «»
                # в UI, что выглядит как «непонятная ошибка».
                msg = f"per-parser timeout {_PER_PARSER_TIMEOUT:.0f}s"
                return slug, None, elapsed, RuntimeError(msg)
            except Exception as e:
                elapsed = int((time.monotonic() - t) * 1000)
                return slug, None, elapsed, e

        runs = [_run_one(s) for s in stale_slugs if s in self._parsers]
        finished = await asyncio.gather(*runs)

        for slug, products, elapsed_ms, exc in finished:
            metrics = getattr(self._parsers[slug], "last_metrics", None)
            metric_kwargs: dict = {}
            if metrics is not None:
                metric_kwargs = {
                    "search_ms": metrics.search_ms,
                    "enrich_ms": metrics.enrich_ms,
                    "http_requests": metrics.http_requests,
                    "result_after_enrich": metrics.result_after_enrich,
                }

            if exc is not None:
                logger.warning("Парсер %s упал: %s", slug, exc)
                errors[slug] = str(exc)
                asyncio.create_task(self._db.log_parser(
                    store_slug=slug, success=False, result_count=0,
                    duration_ms=elapsed_ms, error_msg=str(exc),
                    ts=_utcnow_iso(), **metric_kwargs,
                ))
                continue

            asyncio.create_task(self._db.log_parser(
                store_slug=slug, success=True, result_count=len(products),
                duration_ms=elapsed_ms, error_msg=None,
                ts=_utcnow_iso(), **metric_kwargs,
            ))
            for product in products:
                try:
                    await self._db.upsert_product(product)
                    saved_count += 1
                except Exception as e:
                    logger.error("Ошибка сохранения товара из %s: %s", slug, e)

            # Side-channel: пушим батч в boardgames-catalog. Fire-and-forget,
            # ошибки не влияют на ответ /search (см. CatalogPublisher.publish).
            if self._catalog_publisher is not None and self._catalog_publisher.enabled:
                asyncio.create_task(
                    self._catalog_publisher.publish(slug, list(products))
                )

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
