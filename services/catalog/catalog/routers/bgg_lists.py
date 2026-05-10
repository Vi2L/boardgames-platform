"""Read API для BGG-снимков (Hotness + GeekList).

Используется UI BGG Sync для отображения текущих и исторических snapshot'ов:
- `GET /bgg/hotness?date=YYYY-MM-DD` — снимок hotness на дату (default — последний).
- `GET /bgg/hotness/dates` — список доступных snapshot_date (DESC).
- `GET /bgg/geeklists` — список ID GeekList'ов которые мы импортировали.
- `GET /bgg/geeklists/{id}?date=...` — снимок одного GeekList'а на дату.

Diff между снимками вычисляется на client-side из двух запросов (Set difference
по bgg_id) — проще и нативно для React.
"""
from __future__ import annotations

from datetime import date as date_t
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.models import BggGeeklist, BggHotness, Game

router = APIRouter(prefix="/bgg", tags=["bgg-read"])


@router.get(
    "/hotness/dates",
    response_model=list[date_t],
    dependencies=[Depends(require_scope("read"))],
)
async def list_hotness_dates(
    limit: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> list[date_t]:
    """Список доступных snapshot_date в bgg_hotness (DESC). По умолчанию — 30."""
    stmt = (
        select(distinct(BggHotness.snapshot_date))
        .order_by(BggHotness.snapshot_date.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


@router.get(
    "/hotness",
    dependencies=[Depends(require_scope("read"))],
)
async def get_hotness_snapshot(
    snapshot_date: date_t | None = Query(
        default=None,
        alias="date",
        description="дата снимка YYYY-MM-DD; по умолчанию — последний доступный",
    ),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Snapshot hotness на дату с обогащением игрового title из catalog.games.

    Возвращает: {snapshot_date, items: [{rank, bgg_id, name, year, thumbnail_url,
                                         game_id, game_title}]}.

    `game_title` (canonical title из catalog.games) добавляется чтобы UI отрисовал
    «есть в каталоге» с человеческим названием не делая отдельный запрос на каждую
    игру. JOIN — partial по индексу `ix_bgg_hotness_game_id`.
    """
    if snapshot_date is None:
        latest = (
            await session.execute(
                select(func.max(BggHotness.snapshot_date))
            )
        ).scalar_one_or_none()
        if latest is None:
            return {"snapshot_date": None, "items": []}
        snapshot_date = latest

    stmt = (
        select(
            BggHotness.rank,
            BggHotness.bgg_id,
            BggHotness.name,
            BggHotness.year,
            BggHotness.thumbnail_url,
            BggHotness.game_id,
            Game.title.label("game_title"),
        )
        .outerjoin(Game, Game.id == BggHotness.game_id)
        .where(BggHotness.snapshot_date == snapshot_date)
        .order_by(BggHotness.rank.asc())
    )
    rows = (await session.execute(stmt)).all()
    return {
        "snapshot_date": snapshot_date,
        "items": [
            {
                "rank": r.rank,
                "bgg_id": r.bgg_id,
                "name": r.name,
                "year": r.year,
                "thumbnail_url": r.thumbnail_url,
                "game_id": r.game_id,
                "game_title": r.game_title,
            }
            for r in rows
        ],
    }


@router.get(
    "/geeklists",
    dependencies=[Depends(require_scope("read"))],
)
async def list_geeklists(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Список ID импортированных GeekList'ов с последним snapshot_date и title.

    Используется UI для выпадающего списка «выберите GeekList» + дат снимков.
    """
    # Берём последний snapshot per geeklist_id через DISTINCT ON.
    # SQLA не имеет короткого синтаксиса DISTINCT ON для async — используем подзапрос.
    subq = (
        select(
            BggGeeklist.geeklist_id,
            func.max(BggGeeklist.snapshot_date).label("max_date"),
        )
        .group_by(BggGeeklist.geeklist_id)
        .subquery()
    )
    stmt = (
        select(
            BggGeeklist.geeklist_id,
            BggGeeklist.snapshot_date,
            BggGeeklist.title,
            BggGeeklist.username,
            BggGeeklist.item_count,
        )
        .join(
            subq,
            (BggGeeklist.geeklist_id == subq.c.geeklist_id)
            & (BggGeeklist.snapshot_date == subq.c.max_date),
        )
        .order_by(BggGeeklist.snapshot_date.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "geeklist_id": r.geeklist_id,
            "latest_snapshot_date": r.snapshot_date,
            "title": r.title,
            "username": r.username,
            "item_count": r.item_count,
        }
        for r in rows
    ]


@router.get(
    "/geeklists/{geeklist_id}",
    dependencies=[Depends(require_scope("read"))],
)
async def get_geeklist_snapshot(
    geeklist_id: int,
    snapshot_date: date_t | None = Query(
        default=None,
        alias="date",
        description="дата; по умолчанию — последний снимок этого geeklist'а",
    ),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Snapshot одного GeekList'а на дату.

    items уже хранят `game_id` (резолвлен в момент импорта). Для тех, у кого
    game_id задан, делаем bulk SELECT title — UI не должен дёргать /games/{id} N раз.
    """
    stmt = select(BggGeeklist).where(BggGeeklist.geeklist_id == geeklist_id)
    if snapshot_date is not None:
        stmt = stmt.where(BggGeeklist.snapshot_date == snapshot_date)
    stmt = stmt.order_by(BggGeeklist.snapshot_date.desc()).limit(1)

    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="GeekList snapshot not found")

    # Bulk-fetch titles для resolved game_id'ов одним запросом.
    items = list(row.items or [])
    game_ids = [it.get("game_id") for it in items if it.get("game_id") is not None]
    titles: dict[int, str] = {}
    if game_ids:
        title_rows = (
            await session.execute(
                select(Game.id, Game.title).where(Game.id.in_(game_ids))
            )
        ).all()
        titles = {r.id: r.title for r in title_rows}

    enriched_items = []
    for it in items:
        gid = it.get("game_id")
        enriched_items.append({**it, "game_title": titles.get(gid) if gid else None})

    return {
        "geeklist_id": row.geeklist_id,
        "snapshot_date": row.snapshot_date,
        "title": row.title,
        "description": row.description,
        "username": row.username,
        "item_count": row.item_count,
        "items": enriched_items,
        "fetched_at": row.fetched_at,
    }
