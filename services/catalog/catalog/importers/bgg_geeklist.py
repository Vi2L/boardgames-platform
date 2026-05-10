"""Импортёр кураторских BGG GeekList'ов.

Универсальный механизм для monthly «BGG Top 50 Most Played» (id типа 367126,
обновляется админами BGG ежемесячно) и любых других списков с thing-id.

Два entry point'а (паттерн как в `bgg_hotness.py`):
- `run_geeklist_sync(geeklist_id, ...)` — ядро: fetch XML, upsert snapshot
  в `bgg_geeklists`, auto-import bgg_id отсутствующих в каталоге.
- `run_geeklist_import_job(job_id, geeklist_id)` — ImportJob-обёртка с
  LogBuffer-прогрессом для UI-polling'а.

Идемпотентность: UNIQUE(geeklist_id, snapshot_date) → повторный прогон в тот
же день не создаёт дубль (ON CONFLICT DO UPDATE заменяет items, на случай если
куратор отредактировал список с момента предыдущего прогона).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.db import get_engine
from catalog.importers._log_buffer import (
    BufLogger,
    LogBuffer,
    run_import_job_skeleton,
)
from catalog.models import BggGeeklist, Game, ImportJob
from catalog.parsers.bgg.client import BggClient
from catalog.parsers.bgg.parser import parse_geeklist_xml
from catalog.parsers.bgg.service import enrich_one

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_geeklist_sync(
    *,
    geeklist_id: int,
    auto_import: bool = True,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    client: BggClient | None = None,
    log: logging.Logger | None = None,
    rate_limit_sec: float = 1.0,
) -> dict:
    """Ядро geeklist-синхронизации. Идемпотентно по (geeklist_id, snapshot_date).

    Шаги:
    1. Fetch `/xmlapi2/geeklist/{geeklist_id}` → parse_geeklist_xml.
    2. Resolve game_id для bgg_id, уже находящихся в каталоге (один SELECT IN).
    3. Upsert snapshot в `bgg_geeklists` (items как JSONB-array; resolved game_id
       вшит в каждый item чтобы UI мог показать «есть в каталоге» без JOIN).
    4. Auto-import: для bgg_id без game_id → enrich_one() с rate-limit.

    Возвращает: {fetched, snapshot_date, geeklist_id, title, existing,
                 auto_imported, errors}.
    """
    log = log or logger

    if session_factory is None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)

    own_client = client is None
    if client is None:
        client = BggClient.from_settings()

    try:
        if own_client:
            await client.__aenter__()
        xml_text = await client.fetch_geeklist(geeklist_id)
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    meta, items = parse_geeklist_xml(xml_text)
    today = date.today()

    log.info(
        "geeklist[%d] '%s': получено %d позиций (snapshot_date=%s)",
        geeklist_id, meta.title or "?", len(items), today,
    )

    if not items:
        log.warning("geeklist[%d]: пустой список", geeklist_id)

    async with session_factory() as session:
        # Resolve game_id для bgg_id, уже в каталоге.
        bgg_ids = [it.bgg_id for it in items]
        bgg_to_game: dict[int, int] = {}
        if bgg_ids:
            result = await session.execute(
                select(Game.bgg_id, Game.id).where(Game.bgg_id.in_(bgg_ids))
            )
            bgg_to_game = {row[0]: row[1] for row in result.all()}

        # Сериализуем items в JSONB-friendly формат.
        items_json = [
            {
                "rank": it.rank,
                "bgg_id": it.bgg_id,
                "name": it.name,
                "body": it.body,
                # game_id вшит, чтобы UI рендерил «✓ в каталоге» без JOIN.
                "game_id": bgg_to_game.get(it.bgg_id),
            }
            for it in items
        ]

        # Upsert: ON CONFLICT (geeklist_id, snapshot_date) DO UPDATE — куратор мог
        # изменить список с момента предыдущего прогона в тот же день; перезаписываем.
        stmt = pg_insert(BggGeeklist.__table__).values(
            geeklist_id=geeklist_id,
            snapshot_date=today,
            title=meta.title,
            description=meta.description,
            username=meta.username,
            item_count=len(items),
            items=items_json,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_bgg_geeklist_date",
            set_={
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "username": stmt.excluded.username,
                "item_count": stmt.excluded.item_count,
                "items": stmt.excluded.items,
                "fetched_at": _utcnow(),
            },
        )
        await session.execute(stmt)
        await session.commit()

    existing = len(bgg_to_game)
    missing_bgg_ids = [it.bgg_id for it in items if it.bgg_id not in bgg_to_game]
    log.info(
        "geeklist[%d]: %d уже в каталоге, %d новых для авто-импорта",
        geeklist_id, existing, len(missing_bgg_ids),
    )

    auto_imported = 0
    errors = 0
    if auto_import and missing_bgg_ids:
        async with BggClient.from_settings() as import_client:
            for bgg_id in missing_bgg_ids:
                try:
                    async with session_factory() as session:
                        bgg = await enrich_one(bgg_id, session, client=import_client)
                        if bgg is not None:
                            await session.commit()
                            auto_imported += 1
                            log.info(
                                "geeklist auto-import: bgg_id=%d (%s) добавлен",
                                bgg_id, bgg.title,
                            )
                        else:
                            log.warning(
                                "geeklist auto-import: bgg_id=%d не найден в BGG",
                                bgg_id,
                            )
                            errors += 1
                except Exception:  # noqa: BLE001
                    log.exception("geeklist auto-import: bgg_id=%d failed", bgg_id)
                    errors += 1
                # BGG best practice: ≥1 req/sec.
                await asyncio.sleep(rate_limit_sec)

    return {
        "fetched": len(items),
        "snapshot_date": str(today),
        "geeklist_id": geeklist_id,
        "title": meta.title,
        "existing": existing,
        "auto_imported": auto_imported,
        "errors": errors,
    }


async def run_geeklist_import_job(job_id: int, geeklist_id: int) -> None:
    """ImportJob-обёртка для /import/bgg/geeklist через общий skeleton."""
    SessionFactory = async_sessionmaker(get_engine(), expire_on_commit=False)

    # Читаем payload отдельно (auto_import). Во избежание разрыва lifecycle skeleton'а.
    async with SessionFactory() as session:
        job = (
            await session.execute(select(ImportJob).where(ImportJob.id == job_id))
        ).scalar_one()
        auto_import = (job.payload or {}).get("auto_import", True)

    async def body(buf: LogBuffer, buf_log: BufLogger, sf):
        return await run_geeklist_sync(
            geeklist_id=geeklist_id,
            auto_import=auto_import,
            session_factory=sf,
            log=buf_log,  # type: ignore[arg-type]
        )

    def summary(r: dict) -> str:
        return (
            f"Done: fetched={r['fetched']} existing={r['existing']} "
            f"auto_imported={r['auto_imported']} errors={r['errors']}"
        )

    await run_import_job_skeleton(
        job_id,
        init_log=f"GeekList sync запущен: geeklist_id={geeklist_id}",
        body=body,
        session_factory=SessionFactory,
        summary_fn=summary,
        logger_inst=logger,
    )
