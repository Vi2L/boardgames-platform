"""Promotion API — перенос staging-данных в canonical БД с матчингом и откатом.

Generic-эндпоинты с `{provider}` в path, чтобы будущие источники (BGA,
dicebreaker) добавлялись без ломки контракта. Сейчас поддерживается
provider='dicefest'.

Auth: GET = `read`, POST = `admin`.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.models import DicefestRawGame, Game, GameAlias, ImportPromotionLog
from catalog.promotion import dicefest as dicefest_promo
from catalog.schemas import (
    BatchLinkRequest,
    BatchLinkResult,
    DicefestRawGameOut,
    DicefestRawListOut,
    MatchParams,
    PromotionApplyRequest,
    PromotionApplyResult,
    PromotionCandidate,
    PromotionCandidatesOut,
    PromotionLogAliasSummary,
    PromotionLogDetails,
    PromotionLogGameSummary,
    PromotionLogList,
    PromotionLogOut,
    PromotionLogRawGameSummary,
    PromotionRevertResult,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/promotion", tags=["promotion"])

SUPPORTED_PROVIDERS = {"dicefest"}


def _check_provider(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(404, detail=f"unknown provider: {provider}")


# ─── Queue (raw rows для промоушена) ─────────────────────────────────────────


@router.get(
    "/{provider}/queue",
    response_model=DicefestRawListOut,
    dependencies=[Depends(require_scope("read"))],
)
async def queue(
    provider: str,
    status: str = Query("new", description="new | promoted | skipped | rejected"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> DicefestRawListOut:
    _check_provider(provider)
    # Сейчас только dicefest; когда появятся ещё — diss patch по provider.
    stmt = select(DicefestRawGame).where(DicefestRawGame.status == status)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(DicefestRawGame.id.desc()).limit(limit).offset(offset)
    items = (await session.execute(stmt)).scalars().all()
    return DicefestRawListOut(
        items=[DicefestRawGameOut.model_validate(it) for it in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{provider}/{raw_id}",
    response_model=DicefestRawGameOut,
    dependencies=[Depends(require_scope("read"))],
)
async def get_raw(
    provider: str,
    raw_id: int,
    session: AsyncSession = Depends(get_session),
) -> DicefestRawGameOut:
    _check_provider(provider)
    raw = await session.get(DicefestRawGame, raw_id)
    if raw is None:
        raise HTTPException(404, detail=f"raw_id={raw_id} not found")
    return DicefestRawGameOut.model_validate(raw)


# ─── Candidates ──────────────────────────────────────────────────────────────


@router.get(
    "/{provider}/{raw_id}/candidates",
    response_model=PromotionCandidatesOut,
    dependencies=[Depends(require_scope("read"))],
)
async def candidates(
    provider: str,
    raw_id: int,
    threshold: float = Query(0.5, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=20),
    prefer_external_id: bool = Query(
        False, description="Поднять deterministic-кандидата по BGG/Tesera ID",
    ),
    weight_ru: float = Query(1.0, ge=0.0, le=2.0),
    weight_en: float = Query(1.0, ge=0.0, le=2.0),
    weight_alias: float = Query(1.0, ge=0.0, le=2.0),
    session: AsyncSession = Depends(get_session),
) -> PromotionCandidatesOut:
    """Список кандидатов для raw-записи.

    Параметры матчинга передаются через query (плоско, чтобы был кешируемый
    GET): threshold, prefer_external_id, weight_*. Если ни один не задан —
    поведение совпадает со старым контрактом (1.0/1.0/1.0, без external_id).
    """
    _check_provider(provider)
    params = MatchParams(
        threshold=threshold,
        prefer_external_id=prefer_external_id,
        weights={"ru": weight_ru, "en": weight_en, "alias": weight_alias},
    )
    raw, cand_dicts = await dicefest_promo.match_candidates(
        session, raw_id, threshold=threshold, limit=limit, params=params,
    )
    return PromotionCandidatesOut(
        raw=DicefestRawGameOut.model_validate(raw),
        candidates=[PromotionCandidate.model_validate(c) for c in cand_dicts],
        threshold=threshold,
    )


# ─── Apply / Revert ──────────────────────────────────────────────────────────


@router.post(
    "/{provider}/{raw_id}/apply",
    response_model=PromotionApplyResult,
    dependencies=[Depends(require_scope("admin"))],
)
async def apply(
    provider: str,
    raw_id: int,
    payload: PromotionApplyRequest,
    session: AsyncSession = Depends(get_session),
) -> PromotionApplyResult:
    _check_provider(provider)
    result = await dicefest_promo.promote(
        session,
        raw_id,
        action=payload.action,  # type: ignore[arg-type]
        target_game_id=payload.target_game_id,
        notes=payload.notes,
        performed_by=payload.performed_by or "operator",
    )
    return PromotionApplyResult.model_validate(result)


@router.post(
    "/{provider}/batch-link",
    response_model=BatchLinkResult,
    dependencies=[Depends(require_scope("admin"))],
)
async def batch_link(
    provider: str,
    payload: BatchLinkRequest,
    session: AsyncSession = Depends(get_session),
) -> BatchLinkResult:
    """Batch auto-link уверенных совпадений (PR-5).

    Идёт по raw status='new', находит топ-1 кандидата через pg_trgm и линкует
    тех, у кого score ≥ threshold. По умолчанию dry_run=True — UX «preview
    сначала», оператор подтверждает перед реальным запуском.
    """
    _check_provider(provider)
    result = await dicefest_promo.batch_auto_link(
        session,
        threshold=payload.threshold,
        max_items=payload.max_items,
        dry_run=payload.dry_run,
        skip_with_satellite=payload.skip_with_satellite,
        params=payload.match_params,
    )
    return BatchLinkResult.model_validate(result)


@router.post(
    "/log/{log_id}/revert",
    response_model=PromotionRevertResult,
    dependencies=[Depends(require_scope("admin"))],
)
async def revert_log(
    log_id: int,
    payload: dict[str, Any] | None = None,
    session: AsyncSession = Depends(get_session),
) -> PromotionRevertResult:
    body = payload or {}
    log = await session.get(ImportPromotionLog, log_id)
    if log is None:
        raise HTTPException(404, detail=f"log_id={log_id} not found")
    # Сейчас один провайдер; когда появятся ещё — диспатч по log.provider.
    if log.provider != "dicefest":
        raise HTTPException(501, detail=f"revert не реализован для {log.provider}")
    result = await dicefest_promo.revert(
        session, log_id,
        performed_by=body.get("performed_by") or "operator",
        notes=body.get("notes"),
    )
    return PromotionRevertResult.model_validate(result)


@router.get(
    "/log/{log_id}/details",
    response_model=PromotionLogDetails,
    dependencies=[Depends(require_scope("read"))],
)
async def get_log_details(
    log_id: int,
    session: AsyncSession = Depends(get_session),
) -> PromotionLogDetails:
    """Развёрнутые детали одной записи журнала.

    UI показывает в модалке: сама запись + связанные raw-staging /
    canonical Game / алиас. Если запись reverted — отдаёт id revert-записи,
    чтобы клиент мог сделать deep-link.

    Объекты, на которые ссылается log, подгружаются раздельными session.get,
    а не одним JOIN — N+1 здесь несущественен (модалка открывается на одну
    запись), а код проще читать.
    """
    log = await session.get(ImportPromotionLog, log_id)
    if log is None:
        raise HTTPException(404, detail=f"log_id={log_id} not found")

    raw_summary: PromotionLogRawGameSummary | None = None
    # raw_id указывает на provider-specific staging; пока поддерживаем только
    # dicefest. Когда добавим bga/dicebreaker — расширим switch по log.provider.
    if log.provider == "dicefest":
        raw = await session.get(DicefestRawGame, log.raw_id)
        if raw is not None:
            raw_summary = PromotionLogRawGameSummary.model_validate(raw)

    game_summary: PromotionLogGameSummary | None = None
    if log.game_id is not None:
        game = await session.get(Game, log.game_id)
        if game is not None:
            game_summary = PromotionLogGameSummary.model_validate(game)

    alias_summary: PromotionLogAliasSummary | None = None
    if log.alias_id is not None:
        alias = await session.get(GameAlias, log.alias_id)
        if alias is not None:
            alias_summary = PromotionLogAliasSummary.model_validate(alias)

    # Если эту запись отменили — найти соответствующую revert-запись.
    # revert() пишет отдельную строку с action='revert', тем же raw_id,
    # performed_at >= log.reverted_at (см. promotion/dicefest.py:revert).
    reverted_by_entry_id: int | None = None
    if log.reverted_at is not None:
        revert_stmt = (
            select(ImportPromotionLog.id)
            .where(
                ImportPromotionLog.action == "revert",
                ImportPromotionLog.raw_id == log.raw_id,
                ImportPromotionLog.provider == log.provider,
                ImportPromotionLog.performed_at >= log.reverted_at,
            )
            .order_by(ImportPromotionLog.performed_at.asc())
            .limit(1)
        )
        reverted_by_entry_id = (await session.execute(revert_stmt)).scalar_one_or_none()

    return PromotionLogDetails(
        entry=PromotionLogOut.model_validate(log),
        raw_game=raw_summary,
        game=game_summary,
        alias=alias_summary,
        reverted_by_entry_id=reverted_by_entry_id,
    )


@router.get(
    "/log",
    response_model=PromotionLogList,
    dependencies=[Depends(require_scope("read"))],
)
async def list_log(
    provider: str | None = Query(None),
    game_id: int | None = Query(
        None, description="фильтр по game_id (для audit-таба drawer)",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> PromotionLogList:
    stmt = select(ImportPromotionLog)
    if provider:
        stmt = stmt.where(ImportPromotionLog.provider == provider)
    if game_id is not None:
        stmt = stmt.where(ImportPromotionLog.game_id == game_id)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(ImportPromotionLog.performed_at.desc()).limit(limit).offset(offset)
    items = (await session.execute(stmt)).scalars().all()
    return PromotionLogList(
        items=[PromotionLogOut.model_validate(it) for it in items],
        total=total,
        limit=limit,
        offset=offset,
    )
