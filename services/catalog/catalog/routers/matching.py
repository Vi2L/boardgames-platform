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

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select
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
from catalog.matching.v2 import normalize_title
from catalog.matching.v2.auditor import (
    log_change,
    revert_batch as v2_revert_batch,
    revert_many as v2_revert_many,
    revert_one as v2_revert_one,
)
from catalog.matching.v2.decisions import (
    invalidate_for_game,
    save_decision,
)
from catalog.matching.v2.domain import MatchAction
from catalog.matching.v2.health import OllamaHealth
from catalog.matching.v2.queue_repo import count_by_status as v2_count_by_status
from catalog.models import Game, GameAlias, MatchLog, Offer
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

    # Состояние очереди match_queue (matching v2). Здесь:
    # - `pending` — ждут воркера (T2/T3).
    # - `processing` — в работе прямо сейчас.
    # - `skipped` — ML дошёл до T4 (manual). Эти офферы НЕ всплывают в
    #   `/matching/queue` сами по себе (тот фильтрует по `offers.match_status`),
    #   но они существуют в очереди как «отдано оператору». Без этой метрики
    #   оператор не знал бы что они есть.
    # - `failed` — исчерпан backoff retry; оператор должен глянуть error_detail.
    queue_counts = await v2_count_by_status(session)

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
        "queue": {
            "pending": queue_counts.get("pending", 0),
            "processing": queue_counts.get("processing", 0),
            "skipped": queue_counts.get("skipped", 0),
            "failed": queue_counts.get("failed", 0),
            "done": queue_counts.get("done", 0),
        },
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
    was_linked: bool | None = Query(None, description="фильтр по was_linked"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> MatchingQueueOut:
    stmt = select(Offer).where(Offer.match_status == "unmatched")
    if store:
        stmt = stmt.where(Offer.store_slug == store)
    if was_linked is not None:
        stmt = stmt.where(Offer.was_linked == was_linked)

    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    # was_linked=True офферы всплывают вверху — оператор мог ошибиться при
    # первом матче, такие требуют повторного внимания. Далее — по score DESC.
    stmt = (
        stmt.order_by(
            Offer.was_linked.desc(),
            desc(Offer.match_score).nulls_last(),
            Offer.id.desc(),
        )
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

    prev_game_id = offer.game_id
    prev_status = offer.match_status

    offer.game_id = payload.game_id
    offer.match_status = "manual"
    # match_score сохраняем как был, для аудита: «оператор подтвердил при score=X».

    # Запоминаем title_raw как alias — следующий ingest сматчится автоматически.
    alias_stmt = (
        pg_insert(GameAlias.__table__)
        .values(game_id=payload.game_id, alias=offer.title_raw, source="manual")
        .on_conflict_do_nothing(constraint="uq_alias_per_game")
        .returning(GameAlias.__table__.c.id)
    )
    alias_row = (await session.execute(alias_stmt)).first()
    alias_id_created = int(alias_row[0]) if alias_row else None

    # Matcher v2: сохраняем решение в Tier 0 cache (manual = бессрочно).
    await save_decision(
        session,
        title_norm=normalize_title(offer.title_raw),
        game_id=payload.game_id,
        source="manual",
        tier=None,
        score=offer.match_score,
    )

    # Matcher v2: аудит-запись.
    await log_change(
        session,
        offer_id=offer_id,
        action=MatchAction.MANUAL,
        prev_game_id=prev_game_id,
        new_game_id=payload.game_id,
        prev_status=prev_status,
        new_status="manual",
        score=offer.match_score,
        alias_created_id=alias_id_created,
        performed_by="operator",
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
    "/{offer_id}/unlink",
    response_model=OfferOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def unlink(
    offer_id: int, session: AsyncSession = Depends(get_session)
) -> OfferOut:
    """Отвязать оффер от игры — вернуть в очередь для повторного матчинга.

    Устанавливает was_linked=True, чтобы оффер всплыл выше в очереди.
    Алиас, добавленный при link, намеренно НЕ удаляем — он улучшает
    будущий авто-матч других офферов с таким же title_raw.
    """
    offer = (
        await session.execute(select(Offer).where(Offer.id == offer_id))
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(status_code=404, detail="offer not found")
    if offer.match_status not in ("manual", "auto"):
        raise HTTPException(
            status_code=409,
            detail=f"offer is not linked (status={offer.match_status}); unlink only manual/auto",
        )

    prev_game_id = offer.game_id
    prev_status = offer.match_status

    offer.game_id = None
    offer.match_status = "unmatched"
    offer.was_linked = True
    # match_score сохраняем — помогает при повторном триаже понять,
    # насколько уверенным был исходный матч.

    # Matcher v2: инвалидация cache + audit log.
    if prev_game_id is not None:
        await invalidate_for_game(session, prev_game_id)
    await log_change(
        session,
        offer_id=offer_id,
        action=MatchAction.UNLINK,
        prev_game_id=prev_game_id,
        new_game_id=None,
        prev_status=prev_status,
        new_status="unmatched",
        performed_by="operator",
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

    prev_game_id = offer.game_id
    prev_status = offer.match_status

    offer.game_id = None
    offer.match_status = "rejected"

    # Matcher v2: negative cache (game_id=NULL) — следующий ingest этого title
    # вернёт cached_reject и не пушит в очередь повторно.
    await save_decision(
        session,
        title_norm=normalize_title(offer.title_raw),
        game_id=None,
        source="manual",
        tier=None,
        score=None,
    )

    # Matcher v2: audit log.
    await log_change(
        session,
        offer_id=offer_id,
        action=MatchAction.REJECT,
        prev_game_id=prev_game_id,
        new_game_id=None,
        prev_status=prev_status,
        new_status="rejected",
        performed_by="operator",
    )

    await session.commit()
    await session.refresh(offer)
    return OfferOut.model_validate(offer)


# ─── Matcher v2: ML status + match_log API ────────────────────────────────────


@router.get(
    "/ml-status",
    dependencies=[Depends(require_scope("read"))],
)
async def ml_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Состояние Ollama + размер очереди T2/T3 для UI MlStatusBadge.

    `models` — словарь model_name → bool (доступна ли). `queue` — counts по
    статусам match_queue (pending/processing/done/failed/skipped).
    """
    health = OllamaHealth.get_instance()
    queue_counts = await v2_count_by_status(session)
    return {
        **health.status_summary,
        "queue": queue_counts,
    }


class MatchLogOut(BaseModel):
    """Одна запись match_log для UI отчёта."""
    id: int
    offer_id: int
    prev_game_id: int | None = None
    new_game_id: int | None = None
    prev_status: str | None = None
    new_status: str
    action: str
    tier: int | None = None
    score: float | None = None
    reason: str | None = None
    batch_id: str | None = None
    alias_created_id: int | None = None
    performed_by: str | None = None
    performed_at: str
    reverted_at: str | None = None
    reverted_by: str | None = None
    # Контекстные поля из JOIN с offers + games — упрощают UI.
    title_raw: str | None = None
    store_slug: str | None = None
    new_game_title: str | None = None
    prev_game_title: str | None = None


class MatchLogPage(BaseModel):
    items: list[MatchLogOut]
    total: int
    limit: int
    offset: int


@router.get(
    "/log",
    response_model=MatchLogPage,
    dependencies=[Depends(require_scope("read"))],
)
async def get_log(
    offer_id: int | None = Query(None),
    action: str | None = Query(None, description="фильтр по action (auto_t1, manual, ...)"),
    tier: int | None = Query(None, ge=0, le=3),
    performed_by: str | None = Query(None),
    only_active: bool = Query(False, description="скрыть reverted записи"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> MatchLogPage:
    """Журнал решений матчинга. Фильтры + пагинация. JOIN с offer и games
    для контекста — UI сразу видит title_raw и game_title."""
    from sqlalchemy.orm import aliased

    NewGame = aliased(Game)
    PrevGame = aliased(Game)

    base = (
        select(MatchLog, Offer.title_raw, Offer.store_slug,
               NewGame.title.label("new_title"), PrevGame.title.label("prev_title"))
        .join(Offer, Offer.id == MatchLog.offer_id, isouter=True)
        .join(NewGame, NewGame.id == MatchLog.new_game_id, isouter=True)
        .join(PrevGame, PrevGame.id == MatchLog.prev_game_id, isouter=True)
    )

    if offer_id is not None:
        base = base.where(MatchLog.offer_id == offer_id)
    if action:
        base = base.where(MatchLog.action == action)
    if tier is not None:
        base = base.where(MatchLog.tier == tier)
    if performed_by:
        base = base.where(MatchLog.performed_by == performed_by)
    if only_active:
        base = base.where(MatchLog.reverted_at.is_(None))

    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    rows = (await session.execute(
        base.order_by(desc(MatchLog.performed_at)).limit(limit).offset(offset)
    )).all()

    items = [
        MatchLogOut(
            id=log.id,
            offer_id=log.offer_id,
            prev_game_id=log.prev_game_id,
            new_game_id=log.new_game_id,
            prev_status=log.prev_status,
            new_status=log.new_status,
            action=log.action,
            tier=log.tier,
            score=log.score,
            reason=log.reason,
            batch_id=str(log.batch_id) if log.batch_id else None,
            alias_created_id=log.alias_created_id,
            performed_by=log.performed_by,
            performed_at=log.performed_at.isoformat(),
            reverted_at=log.reverted_at.isoformat() if log.reverted_at else None,
            reverted_by=log.reverted_by,
            title_raw=title_raw,
            store_slug=store_slug,
            new_game_title=new_title,
            prev_game_title=prev_title,
        )
        for log, title_raw, store_slug, new_title, prev_title in rows
    ]
    return MatchLogPage(items=items, total=total, limit=limit, offset=offset)


class RevertOneRequest(BaseModel):
    delete_alias: bool = False


class RevertManyRequest(BaseModel):
    log_ids: list[int]
    delete_alias: bool = False


class RevertBatchRequest(BaseModel):
    batch_id: UUID
    delete_alias: bool = False


@router.post(
    "/log/{log_id}/revert",
    dependencies=[Depends(require_scope("admin"))],
)
async def revert_log_one(
    log_id: int,
    payload: RevertOneRequest = RevertOneRequest(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Откат одной записи match_log.

    Восстанавливает offer.game_id + match_status из prev_*. Опционально удаляет
    alias, добавленный этой записью. Удаляет match_decisions cache для title.
    """
    try:
        result = await v2_revert_one(
            session, log_id, delete_alias=payload.delete_alias,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()
    return result


@router.post(
    "/log/bulk-revert",
    dependencies=[Depends(require_scope("admin"))],
)
async def revert_log_bulk(
    payload: RevertManyRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Bulk-revert по списку id (выбор чекбоксами в UI). Одна транзакция."""
    if not payload.log_ids:
        raise HTTPException(status_code=400, detail="log_ids required")
    result = await v2_revert_many(
        session, payload.log_ids, delete_alias=payload.delete_alias,
    )
    await session.commit()
    return result


@router.post(
    "/log/batch-revert",
    dependencies=[Depends(require_scope("admin"))],
)
async def revert_batch_endpoint(
    payload: RevertBatchRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Bulk-revert по batch_id (один reassess-all = один UUID).

    Полезно для отката массовых reassess-операций одной командой.
    """
    result = await v2_revert_batch(
        session, payload.batch_id, delete_alias=payload.delete_alias,
    )
    await session.commit()
    return result


# ─── Embedding warmup (admin-only) ───────────────────────────────────────────


class WarmupRequest(BaseModel):
    """POST /matching/warmup-embeddings — запуск прогрева через ImportJob."""
    batch_size: int = 32
    limit: int | None = None
    only_games: bool = False
    only_aliases: bool = False


@router.post(
    "/warmup-embeddings",
    dependencies=[Depends(require_scope("admin"))],
)
async def warmup_embeddings(
    payload: WarmupRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Запуск warmup в фоне. Возвращает import_job_id; UI polling'ит его.

    Использует существующий ImportJob паттерн (как enrich_bgg / dicefest),
    чтобы не плодить новый прогресс-механизм. type='embedding-warmup'.
    """
    import asyncio

    from catalog.models import ImportJob
    from catalog.scripts.warmup_embeddings import warmup

    # Один warmup за раз (защита от двойного клика)
    existing = (await session.execute(
        select(ImportJob.id).where(
            ImportJob.type == "embedding-warmup",
            ImportJob.status.in_(("pending", "running")),
        ).limit(1)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, detail=f"warmup уже выполняется (job_id={existing})")

    job = ImportJob(
        type="embedding-warmup",
        payload=payload.model_dump(),
        status="running",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    job_id = job.id

    async def _runner() -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from catalog.db import get_engine

        try:
            summary = await warmup(
                batch_size=payload.batch_size,
                limit=payload.limit,
                only_games=payload.only_games,
                only_aliases=payload.only_aliases,
                job_id=job_id,
            )
            SessionFactory = async_sessionmaker(get_engine(), expire_on_commit=False)
            async with SessionFactory() as s:
                j = await s.get(ImportJob, job_id)
                if j is not None:
                    j.status = "done"
                    j.result = summary
                await s.commit()
        except Exception as e:  # noqa: BLE001
            from sqlalchemy.ext.asyncio import async_sessionmaker
            from catalog.db import get_engine

            SessionFactory = async_sessionmaker(get_engine(), expire_on_commit=False)
            async with SessionFactory() as s:
                j = await s.get(ImportJob, job_id)
                if j is not None:
                    j.status = "failed"
                    j.error = str(e)
                await s.commit()

    asyncio.create_task(_runner(), name=f"warmup-embeddings-{job_id}")
    return {"job_id": job_id, "status": "running"}
