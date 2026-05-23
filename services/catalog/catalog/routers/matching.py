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

from uuid import UUID, uuid4

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.config import get_settings
from catalog.db import get_session
from catalog.matching.matcher import (
    AUTO_MATCH_THRESHOLD,
    classify,
    find_best_match,
    find_match_candidates,
)
from catalog.matching.v2 import match_sync, normalize_title
from catalog.matching.v2.auditor import (
    log_change,
    revert_batch as v2_revert_batch,
    revert_many as v2_revert_many,
    revert_one as v2_revert_one,
)
from catalog.matching.v2.decisions import (
    invalidate_bulk,
    invalidate_for_game,
    invalidate_for_title,
    save_decision,
)
from catalog.matching.v2.domain import MatchAction
from catalog.matching.v2.health import OllamaHealth
from catalog.matching.v2.queue_repo import (
    cancel_pending as v2_cancel_pending,
    count_by_status as v2_count_by_status,
    depth_history as v2_depth_history,
    enqueue as v2_enqueue,
    lookup_queue_item as v2_lookup_queue_item,
)
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


async def _apply_match_result(
    session: AsyncSession,
    offer: Offer,
    result,  # MatchResult из catalog.matching.v2.domain
    *,
    prev_game_id: int | None,
    prev_status: str | None,
    performed_by: str,
    batch_id: UUID | None = None,
) -> str:
    """Применяет MatchResult к Offer + пишет save_decision + log_change.

    Используется и `reassess_offer` (single), и `reassess_all` (batch).
    Возвращает строковый идентификатор итога:
      - "matched_auto"   — установлен game_id, match_status='auto'
      - "queued_ml"      — отправлен в match_queue (ML on, нет уверенного матча)
      - "unmatched"      — match_status='unmatched' (ML off / no candidates)
      - "rejected_cache" — T0 cache вернул negative (cached_reject)
    """
    if result.matched:
        # T0/T1/T2/T3 нашёл матч.
        offer.game_id = result.game_id
        offer.match_score = result.score
        offer.match_tier = result.tier
        offer.match_reason = result.reason
        offer.match_status = "auto"
        # Cache решение в match_decisions — НО только если это новый матч (T1+),
        # для T0 запись уже существует, повторный save_decision — лишний UPDATE.
        if result.tier and result.tier >= 1:
            await save_decision(
                session,
                title_norm=normalize_title(offer.title_raw),
                game_id=result.game_id,
                source=f"auto_t{result.tier}",
                tier=result.tier,
                score=result.score,
            )
        outcome = "matched_auto"
    elif result.action == MatchAction.REJECT:
        # T0 negative cache — оператор когда-то отверг этот title (либо LLM
        # T3 решил «не настолка»). Синхронизируем `match_status='rejected'`,
        # чтобы оффер не оставался в `unmatched`-очереди после reassess.
        # Раньше (до CR-A) обновлялся только match_reason — это приводило к
        # «зомби-офферам»: T0 продолжал возвращать cached_reject, оффер
        # бесконечно висел в unmatched, оператор видел его при каждом reassess.
        offer.game_id = None
        offer.match_status = "rejected"
        offer.match_tier = result.tier
        offer.match_reason = result.reason
        outcome = "rejected_cache"
    elif result.needs_async:
        # ML on + sync tier'ы не сошлись — отправляем в очередь воркера.
        # match_status стайл 'pending_ml' — UI не будет показывать оффер в
        # unmatched-очереди, а воркер подберёт.
        offer.match_score = result.score
        offer.match_tier = result.tier
        offer.match_reason = result.reason
        offer.match_status = "pending_ml"
        # priority=5 (выше дефолтного ingest=0) — reassess обычно делает оператор
        # и он ждёт результата быстрее, чем фоновый ingest.
        await v2_enqueue(
            session,
            offer_id=offer.id,
            store_slug=offer.store_slug,
            title_raw=offer.title_raw,
            title_norm=normalize_title(offer.title_raw),
            priority=5,
        )
        outcome = "queued_ml"
    else:
        # ML off + не сошлись tier'ы — оставляем в unmatched с лучшим score.
        offer.game_id = None
        offer.match_score = result.score
        offer.match_tier = result.tier
        offer.match_reason = result.reason
        offer.match_status = "unmatched"
        outcome = "unmatched"

    # Аудит — для всех исходов, включая `rejected_cache`: после фикса CR-A
    # status может измениться (`unmatched → rejected`), это важно для revert.
    # Если оффер был уже `rejected` до reassess — log_change запишет всё равно,
    # но с одинаковыми prev/new — UI может фильтровать через only_active.
    await log_change(
        session,
        offer_id=offer.id,
        action=MatchAction.REASSESS,
        prev_game_id=prev_game_id,
        new_game_id=offer.game_id,
        prev_status=prev_status,
        new_status=offer.match_status,
        tier=result.tier,
        score=result.score,
        reason=result.reason,
        batch_id=batch_id,
        performed_by=performed_by,
    )
    return outcome


