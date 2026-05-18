"""CAT-8: scheduler-job для еженедельного обновления BGG-семей.

`bgg_family_refresh` обходит N самых старых по fetched_at families в БД,
тянет свежий `/xmlapi2/family/{id}`, diff'ит members, для новых thing-id
вызывает `enrich_one(cascade=False)`. Cascade=False — мы УЖЕ внутри
periodic refresh, рекурсивный cascade избыточен.

Параметры (`scheduler_configs.params`):
- `max_families` (default 100) — сколько family'ов обрабатывать за один прогон.
  Round-robin: следующий прогон возьмёт следующие N по fetched_at.
- `enrich_rate_limit_sec` (default 1.0) — пауза между enrich_one для отсутствующих
  thing-id (BGG XML API best practice).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.db import get_engine
from catalog.importers._log_buffer import (
    BufLogger,
    LogBuffer,
    run_import_job_skeleton,
)
from catalog.models import BggFamily, BggFamilyMember, Game, ImportJob
from catalog.parsers.bgg.client import BggClient
from catalog.parsers.bgg.parser import parse_family_xml
from catalog.parsers.bgg.repository import upsert_family
from catalog.parsers.bgg.service import enrich_one

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_family_refresh_sync(
    *,
    max_families: int = 100,
    enrich_rate_limit_sec: float = 1.0,
    family_rate_limit_sec: float = 1.0,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    client: BggClient | None = None,
    log: logging.Logger | None = None,
) -> dict:
    """Обновляет N самых старых семей: members + description.

    Возвращает: {processed, members_total, new_enriched, errors, oldest_fetched_at,
                 newest_fetched_at}.
    """
    log = log or logger

    if session_factory is None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)

    # Выбираем кандидатов на refresh: самые старые по fetched_at.
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(BggFamily.id, BggFamily.bgg_family_id, BggFamily.fetched_at)
                .order_by(BggFamily.fetched_at.asc())
                .limit(max_families)
            )
        ).all()

    if not rows:
        log.info("family_refresh: в БД ещё нет семей, нечего обновлять")
        return {
            "processed": 0, "members_total": 0, "new_enriched": 0, "errors": 0,
            "oldest_fetched_at": None, "newest_fetched_at": None,
        }

    log.info("family_refresh: обработать %d семей (старейшая %s, свежайшая %s)",
             len(rows), rows[0][2], rows[-1][2])

    own_client = client is None
    if client is None:
        client = BggClient.from_settings()

    processed = 0
    members_total = 0
    new_enriched = 0
    errors = 0

    try:
        if own_client:
            await client.__aenter__()
        for (_, bgg_family_id, _) in rows:
            try:
                xml = await client.fetch_family(bgg_family_id)
            except Exception:  # noqa: BLE001
                log.exception("family_refresh: fetch family_id=%d failed", bgg_family_id)
                errors += 1
                continue
            family = parse_family_xml(xml)
            if family is None:
                log.warning("family_refresh: family_id=%d не распарсилась", bgg_family_id)
                errors += 1
                continue

            async with session_factory() as session:
                await upsert_family(session, family)
                # Уже существующие bgg_id в catalog (нужно знать чтобы НЕ enrich'ать заново).
                existing = (
                    await session.execute(
                        select(Game.bgg_id).where(Game.bgg_id.in_(family.members))
                    )
                ).scalars().all()
                await session.commit()

            missing = [bid for bid in family.members if bid not in set(existing)]
            members_total += len(family.members)
            processed += 1
            log.info("family_refresh: family_id=%d '%s': %d members, %d уже в catalog, %d новых",
                     bgg_family_id, family.name, len(family.members),
                     len(existing), len(missing))

            for bid in missing:
                try:
                    async with session_factory() as session:
                        await enrich_one(bid, session, client=client, cascade=False)
                        await session.commit()
                    new_enriched += 1
                except Exception:  # noqa: BLE001
                    log.exception("family_refresh: enrich bgg_id=%d failed", bid)
                    errors += 1
                await asyncio.sleep(enrich_rate_limit_sec)

            # Между семьями — пауза, чтобы не «жарить» BGG.
            await asyncio.sleep(family_rate_limit_sec)
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    return {
        "processed": processed,
        "members_total": members_total,
        "new_enriched": new_enriched,
        "errors": errors,
        "oldest_fetched_at": str(rows[0][2]),
        "newest_fetched_at": str(rows[-1][2]),
    }


async def run_family_refresh_import_job(import_job_id: int) -> None:
    """ImportJob-обёртка для `bgg_family_refresh` scheduler-job'а."""
    SessionFactory = async_sessionmaker(get_engine(), expire_on_commit=False)

    async with SessionFactory() as session:
        job = (
            await session.execute(select(ImportJob).where(ImportJob.id == import_job_id))
        ).scalar_one()
        payload = job.payload or {}
        max_families = int(payload.get("max_families", 100))

    async def body(buf: LogBuffer, buf_log: BufLogger, sf):
        return await run_family_refresh_sync(
            max_families=max_families,
            session_factory=sf,
            log=buf_log,  # type: ignore[arg-type]
        )

    def summary(r: dict) -> str:
        return (
            f"Done: processed={r['processed']} members={r['members_total']} "
            f"new_enriched={r['new_enriched']} errors={r['errors']}"
        )

    await run_import_job_skeleton(
        import_job_id,
        init_log=f"BGG family refresh запущен: max_families={max_families}",
        body=body,
        session_factory=SessionFactory,
        summary_fn=summary,
        logger_inst=logger,
    )
