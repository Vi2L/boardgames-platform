"""SSE-эндпоинт поиска через parsers REST API.

Архитектура:
- Один HTTP-запрос к parsers /search (не per-parser)
- SSE-события: store-start → api-request → api-response → store-done × N → results
- store-start/store-done сохраняются для UI-совместимости (badges)
- После завершения результаты пишутся в локальную PortalDB
  (для DatabasePage и ProductPage с deep-link)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.db_local import get_portal_db
from app.deps import get_parsers_client
from app.parsers_client import ParsersServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


async def _log_to_portal_db(
    *, query: str, stores: list[str] | None, source: str | None,
    total_ms: int | None, products: list, error_count: int,
    errors: dict[str, str] | None = None,
) -> None:
    """Сохраняет результат search в локальной БД портала.

    Любая ошибка (БД не инициализирована, диск переполнен, миграция
    застряла) — не должна валить SSE. Только пишем в лог и идём дальше.
    """
    try:
        db = get_portal_db()
        if products:
            await db.upsert_products(products)
        await db.log_search(
            query=query, stores=stores, source=source, total_ms=total_ms,
            products_count=len(products), error_count=error_count,
            errors=errors,
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to log search to portal db")


async def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_search(
    queue: asyncio.Queue,
    q: str,
    store_slugs: list[str] | None,
    limit: int,
    refresh: bool,
) -> None:
    """Выполняет поиск через parsers API, кладёт SSE-события в queue."""
    client = get_parsers_client()
    t0 = time.monotonic()

    # Получаем список магазинов для UI-badges
    active_stores: list = []
    try:
        all_stores = await client.get_stores()
        active_stores = [
            s for s in all_stores
            if not store_slugs or s.slug in store_slugs
        ]
    except Exception:
        # Если stores недоступны — продолжаем, ошибка будет в api-error
        pass

    # store-start для всех выбранных магазинов
    for store in active_stores:
        await queue.put(("store-start", {"slug": store.slug, "name": store.name}))

    # Логируем исходящий запрос к parsers
    await queue.put(("api-request", {
        "url": f"{client.base_url}/search",
        "q": q,
        "stores": store_slugs,
        "limit": limit,
        "refresh": refresh,
    }))

    try:
        result = await client.search(q, store_slugs, limit, refresh)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        await queue.put(("api-response", {
            "status": 200,
            "elapsed_ms": elapsed_ms,
            "source": result.source,
            "products_count": len(result.products),
            "error_count": len(result.errors),
        }))

        # store-done: разбиваем результаты по магазинам
        products_by_store: dict[str, list] = {}
        for p in result.products:
            products_by_store.setdefault(p.store_slug, []).append(p)

        for store in active_stores:
            store_products = products_by_store.get(store.slug, [])
            store_error = result.errors.get(store.slug)
            await queue.put(("store-done", {
                "slug": store.slug,
                "name": store.name,
                "count": len(store_products),
                "elapsed_ms": elapsed_ms,
                "error": store_error,
            }))

        # Финальный результат
        products_data = [p.model_dump() for p in result.products]
        await queue.put(("results", {
            "query": q,
            "products": products_data,
            "source": result.source,
            "errors": result.errors,
            "total_ms": elapsed_ms,
        }))

        # Сохраняем в локальную БД портала (для DatabasePage и ProductPage)
        await _log_to_portal_db(
            query=q, stores=store_slugs, source=result.source,
            total_ms=elapsed_ms, products=result.products,
            error_count=len(result.errors), errors=result.errors,
        )

    except ParsersServiceError as exc:
        # Структурированный 5xx/4xx от parsers — у нас уже есть человекочитаемое
        # detail. Магазины тут не «упали» — это решение parsers «нет данных по
        # этому запросу», поэтому в store-done error не пишем (бейджи не
        # окрасятся в красный, что точнее отражает причину).
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        message = exc.detail or f"parsers HTTP {exc.status_code}"

        for store in active_stores:
            await queue.put(("store-done", {
                "slug": store.slug, "name": store.name,
                "count": 0, "elapsed_ms": elapsed_ms, "error": None,
            }))

        await queue.put(("api-error", {
            "error": message,
            "status_code": exc.status_code,
            "elapsed_ms": elapsed_ms,
        }))

        await _log_to_portal_db(
            query=q, stores=store_slugs, source=None,
            total_ms=elapsed_ms, products=[],
            error_count=0,
            errors={"_parsers_status": f"{exc.status_code}: {message}"},
        )

    except Exception as exc:
        # Сетевые/неожиданные ошибки (httpx.ConnectError, TimeoutException,
        # KeyError при битом JSON и т. п.) — действительно «сломались
        # магазины», красим бейджи в красный.
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        for store in active_stores:
            await queue.put(("store-done", {
                "slug": store.slug, "name": store.name,
                "count": 0, "elapsed_ms": elapsed_ms, "error": str(exc),
            }))

        await queue.put(("api-error", {
            "error": str(exc),
            "elapsed_ms": elapsed_ms,
        }))

        # Логируем неудачную попытку отдельно
        await _log_to_portal_db(
            query=q, stores=store_slugs, source=None,
            total_ms=elapsed_ms, products=[],
            error_count=len(active_stores) or 1,
            errors={"_": str(exc)},
        )

    await queue.put(None)


async def _stream(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    """Читает события из queue и отдаёт как SSE.

    Heartbeat каждые 30 секунд — keepalive для прокси и браузеров.
    """
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            yield ": heartbeat\n\n"
            continue

        if item is None:
            break

        event_name, data = item
        yield await _sse(event_name, data)


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Поисковый запрос"),
    stores: str | None = Query(None, description="Slug магазинов через запятую"),
    limit: int = Query(100, ge=1, le=500, description="Лимит результатов на магазин"),
    refresh: bool = Query(False, description="Игнорировать кеш и обновить"),
) -> StreamingResponse:
    """Запускает поиск через parsers API, стримит SSE-события.

    События:
    - store-start:   магазин начинает запрос (UI badge → running)
    - api-request:   детали HTTP-запроса к parsers /search
    - api-response:  ответ parsers (статус, время, source, кол-во)
    - store-done:    результат по конкретному магазину (count, error)
    - results:       финальный список всех продуктов
    - api-error:     ошибка если parsers API недоступен
    """
    store_slugs = [s.strip() for s in stores.split(",")] if stores else None
    queue: asyncio.Queue = asyncio.Queue()

    asyncio.create_task(_run_search(queue, q, store_slugs, limit, refresh))

    return StreamingResponse(
        _stream(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
