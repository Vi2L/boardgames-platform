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
from catalog.matching.matcher import (
    AUTO_MATCH_THRESHOLD,
    classify,
    find_best_match,
    find_match_candidates,
)
from catalog.models import Game, GameAlias, Offer
from catalog.schemas import MatchingQueueOut, MatchLinkRequest, OfferOut

router = APIRouter(prefix="/matching", tags=["matching"])


@router.get(
    "/stats",
    dependencies=[Depends(require_scope("read"))],
)
async def stats(session: AsyncSession = Depends(get_session)) -> dict:
    """Сводка очереди матчинга: общий total, breakdown по магазинам и
    score-buckets.

    Bucket'ы зеркалят пороги матчера:
      - good     — score >= 0.6 (auto-threshold; почти match, оператор
                   просто подтверждает);
      - candidate — 0.3 <= score < 0.6 (показывается в очереди как
                   «есть кандидат, надо проверить»);
      - cold     — score < 0.3 OR NULL (нет кандидатов вообще).
    """
    from sqlalchemy import case
    bucket = case(
        (Offer.match_score >= 0.6, "good"),
        (Offer.match_score >= 0.3, "candidate"),
        else_="cold",
    ).label("bucket")

    by_store = (await session.execute(
        select(
            Offer.store_slug,
            func.count().label("total"),
            func.avg(Offer.match_score).label("avg_score"),
        )
        .where(Offer.match_status == "unmatched")
        .group_by(Offer.store_slug)
        .order_by(func.count().desc())
    )).all()

    by_bucket = (await session.execute(
        select(bucket, func.count().label("total"))
        .where(Offer.match_status == "unmatched")
        .group_by(bucket)
    )).all()

    total = sum(r.total for r in by_store)

    return {
        "total_unmatched": total,
        "by_store": [
            {
                "store_slug": r.store_slug,
                "total": r.total,
                "avg_score": float(r.avg_score) if r.avg_score is not None else None,
            }
            for r in by_store
        ],
        "by_bucket": {r.bucket: r.total for r in by_bucket},
        "thresholds": {"auto": 0.6, "candidate": 0.3},
    }


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
    "/{offer_id}/reassess",
    response_model=OfferOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def reassess_offer(
    offer_id: int,
    session: AsyncSession = Depends(get_session),
) -> OfferOut:
    """Пересчитать матчинг для одного offer — после правки алиасов или
    добавления BGG-импорта score у offer мог вырасти.

    Не трогает manual / rejected — оператор уже принял решение.
    Если новый score ≥ AUTO_MATCH_THRESHOLD — статус становится 'auto',
    иначе остаётся 'unmatched' с обновлённым score.
    """
    offer = (
        await session.execute(select(Offer).where(Offer.id == offer_id))
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(status_code=404, detail="offer not found")
    if offer.match_status in ("manual", "rejected"):
        raise HTTPException(
            status_code=409,
            detail=f"offer already {offer.match_status}; reassess only "
                   "unmatched/auto",
        )

    cand = await find_best_match(session, offer.title_raw)
    if cand is None:
        offer.game_id = None
        offer.match_score = None
        offer.match_status = "unmatched"
    else:
        offer.match_score = cand.score
        offer.match_status = classify(cand.score)
        offer.game_id = cand.game_id if cand.score >= AUTO_MATCH_THRESHOLD else None

    await session.commit()
    await session.refresh(offer)
    return OfferOut.model_validate(offer)


@router.post(
    "/reassess-all",
    dependencies=[Depends(require_scope("admin"))],
)
async def reassess_all(
    store: str | None = Query(None, description="ограничить магазином"),
    max_score: float | None = Query(
        None,
        description="только оффер'ы со score < max_score (или NULL)",
    ),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Batch-reassess: прогоняет find_best_match по всем unmatched.

    Полезно после массового импорта BGG/Tesera или ручной правки алиасов.
    Не трогает manual / rejected — там уже есть решение оператора.
    """
    stmt = select(Offer).where(Offer.match_status == "unmatched")
    if store:
        stmt = stmt.where(Offer.store_slug == store)
    if max_score is not None:
        # NULL включаем (offer без score = ещё не матчился)
        from sqlalchemy import or_
        stmt = stmt.where(or_(Offer.match_score < max_score, Offer.match_score.is_(None)))

    offers = (await session.execute(stmt)).scalars().all()

    promoted = 0
    improved = 0
    unchanged = 0
    for offer in offers:
        prev_score = offer.match_score
        prev_status = offer.match_status
        cand = await find_best_match(session, offer.title_raw)
        if cand is None:
            new_score, new_status, new_gid = None, "unmatched", None
        else:
            new_score = cand.score
            new_status = classify(cand.score)
            new_gid = cand.game_id if new_status == "auto" else None

        offer.match_score = new_score
        offer.match_status = new_status
        offer.game_id = new_gid

        if prev_status == "unmatched" and new_status == "auto":
            promoted += 1
        elif new_score and (prev_score is None or new_score > prev_score):
            improved += 1
        else:
            unchanged += 1

    await session.commit()
    return {
        "scanned": len(offers),
        "promoted_to_auto": promoted,
        "score_improved": improved,
        "unchanged": unchanged,
    }


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
