"""APScheduler для периодической синхронизации BGG.

Запускается в lifespan catalog/api.py. Использует AsyncIOScheduler — работает
в том же event loop, что и uvicorn, без отдельного потока.

Зарегистрированные job'ы:
  bgg_top_sync     — enrich_batch(rank_le=N, skip_recent_days=M) раз в неделю.
  bgg_hotness_sync — fetch /hot → upsert bgg_hotness + auto-import раз в день.

Обе задачи:
  - max_instances=1: не запускает параллельную копию если предыдущая ещё идёт.
  - coalesce=True: если сервис был down и пропустил запуск — выполнит один раз
    при старте, а не N раз подряд.
  - Wrapped в try/except: ошибка задачи попадает в лог, не убивает scheduler.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


async def _bgg_top_sync_job() -> None:
    """Еженедельное полное обогащение TOP-N игр через enrich_batch."""
    from catalog.config import get_settings
    from catalog.parsers.bgg.client import BggClient
    from catalog.parsers.bgg.service import enrich_batch

    settings = get_settings()
    logger.info(
        "scheduler: bgg_top_sync started (rank_le=%s, skip_recent_days=%s)",
        settings.bgg_top_sync_rank_le,
        settings.bgg_top_sync_skip_recent_days,
    )
    try:
        async with BggClient.from_settings() as client:
            stats = await enrich_batch(
                rank_le=settings.bgg_top_sync_rank_le,
                skip_recent_days=settings.bgg_top_sync_skip_recent_days,
                rate_limit_sec=1.0,
                client=client,
            )
        logger.info("scheduler: bgg_top_sync done: %s", stats.to_dict())
    except Exception:
        logger.exception("scheduler: bgg_top_sync failed")


async def _bgg_hotness_sync_job() -> None:
    """Ежедневный snapshot BGG Hotness + auto-import новых игр."""
    from catalog.config import get_settings
    from catalog.importers.bgg_hotness import run_hotness_sync

    settings = get_settings()
    logger.info("scheduler: bgg_hotness_sync started")
    try:
        result = await run_hotness_sync(
            auto_import=settings.bgg_hotness_auto_import,
        )
        logger.info("scheduler: bgg_hotness_sync done: %s", result)
    except Exception:
        logger.exception("scheduler: bgg_hotness_sync failed")


def create_scheduler() -> AsyncIOScheduler:
    """Создаёт и конфигурирует APScheduler на основе текущих Settings.

    Вызывается из lifespan — scheduler.start() / scheduler.shutdown(wait=False)
    делает lifespan самостоятельно.
    """
    from catalog.config import get_settings

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")

    if settings.bgg_top_sync_enabled:
        try:
            trigger = CronTrigger.from_crontab(settings.bgg_top_sync_cron, timezone="UTC")
        except Exception:
            logger.error(
                "bgg_top_sync_cron невалиден: %r — используется дефолт '0 3 * * 1'",
                settings.bgg_top_sync_cron,
            )
            trigger = CronTrigger.from_crontab("0 3 * * 1", timezone="UTC")

        scheduler.add_job(
            _bgg_top_sync_job,
            trigger,
            id="bgg_top_sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("scheduler: bgg_top_sync зарегистрирован (%s UTC)", settings.bgg_top_sync_cron)

    if settings.bgg_hotness_sync_enabled:
        try:
            trigger = CronTrigger.from_crontab(settings.bgg_hotness_sync_cron, timezone="UTC")
        except Exception:
            logger.error(
                "bgg_hotness_sync_cron невалиден: %r — используется дефолт '0 6 * * *'",
                settings.bgg_hotness_sync_cron,
            )
            trigger = CronTrigger.from_crontab("0 6 * * *", timezone="UTC")

        scheduler.add_job(
            _bgg_hotness_sync_job,
            trigger,
            id="bgg_hotness_sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "scheduler: bgg_hotness_sync зарегистрирован (%s UTC)",
            settings.bgg_hotness_sync_cron,
        )

    return scheduler