@router.post(
    "/{offer_id}/reassess",
    response_model=OfferOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def reassess_offer(
    offer_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> OfferOut:
    """Пересчитать матчинг для одного offer через v2 pipeline (CAT-17).

    Запускает синхронный T0 → T1 (с title_pipeline + лемматизация). При
    промахе и включённом ML — отправляет в очередь воркера (T2/T3),
    match_status становится 'pending_ml'. UI должен polling'ить queue item.

    Не трогает manual / rejected — оператор уже принял решение.
    Изменения пишутся в `match_log` с `action=REASSESS` для возможности revert.
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
                   "unmatched/auto/pending_ml",
        )

    prev_game_id = offer.game_id
    prev_status = offer.match_status

    result = await match_sync(session, offer.title_raw, store_slug=offer.store_slug)
    await _apply_match_result(
        session, offer, result,
        prev_game_id=prev_game_id, prev_status=prev_status,
        performed_by=_performed_by_from_request(request),
    )

    await session.commit()
    await session.refresh(offer)
    return OfferOut.model_validate(offer)


# Лимит batch'а reassess-all — защита от OOM на больших unmatched-очередях.
# При >500 unmatched оператор должен запускать несколько раз / итерационно.
_REASSESS_ALL_LIMIT = 500


@router.post(
    "/reassess-all",
    dependencies=[Depends(require_scope("admin"))],
)
async def reassess_all(
    request: Request,
    store: str | None = Query(None, description="ограничить магазином"),
    max_score: float | None = Query(
        None,
        description="только оффер'ы со score < max_score (или NULL)",
    ),
    after_id: int | None = Query(
        None,
        description="cursor: обработать только offer.id > after_id "
                    "(использовать `next_after_id` из предыдущего ответа)",
    ),
    limit: int = Query(
        _REASSESS_ALL_LIMIT, ge=1, le=_REASSESS_ALL_LIMIT,
        description=f"максимум офферов за один прогон (потолок {_REASSESS_ALL_LIMIT})",
    ),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Batch-reassess: прогоняет match_sync v2 по unmatched-офферам (CAT-17).

    Один прогон = один `batch_id` (UUID). Это позволяет одной командой
    `POST /matching/log/batch-revert` откатить весь batch если оператор
    обнаружил систематическую ошибку.

    **Pagination через cursor**: `after_id` ограничивает выборку до
    `offer.id > after_id`. Response возвращает `next_after_id` =
    максимальный id обработанного batch'а — клиент передаёт его в
    следующий запрос. Это решает проблему «после reassess офферы
    остались unmatched → следующий batch берёт те же 500».

    Лимит на batch — 500 (`_REASSESS_ALL_LIMIT`). Защита от OOM и от
    чрезмерной нагрузки на Ollama при ML on.

    Не трогает manual / rejected — там уже есть решение оператора.
    """
    stmt = (
        select(Offer)
        .where(Offer.match_status == "unmatched")
        .order_by(Offer.id)
        .limit(limit)
    )
    if store:
        stmt = stmt.where(Offer.store_slug == store)
    if max_score is not None:
        # NULL включаем (offer без score = ещё не матчился)
        stmt = stmt.where(
            or_(Offer.match_score < max_score, Offer.match_score.is_(None))
        )
    if after_id is not None:
        stmt = stmt.where(Offer.id > after_id)

    offers = (await session.execute(stmt)).scalars().all()
    if not offers:
        return {
            "scanned": 0, "promoted_to_auto": 0, "queued_ml": 0,
            "score_improved": 0, "unchanged": 0,
            "batch_id": None, "limit_hit": False,
            "next_after_id": None,
        }

    batch_id = uuid4()
    performed_by = _performed_by_from_request(request)
    # Загружаем pipeline один раз — переиспользуем для всех офферов batch'а.
    # Это критично: load_pipeline() кешируется на 5 мин, но первый вызов
    # делает SELECT из match_publisher_prefixes — если делать его в каждой
    # итерации, это лишние 500 round-trip'ов к БД.
    from catalog.matching.title_pipeline import load_pipeline
    pipeline = await load_pipeline(session)

    promoted = 0
    queued = 0
    improved = 0
    unchanged = 0

    for offer in offers:
        prev_score = offer.match_score
        prev_status = offer.match_status
        prev_game_id = offer.game_id

        result = await match_sync(
            session, offer.title_raw,
            store_slug=offer.store_slug,
            pipeline=pipeline,
        )
        outcome = await _apply_match_result(
            session, offer, result,
            prev_game_id=prev_game_id, prev_status=prev_status,
            performed_by=performed_by,
            batch_id=batch_id,
        )

        if outcome == "matched_auto":
            promoted += 1
        elif outcome == "queued_ml":
            queued += 1
        elif outcome == "unmatched" and result.score and (
            prev_score is None or result.score > prev_score
        ):
            improved += 1
        else:
            unchanged += 1

    await session.commit()
    return {
        "scanned": len(offers),
        "promoted_to_auto": promoted,
        "queued_ml": queued,
        "score_improved": improved,
        "unchanged": unchanged,
        "batch_id": str(batch_id),
        # Подсказка UI: пользователь видит, что лимит достигнут и надо запустить ещё раз.
        "limit_hit": len(offers) == limit,
        # Cursor для следующего batch'а — max id обработанного.
        # offers отсортированы ORDER BY id ASC, поэтому max = offers[-1].id.
        "next_after_id": offers[-1].id if offers else None,
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
    # nullable с CAT-12: action='invalidate' не привязан к оферу.
    offer_id: int | None = None
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


# ─── Matcher v2: queue management (re-enqueue + штучный) + offer lookup ──────


class SkippedQueueItemOut(BaseModel):
    id: int
    offer_id: int
    store_slug: str
    title_raw: str
    error_detail: str | None = None
    result_score: float | None = None
    attempts: int
    created_at: str
    processed_at: str | None = None


class SkippedQueuePageOut(BaseModel):
    items: list[SkippedQueueItemOut]
    total: int
    limit: int
    offset: int
    # breakdowns по ВСЕМ skipped (без активных фильтров) — оператор видит что
    # ещё есть в очереди по другим store/reason без переключения фильтра.
    stores: dict[str, int]
    reasons: dict[str, int]


# Известные prefix'ы reason'ов из worker'а. Используем для bucket'ования в
# breakdown и валидации фильтра. См. worker.py / embeddings.py / llm_arbiter.py.
KNOWN_SKIP_REASONS = (
    "llm_unavailable",
    "llm_disabled",          # legacy — до hardening 2026-05-16; оставляем для старых записей
    "llm_no_match",          # T3 LLM сказал "нет совпадения" (с двумя 'l' — префикс из llm_arbiter)
    "llm_low_confidence",
    "llm_parse_failed",
    "no_candidates",
    "vec_no_candidates",
    "vec_below_threshold",
    "vec_ambiguous",
    "raced_manual",
    "raced_rejected",
    "offer_disappeared",
)


def _reason_bucket_case_sql() -> str:
    """CASE-выражение, нормализующее error_detail в один из known reason-prefix'ов.

    error_detail может содержать ПОЛНЫЙ контекст (`llm_unavailable: connect refused`),
    но для UI группировки нам нужен только верхушка дерева. Делаем prefix-match.
    """
    branches = "\n".join(
        f"            WHEN error_detail LIKE '{r}%' THEN '{r}'"
        for r in KNOWN_SKIP_REASONS
    )
    return f"""
        CASE
{branches}
            ELSE COALESCE(error_detail, 'unknown')
        END
    """


@router.get(
    "/queue/skipped",
    response_model=SkippedQueuePageOut,
    dependencies=[Depends(require_scope("read"))],
)
async def list_skipped_queue(
    store_slug: list[str] = Query(default_factory=list),
    reason: list[str] = Query(default_factory=list),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> SkippedQueuePageOut:
    """match_queue WHERE status='skipped' с фильтрами + breakdown.

    Фильтры — multi-value (FastAPI собирает `?store_slug=a&store_slug=b` в list).
    Reason match — prefix через `error_detail LIKE 'reason%'`: воркер пишет
    detail c контекстом, например `'llm_unavailable: connect refused'`, а
    оператор фильтрует по `'llm_unavailable'`.

    Breakdown `stores` / `reasons` всегда считается по ВСЕМ skipped (без
    активных фильтров) — оператор видит общую картину, не «обрезанную»
    своими же фильтрами.
    """
    where: list[str] = ["status = 'skipped'"]
    params: dict[str, Any] = {}

    if store_slug:
        where.append("store_slug = ANY(:stores)")
        params["stores"] = store_slug

    if reason:
        # array containment: хотя бы один reason должен быть prefix у error_detail
        where.append(
            "EXISTS (SELECT 1 FROM unnest(CAST(:reasons AS text[])) r "
            "WHERE error_detail LIKE r || '%')"
        )
        params["reasons"] = reason

    where_sql = " AND ".join(where)

    # total + items в одной session
    total = (await session.execute(
        text(f"SELECT COUNT(*) FROM match_queue WHERE {where_sql}").bindparams(**params)
    )).scalar_one()

    items_rows = (await session.execute(
        text(
            f"""
            SELECT id, offer_id, store_slug, title_raw, error_detail,
                   result_score, attempts,
                   created_at::text  AS created_at,
                   processed_at::text AS processed_at
            FROM match_queue
            WHERE {where_sql}
            ORDER BY processed_at DESC NULLS LAST, id DESC
            LIMIT :limit OFFSET :offset
            """
        ).bindparams(**params, limit=limit, offset=offset)
    )).mappings().all()

    # Breakdown по всем skipped — без активных фильтров. Один SELECT для
    # stores, другой для reasons. Это дешёво (≤сотни строк в среднем).
    stores_rows = (await session.execute(
        text("SELECT store_slug, COUNT(*) AS n FROM match_queue WHERE status = 'skipped' GROUP BY store_slug")
    )).mappings().all()
    stores_map = {r["store_slug"]: int(r["n"]) for r in stores_rows}

    reasons_sql = f"""
        SELECT {_reason_bucket_case_sql()} AS r, COUNT(*) AS n
        FROM match_queue
        WHERE status = 'skipped'
        GROUP BY r
        ORDER BY n DESC
    """
    reasons_rows = (await session.execute(text(reasons_sql))).mappings().all()
    reasons_map = {r["r"]: int(r["n"]) for r in reasons_rows}

    return SkippedQueuePageOut(
        items=[SkippedQueueItemOut(**dict(r)) for r in items_rows],
        total=int(total),
        limit=limit,
        offset=offset,
        stores=stores_map,
        reasons=reasons_map,
    )


class ReEnqueueRequest(BaseModel):
    """POST /matching/queue/re-enqueue-skipped.

    Если `offer_ids` передан — re-enqueue ровно эти id (точечная операция).
    Иначе — фильтры store_slug/reason применяются ко всем skipped. Если оба
    набора пустые — re-enqueue ВСЕ skipped (требует подтверждения на UI).
    """
    offer_ids: list[int] | None = None
    store_slug: list[str] | None = None
    reason: list[str] | None = None


class ReEnqueueResultOut(BaseModel):
    requested: int
    re_enqueued: int


@router.post(
    "/queue/re-enqueue-skipped",
    response_model=ReEnqueueResultOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def re_enqueue_skipped(
    payload: ReEnqueueRequest,
    session: AsyncSession = Depends(get_session),
) -> ReEnqueueResultOut:
    """Возвращает skipped → pending. Воркер обработает в ближайшем тике.

    Семантика идентична `enqueue` ON CONFLICT DO UPDATE из queue_repo: сбрасываем
    attempts, next_attempt_at, error_detail и result_*. claimed_at тоже сбрасываем
    (был установлен старым claim'ом, иначе recover_stuck может ошибиться).
    """
    where: list[str] = ["status = 'skipped'"]
    params: dict[str, Any] = {}

    if payload.offer_ids:
        # точечный re-enqueue — игнорирует фильтры store/reason
        where.append("offer_id = ANY(:ids)")
        params["ids"] = payload.offer_ids
    else:
        if payload.store_slug:
            where.append("store_slug = ANY(:stores)")
            params["stores"] = payload.store_slug
        if payload.reason:
            where.append(
                "EXISTS (SELECT 1 FROM unnest(CAST(:reasons AS text[])) r "
                "WHERE error_detail LIKE r || '%')"
            )
            params["reasons"] = payload.reason

    where_sql = " AND ".join(where)

    # count перед update — для отчёта оператору сколько имеем перед операцией
    requested = (await session.execute(
        text(f"SELECT COUNT(*) FROM match_queue WHERE {where_sql}").bindparams(**params)
    )).scalar_one()

    result = await session.execute(
        text(
            f"""
            UPDATE match_queue
            SET status = 'pending',
                attempts = 0,
                next_attempt_at = NULL,
                error_detail = NULL,
                processed_at = NULL,
                claimed_at = NULL,
                result_game_id = NULL,
                result_score = NULL,
                result_tier = NULL
            WHERE {where_sql}
            """
        ).bindparams(**params)
    )
    await session.commit()
    return ReEnqueueResultOut(requested=int(requested), re_enqueued=result.rowcount or 0)


class RunV2ResponseOut(BaseModel):
    offer_id: int
    queued: bool
    priority: int
    queue_id: int | None = None


@router.post(
    "/{offer_id}/run-v2",
    response_model=RunV2ResponseOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def run_v2_on_offer(
    offer_id: int,
    session: AsyncSession = Depends(get_session),
) -> RunV2ResponseOut:
    """Прогон одного offer через v2 pipeline (T2/T3 в воркере).

    Технически — enqueue в `match_queue` с `priority=10` (поднимает запись в
    начало очереди при следующем тике). Не sync с inline-результатом — Ollama
    может отвечать 10-30 сек, держать HTTP-request это много (timeout риск).

    Если offer уже в очереди (UNIQUE offer_id) — ON CONFLICT сбрасывает в
    pending с priority=10. Безопасно вызывать повторно.
    """
    offer = await session.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail=f"offer {offer_id} not found")

    queue_id = await v2_enqueue(
        session,
        offer_id=offer_id,
        store_slug=offer.store_slug,
        title_raw=offer.title_raw,
        title_norm=normalize_title(offer.title_raw),
        priority=10,
    )
    await session.commit()
    return RunV2ResponseOut(
        offer_id=offer_id,
        queued=True,
        priority=10,
        queue_id=queue_id,
    )


class OfferLookupOut(BaseModel):
    id: int
    store_slug: str
    external_id: str
    title_raw: str
    url: str | None = None
    image_url: str | None = None
    last_price: int | None = None
    game_id: int | None = None
    match_status: str
    match_score: float | None = None
    match_tier: int | None = None
    match_reason: str | None = None


def _offer_to_lookup(o: Offer) -> OfferLookupOut:
    return OfferLookupOut(
        id=o.id, store_slug=o.store_slug, external_id=o.external_id,
        title_raw=o.title_raw, url=o.url, image_url=o.image_url,
        last_price=o.last_price, game_id=o.game_id,
        match_status=o.match_status, match_score=o.match_score,
        match_tier=o.match_tier, match_reason=o.match_reason,
    )


class OffersSearchOut(BaseModel):
    items: list[OfferLookupOut]


# ВАЖНО: `/offers/search` декларируется ДО `/offers/{offer_id}` — иначе FastAPI
# попытается парсить строку "search" как int и вернёт 422. Path order имеет
# значение, и здесь это explicit assumption.
@router.get(
    "/offers/search",
    response_model=OffersSearchOut,
    dependencies=[Depends(require_scope("read"))],
)
async def search_offers(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> OffersSearchOut:
    """Fuzzy lookup по подстроке title (для UI «найти offer по title»).

    ILIKE без trgm — для UI типа этого хватает (мало результатов, не индекс).
    Сортировка: сначала unmatched (оператор скорее всего ищет проблемный),
    потом по id DESC (свежие). Trgm score-сортировка пока не делаем — UI
    не показывает score в этом списке.
    """
    rows = (await session.execute(
        select(Offer)
        .where(Offer.title_raw.ilike(f"%{q}%"))
        .order_by(
            # unmatched / rejected подняты вверх — обычно их ищут.
            case(
                (Offer.match_status == "unmatched", 0),
                (Offer.match_status == "rejected", 1),
                else_=2,
            ),
            Offer.id.desc(),
        )
        .limit(limit)
    )).scalars().all()
    return OffersSearchOut(items=[_offer_to_lookup(o) for o in rows])


@router.get(
    "/offers/{offer_id}",
    response_model=OfferLookupOut,
    dependencies=[Depends(require_scope("read"))],
)
async def lookup_offer(
    offer_id: int,
    session: AsyncSession = Depends(get_session),
) -> OfferLookupOut:
    """Lookup одного offer с диагностическими полями матчинга — для штучного
    панель в /matching → Штучный."""
    o = await session.get(Offer, offer_id)
    if o is None:
        raise HTTPException(status_code=404, detail=f"offer {offer_id} not found")
    return _offer_to_lookup(o)


# ─── Matcher v2: queue depth / lookup / cancel (UX-improvements §A/§D/§E) ────


class QueueDepthPoint(BaseModel):
    ts: str
    depth: int


class QueueDepthOut(BaseModel):
    points: list[QueueDepthPoint]
    current: int
    peak: int
    drainage_rate_per_min: float
    range_hours: int
    bucket_minutes: int


@router.get(
    "/queue/depth",
    response_model=QueueDepthOut,
    dependencies=[Depends(require_scope("read"))],
)
async def queue_depth_history(
    range_hours: int = Query(24, ge=1, le=24 * 7),
    bucket_minutes: int = Query(60, ge=1, le=60 * 24),
    session: AsyncSession = Depends(get_session),
) -> QueueDepthOut:
    """Глубина очереди по bucket'ам — для UI header sparkline.

    Реконструкция: точная snapshot-таблица отсутствует, считаем по
    created_at / processed_at. Подробности — в `queue_repo.depth_history`.
    """
    data = await v2_depth_history(
        session, range_hours=range_hours, bucket_minutes=bucket_minutes,
    )
    return QueueDepthOut.model_validate(data)


class QueueItemLookupOut(BaseModel):
    id: int
    offer_id: int
    store_slug: str
    title_raw: str
    status: str
    priority: int
    attempts: int
    error_detail: str | None = None
    created_at: str
    claimed_at: str | None = None
    processed_at: str | None = None
    next_attempt_at: str | None = None
    result_game_id: int | None = None
    result_score: float | None = None
    result_tier: int | None = None
    # position_in_pending — COUNT записей которые воркер возьмёт раньше этой.
    # None если status != 'pending'.
    position_in_pending: int | None = None


@router.get(
    "/queue/{queue_id}",
    response_model=QueueItemLookupOut,
    dependencies=[Depends(require_scope("read"))],
)
async def lookup_queue_item(
    queue_id: int,
    session: AsyncSession = Depends(get_session),
) -> QueueItemLookupOut:
    """Lookup одной match_queue записи для UI Штучного матчинга.

    Возвращает 404 если записи нет. Если status='pending' — поле
    position_in_pending показывает «номер в очереди» (offset от head по
    порядку claim_batch).
    """
    data = await v2_lookup_queue_item(session, queue_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"queue item {queue_id} not found")
    return QueueItemLookupOut.model_validate(data)


class CancelQueueItemOut(BaseModel):
    """`result`: 'cancelled' | 'not_found' | 'already_processing' |
    'already_done' | 'already_failed' | 'already_skipped'."""
    queue_id: int
    result: str


class ProbeResultOut(BaseModel):
    model: str
    probed: bool
    """`probed=False` если model unknown в OllamaHealth (не bge-m3/qwen2.5)."""
    circuit_state: str
    """closed / open / half_open / unknown — после probe."""
    last_check_at: str | None = None


# ── WT-F11: batch lookup для группировки результатов поиска ──────────────


class LookupBatchItemIn(BaseModel):
    """Один товар во входном батче. Минимум — title; остальные поля
    игнорируются (matcher работает только по title)."""
    title: str = Field(min_length=1)
    store_slug: str | None = None


class LookupBatchRequest(BaseModel):
    items: list[LookupBatchItemIn] = Field(min_length=1, max_length=200)
    # Для каждой найденной игры backend дополнительно возвращает все связанные
    # офферы из catalog.offers — даёт UI «другие магазины этой игры даже если
    # они не в текущем поиске». В первой итерации можно отключить для скорости.
    include_related_offers: bool = True


class LookupMatchOut(BaseModel):
    """Резолв одного input-элемента."""
    idx: int  # позиция в items[]
    game_id: int | None
    game_title: str | None = None
    game_title_ru: str | None = None
    match_score: float | None = None
    match_tier: int | None = None
    match_reason: str | None = None


class RelatedOfferOut(BaseModel):
    """Оффер из catalog.offers — НЕ обязательно совпадает с input items.
    Frontend может dedup'ить по (store_slug, title_raw)."""
    store_slug: str
    title_raw: str
    url: str
    image_url: str | None = None
    last_price: int | None = None  # копейки
    in_stock: bool | None = None
    match_status: str


class LookupGameOut(BaseModel):
    """Сводка по игре (для всех game_id, найденных в matches[])."""
    game_id: int
    title: str
    title_ru: str | None = None
    related_offers: list[RelatedOfferOut] = []


class LookupBatchResponse(BaseModel):
    matches: list[LookupMatchOut]
    games: list[LookupGameOut]


@router.post(
    "/lookup-batch",
    response_model=LookupBatchResponse,
    dependencies=[Depends(require_scope("read"))],
)
async def lookup_batch(
    payload: LookupBatchRequest,
    session: AsyncSession = Depends(get_session),
) -> LookupBatchResponse:
    """Batch-резолв game_id для списка title'ов из SearchPage (WT-F11).

    Прогоняет каждый title через `match_sync` (T0 cache → T1 trgm 0.92).
    Не пишет в БД, не enqueue'ит — read-only вызов. Если `include_related_offers`,
    для каждой найденной игры возвращает все офферы из catalog.offers
    (включая магазины, которых нет в input).

    Frontend в SearchPage использует `matches[i].game_id` для группировки
    своих SSE-результатов; `games[].related_offers` — для «также есть в
    этих магазинах» секции в drawer'е.
    """
    # 1. Резолв game_id для каждого input — последовательный, чтобы не плодить
    # параллельные коннекты к одной session (SQLAlchemy async session не
    # thread-safe для параллельных execute).
    matches: list[LookupMatchOut] = []
    game_ids_seen: set[int] = set()
    for idx, item in enumerate(payload.items):
        result = await match_sync(
            session, item.title, store_slug=item.store_slug,
        )
        gid = result.game_id if result.matched else None
        matches.append(LookupMatchOut(
            idx=idx,
            game_id=gid,
            match_score=result.score,
            match_tier=result.tier,
            match_reason=result.reason,
        ))
        if gid is not None:
            game_ids_seen.add(gid)

    # 2. Хвост по уникальным game_id: одной выборкой подтягиваем title/title_ru
    # и related_offers (если запрошены).
    games: list[LookupGameOut] = []
    if game_ids_seen:
        # Берём денормализованные `title_ru` из games (миграция 0006 cd).
        # Полная иерархия приоритетов алиасов (manual > dicefest > wikidata) —
        # в /games роутере; здесь достаточно денорм-поля для UI-заголовков.
        game_rows = (await session.execute(
            select(Game.id, Game.title, Game.title_ru)
            .where(Game.id.in_(game_ids_seen))
        )).all()
        title_by_gid = {r.id: (r.title, r.title_ru) for r in game_rows}

        # related_offers — отдельная выборка по game_id.
        offers_by_gid: dict[int, list[RelatedOfferOut]] = {gid: [] for gid in game_ids_seen}
        if payload.include_related_offers:
            offer_rows = (await session.execute(
                select(
                    Offer.game_id, Offer.store_slug, Offer.title_raw, Offer.url,
                    Offer.image_url, Offer.last_price, Offer.in_stock,
                    Offer.match_status,
                )
                .where(Offer.game_id.in_(game_ids_seen))
                .where(Offer.match_status.in_(("auto", "manual")))
                .order_by(Offer.game_id, Offer.last_seen_at.desc())
            )).all()
            for r in offer_rows:
                offers_by_gid[r.game_id].append(RelatedOfferOut(
                    store_slug=r.store_slug, title_raw=r.title_raw, url=r.url,
                    image_url=r.image_url, last_price=r.last_price,
                    in_stock=r.in_stock, match_status=r.match_status,
                ))

        for gid in sorted(game_ids_seen):
            title, title_ru = title_by_gid.get(gid, (f"game #{gid}", None))
            games.append(LookupGameOut(
                game_id=gid, title=title, title_ru=title_ru,
                related_offers=offers_by_gid.get(gid, []),
            ))

    # 3. Обогащаем matches title'ами из games (избегаем второго JOIN'а)
    title_idx = {g.game_id: (g.title, g.title_ru) for g in games}
    for m in matches:
        if m.game_id is not None and m.game_id in title_idx:
            m.game_title, m.game_title_ru = title_idx[m.game_id]

    return LookupBatchResponse(matches=matches, games=games)


class InvalidateDecisionOut(BaseModel):
    """Ответ DELETE /matching/decisions/{title_norm}."""
    title_norm: str
    deleted: int


class InvalidateBulkIn(BaseModel):
    """POST /matching/decisions/invalidate — bulk-фильтры."""
    title_contains: str | None = None
    only_negative: bool = False


class InvalidateBulkOut(BaseModel):
    deleted: int
    filters: dict


@router.post(
    "/ml-models/{name}/probe",
    response_model=ProbeResultOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def force_probe(name: str) -> ProbeResultOut:
    """Принудительный health-probe модели Ollama.

    Triggered из UI Контроль → Force probe кнопка на модели с circuit_state
    half_open/open. Дёргает `OllamaHealth.check()` — это GET /api/tags + проверка
    наличия запрошенной модели. При успехе → закроет цепь немедленно (не ждём
    следующий scheduler-job через 30 сек).

    `name` validation — модель должна быть из ml_embed_model / ml_llm_model.
    Иначе probe бесполезен (мы не дёргаем embed/chat принудительно тут — это
    отдельная задача heavy probing).
    """
    settings = get_settings()
    allowed = {settings.ml_embed_model, settings.ml_llm_model}
    if name not in allowed:
        return ProbeResultOut(
            model=name, probed=False, circuit_state="unknown",
            last_check_at=None,
        )

    health = OllamaHealth.get_instance()
    await health.check()
    summary = health.status_summary
    return ProbeResultOut(
        model=name,
        probed=True,
        circuit_state=summary["circuit_state"].get(name, "unknown"),
        last_check_at=summary.get("last_check_at"),
    )


@router.delete(
    "/queue/{queue_id}",
    response_model=CancelQueueItemOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def cancel_queue_item(
    queue_id: int,
    session: AsyncSession = Depends(get_session),
) -> CancelQueueItemOut:
    """Отменить pending-запись в очереди. processing/done/failed/skipped — 409.

    Используется в UI Штучного матчинга — кнопка Cancel перед обработкой
    воркером.
    """
    result = await v2_cancel_pending(session, queue_id)
    await session.commit()
    if result == "not_found":
        raise HTTPException(status_code=404, detail=f"queue item {queue_id} not found")
    if result.startswith("already_"):
        raise HTTPException(
            status_code=409,
            detail=f"queue item {queue_id} {result.replace('_', ' ')} — нельзя отменить",
        )
    return CancelQueueItemOut(queue_id=queue_id, result=result)


@router.delete(
    "/decisions/{title_norm}",
    response_model=InvalidateDecisionOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def invalidate_decision(
    title_norm: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> InvalidateDecisionOut:
    """Точечная инвалидация Tier 0 кэша (CAT-12).

    Когда оператор хочет пересмотреть `reject` или ошибочный auto-match —
    удаляет запись в `match_decisions` для конкретного title_norm.
    Следующий ingest того же title пройдёт T0 miss → T1/T2/T3 заново.

    Audit: пишет в `match_log` запись `action='invalidate'` с
    `reason='manual_invalidate'`. `offer_id` не указан — инвалидация
    относится к title_norm, а не к конкретному оферу.
    """
    # Принимаем title_norm как есть — caller обычно берёт его из
    # MatchLog row, где он уже нормализован. Если пришла raw-форма,
    # пользователю поможет normalize_title до отправки запроса.
    deleted = await invalidate_for_title(session, title_norm)
    if deleted > 0:
        await session.execute(
            text(
                "INSERT INTO match_log (offer_id, action, prev_status, new_status, "
                "reason, performed_by, performed_at) "
                "VALUES (NULL, 'invalidate', NULL, 'invalidated', "
                ":reason, :who, now())"
            ).bindparams(
                reason=f"manual_invalidate: title_norm={title_norm}"[:500],
                who=_performed_by_from_request(request),
            )
        )
    await session.commit()
    return InvalidateDecisionOut(title_norm=title_norm, deleted=deleted)


@router.post(
    "/decisions/invalidate",
    response_model=InvalidateBulkOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def invalidate_decisions_bulk(
    body: InvalidateBulkIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> InvalidateBulkOut:
    """Bulk-инвалидация по фильтрам (CAT-12).

    Поддерживает: `title_contains` (ILIKE %X%), `only_negative` (только
    reject-кэш). Без фильтров — 400 (защита от accidental wipe-all).

    Audit: одна запись `action='invalidate'` с reason'ом из payload.
    """
    if body.title_contains is None and not body.only_negative:
        raise HTTPException(
            status_code=400,
            detail="нужен хотя бы один фильтр (title_contains или only_negative)",
        )
    deleted = await invalidate_bulk(
        session,
        title_contains=body.title_contains,
        only_negative=body.only_negative,
    )
    if deleted > 0:
        filters_desc = ", ".join(
            f"{k}={v!r}" for k, v in body.model_dump(exclude_none=True).items() if v
        )
        await session.execute(
            text(
                "INSERT INTO match_log (offer_id, action, prev_status, new_status, "
                "reason, performed_by, performed_at) "
                "VALUES (NULL, 'invalidate', NULL, 'invalidated', "
                ":reason, :who, now())"
            ).bindparams(
                reason=f"bulk_invalidate ({deleted} rows): {filters_desc}"[:500],
                who=_performed_by_from_request(request),
            )
        )
    await session.commit()
    return InvalidateBulkOut(
        deleted=deleted,
        filters=body.model_dump(exclude_none=True),
    )


def _performed_by_from_request(request: Request) -> str:
    """Берёт identity из X-API-Key или заголовка X-User. Fallback 'operator'."""
    owner = getattr(request.state, "api_key_owner", None)
    if owner:
        return str(owner)[:64]
    user = request.headers.get("x-user")
    if user:
        return user[:64]
    return "operator"


# ─── CAT-17.2: CRUD для match_publisher_prefixes ─────────────────────────────


class PublisherPrefixOut(BaseModel):
    id: int
    prefix: str
    normalized: str | None = None
    source: str
    is_active: bool
    created_at: str


class PublisherPrefixListOut(BaseModel):
    items: list[PublisherPrefixOut]
    total: int


class PublisherPrefixCreateIn(BaseModel):
    prefix: str = Field(min_length=1, max_length=128)
    normalized: str | None = Field(default=None, max_length=128)
    source: str = Field(default="manual", max_length=32)


@router.get(
    "/publisher-prefixes",
    response_model=PublisherPrefixListOut,
    dependencies=[Depends(require_scope("read"))],
)
async def list_publisher_prefixes(
    is_active: bool | None = Query(None, description="фильтр по is_active"),
    session: AsyncSession = Depends(get_session),
) -> PublisherPrefixListOut:
    """Список префиксов издателей для title pipeline.

    UI отображает список с возможностью активации/деактивации (toggle).
    Сортировка по длине DESC — это даёт preview того порядка, в котором
    pipeline проверяет префиксы (greedy match по самому длинному).
    """
    from catalog.models import MatchPublisherPrefix

    stmt = select(MatchPublisherPrefix)
    if is_active is not None:
        stmt = stmt.where(MatchPublisherPrefix.is_active.is_(is_active))
    stmt = stmt.order_by(
        func.length(MatchPublisherPrefix.prefix).desc(),
        MatchPublisherPrefix.id,
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = [
        PublisherPrefixOut(
            id=r.id,
            prefix=r.prefix,
            normalized=r.normalized,
            source=r.source,
            is_active=r.is_active,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
    return PublisherPrefixListOut(items=items, total=len(items))


@router.post(
    "/publisher-prefixes",
    response_model=PublisherPrefixOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def create_publisher_prefix(
    body: PublisherPrefixCreateIn,
    session: AsyncSession = Depends(get_session),
) -> PublisherPrefixOut:
    """Добавить новый префикс. Дубликат (по prefix UNIQUE) → 409.

    После создания pipeline-кеш не перегружается автоматически — оператор
    должен явно дёрнуть `POST /matching/pipeline/reload`. Это сознательное
    решение: при массовом добавлении префиксов несколько запросов подряд
    не должны вызывать N reload'ов кеша.
    """
    from catalog.models import MatchPublisherPrefix

    # Проверка дубликата ДО INSERT — даёт человекочитаемый 409 вместо
    # IntegrityError 500.
    existing = (await session.execute(
        select(MatchPublisherPrefix).where(MatchPublisherPrefix.prefix == body.prefix)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"prefix {body.prefix!r} уже существует (id={existing.id})",
        )

    row = MatchPublisherPrefix(
        prefix=body.prefix,
        normalized=body.normalized,
        source=body.source,
        is_active=True,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return PublisherPrefixOut(
        id=row.id, prefix=row.prefix, normalized=row.normalized,
        source=row.source, is_active=row.is_active,
        created_at=row.created_at.isoformat(),
    )


@router.delete(
    "/publisher-prefixes/{prefix_id}",
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_publisher_prefix(
    prefix_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Удалить префикс (физическое DELETE). 404 если не найден.

    Альтернатива — soft-delete через `is_active=FALSE`; используется когда
    префикс может понадобиться вернуть. Жёсткий DELETE через DELETE-endpoint
    — для seed'ов, оказавшихся false-positive (например, «АСТ» обрезал
    реальные имена игр).
    """
    from catalog.models import MatchPublisherPrefix

    row = await session.get(MatchPublisherPrefix, prefix_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"prefix {prefix_id} not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": True, "id": prefix_id, "prefix": row.prefix}


@router.post(
    "/pipeline/reload",
    dependencies=[Depends(require_scope("admin"))],
)
async def reload_pipeline(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Сбросить module-level кеш TitlePipeline + перечитать prefixes из БД.

    Используется после CRUD-операций с `match_publisher_prefixes` — без
    reload'а изменения войдут в силу через 5 минут (TTL кеша).
    """
    from catalog.matching.title_pipeline import load_pipeline, reset_cache

    reset_cache()
    pipeline = await load_pipeline(session, force_reload=True)
    return {
        "reloaded": True,
        "prefixes_count": len(pipeline.prefixes),
    }
