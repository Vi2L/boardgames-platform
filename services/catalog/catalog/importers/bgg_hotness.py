"""Синхронизация BGG Hotness: fetch /hot, upsert bgg_hotness, auto-import.

Два entry point:
- `run_hotness_sync(settings, session_factory)` — ядро логики, используется
  и scheduler'ом и ручным endpoint'ом. Возвращает dict с итогами прогона.
- `run_hotness_import_job(job_id)` — обёртка под ImportJob-паттерн: ставит
  статусы running/done/failed, пишет прогресс через LogBuffer. Вызывается
  из `asyncio.create_task` в роутере `/import/bgg/hotness`.
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
from catalog.models import BggHotness, Game, ImportJob
from catalog.parsers.bgg.client import BggClient
from catalog.parsers.bgg.parser import parse_hot_xml
from catalog.parsers.bgg.service import enrich_one

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_hotness_sync(
    *,
    auto_import: bool = True,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    client: BggClient | None = None,
    log: logging.Logger | None = None,
) -> dict:
    """Ядро hotness-синхронизации. Идемпотентно: повторный запуск в тот же день
    не создаёт дублей (ON CONFLICT DO NOTHING по uq_bgg_hotness_date_bgg).

    Шаги:
    1. Fetch /hot?type=boardgame → список BggHotnessItem.
    2. Upsert снимка в bgg_hotness (один snapshot_date = один прогон в день).
    3. Resolve game_id для найденных bgg_id → UPDATE bgg_hotness.game_id.
    4. Auto-import: для bgg_id без game_id → enrich_one() с rate-limit 1 рек/сек.

    Возвращает: {fetched, snapshot_date, existing, auto_imported, errors}.
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

        xml_text = await client.fetch_hot()
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    items = parse_hot_xml(xml_text)
    if not items:
        log.warning("hotness: BGG вернул пустой список")
        return {"fetched": 0, "snapshot_date": str(date.today()), "existing": 0, "auto_imported": 0, "errors": 0}

    today = date.today()
    log.info("hotness: получено %d позиций от BGG (snapshot_date=%s)", len(items), today)

    async with session_factory() as session:
        # 2. Upsert снимка — ON CONFLICT DO NOTHING при повторном запуске в тот же день.
        rows = [
            {
                "snapshot_date": today,
                "rank": item.rank,
                "bgg_id": item.bgg_id,
                "name": item.name,
                "year": item.year,
                "thumbnail_url": item.thumbnail_url,
            }
            for item in items
        ]
        await session.execute(
            pg_insert(BggHotness.__table__)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_bgg_hotness_date_bgg")
        )

        # 3. Разрешаем game_id для игр, уже находящихся в каталоге.
        bgg_ids = [item.bgg_id for item in items]
        result = await session.execute(
            select(Game.bgg_id, Game.id).where(Game.bgg_id.in_(bgg_ids))
        )
        bgg_to_game: dict[int, int] = {row[0]: row[1] for row in result.all()}

        for bgg_id, game_id in bgg_to_game.items():
            await session.execute(
                update(BggHotness.__table__)
                .where(BggHotness.__table__.c.snapshot_date == today)
                .where(BggHotness.__table__.c.bgg_id == bgg_id)
                .values(game_id=game_id)
            )

        await session.commit()

    existing = len(bgg_to_game)
    missing_bgg_ids = [item.bgg_id for item in items if item.bgg_id not in bgg_to_game]
    log.info(
        "hotness: %d уже в каталоге, %d новых для авто-импорта",
        existing, len(missing_bgg_ids),
    )

    # 4. Auto-import: enrich_one для каждой новой игры.
    auto_imported = 0
    errors = 0
    if auto_import and missing_bgg_ids:
        # Используем отдельный long-lived BggClient со своим httpx-соединением
        # для всего батча авто-импорта.
        async with BggClient.from_settings() as import_client:
            for bgg_id in missing_bgg_ids:
                try:
                    async with session_factory() as session:
                        bgg = await enrich_one(bgg_id, session, client=import_client)
                        if bgg is not None:
                            await session.commit()
                            auto_imported += 1
                            log.info(
                                "hotness auto-import: bgg_id=%d (%s) добавлен",
                                bgg_id, bgg.title,
                            )
                        else:
                            log.warning("hotness auto-import: bgg_id=%d не найден в BGG", bgg_id)
                            errors += 1
                except Exception:  # noqa: BLE001
                    log.exception("hotness auto-import: bgg_id=%d failed", bgg_id)
                    errors += 1
                # Rate-limit: BGG best practice — не более 1 req/sec.
                await asyncio.sleep(1.0)

    return {
        "fetched": len(items),
        "snapshot_date": str(today),
        "existing": existing,
        "auto_imported": auto_imported,
        "errors": errors,
    }


async def run_hotness_import_job(job_id: int) -> None:
    """ImportJob-обёртка для /import/bgg/hotness через общий skeleton."""
    from catalog.config import get_settings

    SessionFactory = async_sessionmaker(get_engine(), expire_on_commit=False)
    settings = get_settings()

    async def body(buf: LogBuffer, buf_log: BufLogger, sf):
        return await run_hotness_sync(
            auto_import=settings.bgg_hotness_auto_import,
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
        init_log="BGG Hotness sync запущен",
        body=body,
        session_factory=SessionFactory,
        summary_fn=summary,
        logger_inst=logger,
    )
