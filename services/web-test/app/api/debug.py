"""Debug-эндпоинты: проксирование диагностических ручек parsers.

Web-test — тонкий прокси: ловит ParsersServiceError и маппит его в HTTPException,
чтобы фронт получал структурированный {"detail": "..."} вместо stack-trace.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_parsers_client
from app.parsers_client import ParsersClient, ParsersServiceError

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/parse")
async def debug_parse(
    q: str = Query(..., min_length=1, description="Поисковый запрос для парсера"),
    stores: str | None = Query(None, description="Магазины через запятую (опционально)"),
    limit: int = Query(5, ge=1, le=20),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    """Live Test — запустить парсеры мимо кеша.

    Возвращает структуру от parsers как есть:
    `{"query": str, "results": {<slug>: {products, count, duration_ms, metrics, error}}}`.
    """
    store_list = [s.strip() for s in stores.split(",") if s.strip()] if stores else None
    try:
        return await client.debug_parse(q=q, stores=store_list, limit=limit)
    except ParsersServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
