"""Импортёры: BGG (Tesera будет на этапе 4).

POST /import/bgg запускает background-task через asyncio.create_task — для одной
игры это занимает 1-3 секунды (BGG XML API + парсинг + upsert), синхронный режим
тоже доступен через ?wait=true для тестов.

GET /import/jobs/{id} — поллинг статуса.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.db import get_engine, get_session
from catalog.importers.bgg import (
    BggGame,
    fetch_bgg_thing,
    parse_bgg_xml,
    slug_from_title,
)
from catalog.models import Game, GameAlias, ImportJob
from catalog.schemas import BggImportRequest, ImportJobOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/import", tags=["import"])


async def _upsert_game_from_bgg(
    session: AsyncSession, bgg: BggGame
) -> int:
    """Идемпотентный upsert по bgg_id.

    Возвращает game_id. Алиасы апсертятся отдельно (по uq_alias_per_game).
    """
    slug = slug_from_title(bgg.title, bgg.bgg_id)

    # ON CONFLICT (bgg_id) DO UPDATE — обновляем основные поля, сохраняем
    # ручные правки в meta через jsonb merge нельзя без сложных выражений,
    # так что meta перезаписываем. Этап 7+ может усложнить.
    stmt = pg_insert(Game.__table__).values(
        slug=slug,
        title=bgg.title,
        year=bgg.year,
        designers=bgg.designers or None,
        publishers=bgg.publishers or None,
        players_min=bgg.players_min,
        players_max=bgg.players_max,
        age_min=bgg.age_min,
        playtime_min=bgg.playtime_min,
        playtime_max=bgg.playtime_max,
        bgg_id=bgg.bgg_id,
        cover_url=bgg.cover_url,
        description=bgg.description,
        meta=bgg.to_meta(),
        source="bgg",
        status="published",
    ).on_conflict_do_update(
        index_elements=["bgg_id"],
        set_={
            "title": bgg.title,
            "year": bgg.year,
            "designers": bgg.designers or None,
            "publishers": bgg.publishers or None,
            "players_min": bgg.players_min,
            "players_max": bgg.players_max,
            "age_min": bgg.age_min,
            "playtime_min": bgg.playtime_min,
            "playtime_max": bgg.playtime_max,
            "cover_url": bgg.cover_url,
            "description": bgg.description,
            "meta": bgg.to_meta(),
            "updated_at": _utcnow(),
        },
    ).returning(Game.id)
    game_id = (await session.execute(stmt)).scalar_one()

    # Альтернативные имена → game_aliases. ON CONFLICT DO NOTHING на uq_alias_per_game.
    for alias in bgg.aliases:
        await session.execute(
            pg_insert(GameAlias.__table__)
            .values(game_id=game_id, alias=alias, source="bgg")
            .on_conflict_do_nothing(constraint="uq_alias_per_game")
        )
    return game_id


async def _run_bgg_import_job(
    job_id: int, bgg_ids: list[int]
) -> None:
    """Background-таск: для каждого id — fetch BGG → parse → upsert.

    Ошибка по одному id не валит всю задачу — пишется в result.errors.
    Использует свой session_factory (не FastAPI dep), потому что вне HTTP-контекста.
    """
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as session:
        job = (await session.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
        job.status = "running"
        job.started_at = _utcnow()
        await session.commit()

    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for bgg_id in bgg_ids:
            try:
                xml = await fetch_bgg_thing(bgg_id, client=client)
                bgg = parse_bgg_xml(xml)
                if bgg is None:
                    errors.append({"bgg_id": bgg_id, "error": "not found"})
                    continue
                async with SessionFactory() as session:
                    gid = await _upsert_game_from_bgg(session, bgg)
                    await session.commit()
                imported.append({"bgg_id": bgg_id, "game_id": gid, "title": bgg.title})
            except Exception as exc:  # noqa: BLE001
                logger.exception("BGG import failed for %s", bgg_id)
                errors.append({"bgg_id": bgg_id, "error": str(exc)})

    async with SessionFactory() as session:
        job = (await session.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
        job.status = "failed" if errors and not imported else "done"
        job.finished_at = _utcnow()
        job.result = {"imported": imported, "errors": errors}
        if errors and not imported:
            job.error = errors[0]["error"]
        await session.commit()


@router.post("/bgg", response_model=ImportJobOut)
async def import_bgg(
    payload: BggImportRequest,
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    ids = payload.ids or ([payload.bgg_id] if payload.bgg_id else [])
    if not ids:
        raise HTTPException(status_code=400, detail="bgg_id или ids обязателен")

    job = ImportJob(type="bgg", payload={"ids": ids}, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await _run_bgg_import_job(job.id, ids)
        await session.refresh(job)
    else:
        # Fire-and-forget. Сама задача создаёт свою сессию — текущая dep-сессия
        # будет закрыта по завершении HTTP-запроса.
        asyncio.create_task(_run_bgg_import_job(job.id, ids))

    return ImportJobOut.model_validate(job)


@router.get("/jobs/{job_id}", response_model=ImportJobOut)
async def get_job(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> ImportJobOut:
    job = (await session.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return ImportJobOut.model_validate(job)
