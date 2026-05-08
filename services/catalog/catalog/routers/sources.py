"""Унифицированный API источников: detection runs + match profiles.

Эндпоинты в формате `/sources/{provider}/...` — те же, что в /promotion. Для
detection это новые ручки (запуск сухого прогона, листинг items, apply,
discard). Для match profiles — CRUD конфигов матчинга.

Auth: GET = `read`, POST/DELETE = `admin`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.models import (
    MatchProfile,
    SourceScrapeItem,
    SourceScrapeRun,
)
from catalog.schemas import (
    MatchParams,
    MatchProfileIn,
    MatchProfileOut,
    ScrapeItemListOut,
    ScrapeItemOut,
    ScrapeRunApplyRequest,
    ScrapeRunApplyResult,
    ScrapeRunCreate,
    ScrapeRunDiscardResult,
    ScrapeRunListOut,
    ScrapeRunOut,
)
from catalog.sources import REGISTRY, get_scraper
from catalog.sources.base import ScraperParams
from catalog.sources.runner import (
    RunNotReady,
    apply_run,
    discard_run,
    run_detection,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])


def _check_provider(provider: str) -> None:
    if provider not in REGISTRY:
        raise HTTPException(
            404,
            detail=(
                f"unknown provider: {provider}. "
                f"Known: {', '.join(sorted(REGISTRY)) or '(none)'}"
            ),
        )


# ─── Detection runs ───────────────────────────────────────────────────────────


@router.post(
    "/{provider}/runs",
    response_model=ScrapeRunOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def start_run(
    provider: str,
    payload: ScrapeRunCreate,
    session: AsyncSession = Depends(get_session),
) -> ScrapeRunOut:
    """Запустить сухой прогон скрапа. HTTP-handler возвращается сразу — фоновая
    задача через `asyncio.create_task` обновляет run по мере прогресса.
    """
    _check_provider(provider)
    scraper = get_scraper(provider)

    params = ScraperParams(
        max_items=payload.max_items,
        only_year=payload.only_year,
        extra=payload.extra,
    )

    run = SourceScrapeRun(
        provider=provider,
        status="running",
        params=params.to_dict(),
        totals={},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    # Фоновая задача — своя сессия внутри run_detection.
    asyncio.create_task(run_detection(run.id, scraper, params))

    return ScrapeRunOut.model_validate(run)


@router.get(
    "/{provider}/runs",
    response_model=ScrapeRunListOut,
    dependencies=[Depends(require_scope("read"))],
)
async def list_runs(
    provider: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ScrapeRunListOut:
    _check_provider(provider)
    base = select(SourceScrapeRun).where(SourceScrapeRun.provider == provider)
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    stmt = base.order_by(SourceScrapeRun.id.desc()).limit(limit).offset(offset)
    runs = (await session.execute(stmt)).scalars().all()
    return ScrapeRunListOut(
        runs=[ScrapeRunOut.model_validate(r) for r in runs],
        total=total,
    )


@router.get(
    "/{provider}/runs/{run_id}",
    response_model=ScrapeRunOut,
    dependencies=[Depends(require_scope("read"))],
)
async def get_run(
    provider: str,
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> ScrapeRunOut:
    _check_provider(provider)
    run = await session.get(SourceScrapeRun, run_id)
    if run is None or run.provider != provider:
        raise HTTPException(404, detail=f"run {run_id} not found for {provider}")
    return ScrapeRunOut.model_validate(run)


@router.get(
    "/{provider}/runs/{run_id}/items",
    response_model=ScrapeItemListOut,
    dependencies=[Depends(require_scope("read"))],
)
async def list_run_items(
    provider: str,
    run_id: int,
    change_type: str | None = Query(
        None, description="new | updated | unchanged. Без фильтра — все"),
    search: str | None = Query(None, description="фильтр по slug ILIKE %search%"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ScrapeItemListOut:
    _check_provider(provider)
    run = await session.get(SourceScrapeRun, run_id)
    if run is None or run.provider != provider:
        raise HTTPException(404, detail=f"run {run_id} not found for {provider}")

    base = select(SourceScrapeItem).where(SourceScrapeItem.run_id == run_id)
    if change_type:
        base = base.where(SourceScrapeItem.change_type == change_type)
    if search:
        # Простой ILIKE по slug. На больших run'ах (≥1000 items) сделаем
        # full-text, пока не нужен.
        base = base.where(SourceScrapeItem.slug.ilike(f"%{search}%"))
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    stmt = base.order_by(SourceScrapeItem.id).limit(limit).offset(offset)
    items = (await session.execute(stmt)).scalars().all()
    return ScrapeItemListOut(
        items=[ScrapeItemOut.model_validate(it) for it in items],
        total=total,
    )


@router.post(
    "/{provider}/runs/{run_id}/apply",
    response_model=ScrapeRunApplyResult,
    dependencies=[Depends(require_scope("admin"))],
)
async def apply_run_endpoint(
    provider: str,
    run_id: int,
    payload: ScrapeRunApplyRequest,
    session: AsyncSession = Depends(get_session),
) -> ScrapeRunApplyResult:
    _check_provider(provider)
    if not payload.item_ids and not payload.change_types:
        raise HTTPException(
            400,
            detail="нужен item_ids или change_types — иначе apply ничего не делает",
        )
    try:
        result = await apply_run(
            session,
            run_id,
            item_ids=payload.item_ids,
            change_types=payload.change_types,
            performed_by=payload.performed_by,
        )
    except RunNotReady as e:
        raise HTTPException(409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    return ScrapeRunApplyResult.model_validate(result)


@router.post(
    "/{provider}/runs/{run_id}/discard",
    response_model=ScrapeRunDiscardResult,
    dependencies=[Depends(require_scope("admin"))],
)
async def discard_run_endpoint(
    provider: str,
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> ScrapeRunDiscardResult:
    _check_provider(provider)
    try:
        result = await discard_run(session, run_id)
    except RunNotReady as e:
        raise HTTPException(409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    return ScrapeRunDiscardResult.model_validate(result)


# ─── Match profiles ───────────────────────────────────────────────────────────


@router.get(
    "/{provider}/match-profiles",
    response_model=list[MatchProfileOut],
    dependencies=[Depends(require_scope("read"))],
)
async def list_match_profiles(
    provider: str,
    session: AsyncSession = Depends(get_session),
) -> list[MatchProfileOut]:
    _check_provider(provider)
    stmt = (
        select(MatchProfile)
        .where(MatchProfile.provider == provider)
        .order_by(
            MatchProfile.is_default.desc(),
            MatchProfile.name,
        )
    )
    profiles = (await session.execute(stmt)).scalars().all()
    return [MatchProfileOut.model_validate(p) for p in profiles]


@router.post(
    "/{provider}/match-profiles",
    response_model=MatchProfileOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def upsert_match_profile(
    provider: str,
    payload: MatchProfileIn,
    session: AsyncSession = Depends(get_session),
) -> MatchProfileOut:
    """Создать или обновить профиль с заданным name. Если is_default=True —
    снимаем флаг с текущего дефолта (partial UNIQUE его тогда не пропустит)."""
    _check_provider(provider)
    existing = (
        await session.execute(
            select(MatchProfile).where(
                MatchProfile.provider == provider,
                MatchProfile.name == payload.name,
            ),
        )
    ).scalar_one_or_none()

    if payload.is_default:
        # Снять флаг у текущего дефолта (если он не тот же).
        await session.execute(
            update(MatchProfile)
            .where(
                MatchProfile.provider == provider,
                MatchProfile.is_default.is_(True),
                MatchProfile.name != payload.name,
            )
            .values(is_default=False),
        )

    params_dict = payload.params.model_dump()
    if existing is None:
        profile = MatchProfile(
            provider=provider,
            name=payload.name,
            params=params_dict,
            is_default=payload.is_default,
        )
        session.add(profile)
    else:
        existing.params = params_dict
        existing.is_default = payload.is_default
        profile = existing

    await session.commit()
    await session.refresh(profile)
    return MatchProfileOut.model_validate(profile)


@router.delete(
    "/{provider}/match-profiles/{profile_id}",
    status_code=204,
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_match_profile(
    provider: str,
    profile_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    _check_provider(provider)
    profile = await session.get(MatchProfile, profile_id)
    if profile is None or profile.provider != provider:
        raise HTTPException(404, detail=f"profile {profile_id} not found")
    await session.delete(profile)
    await session.commit()
    # 204 No Content — стандарт REST для удалений
