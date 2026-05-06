"""Управление парсерами: список магазинов и запуск одиночного поиска через SSE."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.search import _run_search, _stream
from app.deps import get_parsers_client
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
