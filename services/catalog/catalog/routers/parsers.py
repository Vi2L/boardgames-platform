"""Роутер `/parsers/...` — операции парсеров каталога (BGG / Wikidata / ...).

Отдельный router, а не расширение `routers/imports.py`, потому что:
- `imports.py` про **запись** в БД (POST /import/bgg создаёт ImportJob,
  пишет в games);
- `parsers.py` про **чтение** из внешних источников (POST /parsers/bgg/search
  идёт в BGG API и возвращает кандидатов оператору без побочных эффектов).

Так контракт API остаётся узнаваемым: search → выбор → import.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from catalog.auth import require_scope
from catalog.parsers.bgg import BggClient, search_games
from catalog.schemas import (
    BggSearchHitOut,
    BggSearchRequest,
    BggSearchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parsers", tags=["parsers"])


def get_bgg_client() -> BggClient:
    """FastAPI dependency — фабрика BggClient'а на запрос.

    Why: тесты переопределяют через `app.dependency_overrides[get_bgg_client]`,
    подсовывая клиент с `httpx.MockTransport`. Без DI пришлось бы патчить
    `httpx.AsyncClient` глобально — а это ломает сам тест-клиент ASGITransport.
    """
    return BggClient()


@router.post(
    "/bgg/search",
    response_model=BggSearchResponse,
    dependencies=[Depends(require_scope("read"))],
)
async def bgg_search(
    payload: BggSearchRequest,
    bgg: BggClient = Depends(get_bgg_client),
) -> BggSearchResponse:
    """Поиск игр в BGG XML API по запросу.

    Сетевой вызов наружу (BGG `/search?query=<q>&type=boardgame`). Любая
    HTTP-ошибка от BGG превращается в 502 Bad Gateway — UI оператора
    отличит «BGG недоступен» от «ничего не нашлось» (последнее = 200 + count=0).

    Scope: `read` — поиск без побочных эффектов в catalog.
    """
    try:
        async with bgg:
            hits = await search_games(
                payload.query,
                limit=payload.limit,
                exact=payload.exact,
                client=bgg,
            )
    except httpx.HTTPError as exc:
        logger.warning("BGG search failed: query=%r err=%s", payload.query, exc)
        raise HTTPException(
            status_code=502,
            detail=f"BGG search failed: {exc}",
        ) from exc

    return BggSearchResponse(
        query=payload.query,
        exact=payload.exact,
        count=len(hits),
        items=[BggSearchHitOut(bgg_id=h.bgg_id, title=h.title, year=h.year) for h in hits],
    )
