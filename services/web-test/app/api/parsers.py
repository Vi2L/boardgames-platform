"""Управление парсерами: список магазинов и запуск одиночного поиска через SSE."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.search import _run_search, _stream
from app.deps import get_parsers_client
from app.parsers_client import ParsersServiceError
from app.schemas import ParserStatsOut

router = APIRouter(prefix="/parsers", tags=["parsers"])


@router.get("", response_model=list[ParserStatsOut])
async def list_parsers() -> list[ParserStatsOut]:
    """Возвращает список магазинов как «парсеры».

    Проверяет доступность parsers API — если недоступен, available=False.
    """
    client = get_parsers_client()
    try:
        stores = await client.get_stores()
        return [
            ParserStatsOut(slug=s.slug, name=s.name, base_url=s.base_url, available=True)
            for s in stores
        ]
    except Exception:
        return []


@router.delete("/cache")
async def invalidate_cache(
    store: str | None = Query(None, description="Slug магазина"),
    q: str | None = Query(None, description="Подстрока запроса"),
    confirm: bool = Query(False, description="Wipe всё (требует true без store/q)"),
) -> dict:
    """Инвалидация кеша parsers.

    Тонкий прокси на DELETE /api/cache parsers. Без store и q parsers
    отвечает 400, если confirm не выставлен — мы пробрасываем это требование.
    """
    client = get_parsers_client()
    try:
        return await client.invalidate_cache(store=store, q=q, confirm=confirm)
    except ParsersServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/{slug}/run")
async def run_parser(
    slug: str,
    q: str = Query(..., min_length=1, description="Поисковый запрос"),
    limit: int = Query(10, ge=1, le=50),
) -> StreamingResponse:
    """Запускает поиск по одному магазину с полным SSE-стримом.

    refresh=True — всегда обращается к магазину напрямую, минуя кеш.
    """
    queue: asyncio.Queue = asyncio.Queue()
    asyncio.create_task(_run_search(queue, q, store_slugs=[slug], limit=limit, refresh=True))

    return StreamingResponse(
        _stream(queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
