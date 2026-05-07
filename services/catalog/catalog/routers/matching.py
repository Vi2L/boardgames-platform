"""UI ручного матчинга: очередь unmatched + link/reject.

GET  /matching/queue          — оффер'ы со статусом unmatched, сортировка по
                                match_score DESC (лучшие кандидаты сверху, чтобы
                                оператор быстро подтверждал «почти-match»).
POST /matching/{offer_id}/link — связать с конкретной Game; добавляем title_raw
                                как alias (manual). Статус = 'manual'.
POST /matching/{offer_id}/reject — это не игра / спам / коробка для подарка.
                                Статус = 'rejected', больше не пересматчиваем.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.matching.matcher import find_match_candidates
from catalog.models import Game, GameAlias, Offer
from catalog.schemas import MatchingQueueOut, MatchLinkRequest, OfferOut

router = APIRouter(prefix="/matching", tags=["matching"])


@router.get(
    "/candidates",
    dependencies=[Depends(require_scope("read"))],
)
async def candidates(
    title: str = Query(..., min_length=1, description="title_raw для матчинга"),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Топ-N кандидатов с score для ручного link.

    Используется при «связать» в UI: оператор видит ранжированный список
    с pg_trgm-similarity вместо просто fuzzy-search без оценки. Пороги:
    auto >= 0.6, candidate >= 0.3.
    """
    return {
        "title": title,
        "auto_threshold": 0.6,
        "candidate_threshold": 0.3,
        "items": await find_match_candidates(session, title, limit=limit),
    }


@router.get(
    "/queue",
    response_model=MatchingQueueOut,
    dependencies=[Depends(require_scope("read"))],
)
async def queue(
    store: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> MatchingQueueOut:
    stmt = select(Offer).where(Offer.match_status == "unmatched")
    if store:
        stmt = stmt.where(Offer.store_slug == store)

    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    # NULLS LAST — оффер'ы без score уходят в конец (оператор разбирает их
    # по остаточному принципу, после «горячих» кандидатов).
    stmt = (
        stmt.order_by(desc(Offer.match_score).nulls_last(), Offer.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = (await session.execute(stmt)).scalars().all()
    return MatchingQueueOut(
        items=[OfferOut.model_validate(o) for o in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{offer_id}/link",
    response_model=OfferOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def link(
    offer_id: int,
    payload: MatchLinkRequest,
    session: AsyncSession = Depends(get_session),
) -> OfferOut:
    offer = (
        await session.execute(select(Offer).where(Offer.id == offer_id))
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(status_code=404, detail="offer not found")

    game = (
        await session.execute(select(Game).where(Game.id == payload.game_id))
    ).scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")

    offer.game_id = payload.game_id
    offer.match_status = "manual"
    # match_score сохраняем как был, для аудита: «оператор подтвердил при score=X».

    # Запоминаем title_raw как alias — следующий ingest сматчится автоматически.
    await session.execute(
        pg_insert(GameAlias.__table__)
        .values(game_id=payload.game_id, alias=offer.title_raw, source="manual")
        .on_conflict_do_nothing(constraint="uq_alias_per_game")
    )
    await session.commit()
    await session.refresh(offer)
    return OfferOut.model_validate(offer)


@router.post(
    "/{offer_id}/reject",
    response_model=OfferOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def reject(
    offer_id: int, session: AsyncSession = Depends(get_session)
) -> OfferOut:
    offer = (
        await session.execute(select(Offer).where(Offer.id == offer_id))
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(status_code=404, detail="offer not found")
    offer.game_id = None
    offer.match_status = "rejected"
    await session.commit()
    await session.refresh(offer)
    return OfferOut.model_validate(offer)
