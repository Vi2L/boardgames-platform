"""APScheduler для периодической синхронизации BGG.

Запускается в lifespan catalog/api.py. Использует AsyncIOScheduler — работает
в том же event loop, что и uvicorn, без отдельного потока.

Зарегистрированные job'ы (миграция 0010 сидит дефолты в `scheduler_configs`):
  bgg_top_sync     — enrich_batch(rank_le=N, skip_recent_days=7) еженедельно.
  bgg_hotness_sync — fetch /hot → bgg_hotness + auto-import ежедневно.
  bgg_mini_batch   — daily catch-up enrichment 500-1000 игр (мягкий rate-limit).

Все три:
  - max_instances=1: не запускает параллельную копию если предыдущая ещё идёт.
  - coalesce=True: если сервис был down и пропустил запуск — выполнит один раз
    при старте, а не N раз подряд.
  - Унифицированы через `trigger_scheduled_job(job_id, params, trigger)` —
    создают ImportJob с `payload.trigger='scheduled'` и используют общую
    history через `GET /import/jobs?trigger=scheduled`.

Cron-выражения и `params` хранятся в `scheduler_configs` (миграция 0010), а не
в Settings. UI меняет их через PATCH /scheduler/jobs/{id} с hot-reload через
`scheduler.reschedule_job()` — без рестарта сервиса.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobAlreadyRunning(Exception):
    """trigger_scheduled_job отказался стартовать второй экземпляр того же job-type.

    Используется и для manual-trigger через POST /scheduler/jobs/{id}/trigger
    (роутер мапит в HTTP 409), и для cron-срабатываний (просто логируется).
    """


# ── Реестр job'ов: для UI (display_name, description) и роутера (trigger_handler).
# job_id строго совпадает с PK в `scheduler_configs` и id в APScheduler.
JOB_METADATA: dict[str, dict[str, str]] = {
    "bgg_top_sync": {
        "display_name": "BGG Top Sync (weekly)",
        "description": (
            "Еженедельное полное обогащение топ-N игр (rank ≤ N) через "
            "/thing batch. Параметры: rank_le (default 1000), skip_recent_days "
            "(default 7). Дефолтное расписание: пн 03:00 UTC."
        ),
    },
    "bgg_hotness_sync": {
        "display_name": "BGG Hotness (daily)",
        "description": (
            "Ежедневный snapshot 50 «горячих» игр + auto-import bgg_id'ов "
            "отсутствующих в каталоге. Дефолт: 06:00 UTC."
        ),
    },
    "bgg_mini_batch": {
        "display_name": "BGG Daily Mini-batch",
        "description": (
            "Ежедневный catch-up: 500-1000 игр из хвоста rank-таблицы со "
            "skip_recent_days > 30. Цикл обновления ~60 дней при 30K играх. "
            "Мягкий rate-limit (2с). Дефолт: 04:00 UTC."
        ),
    },
    "ml_health_check": {
        "display_name": "ML Health Check (every 30s)",
        "description": (
            "Polling Ollama /api/tags для проверки доступности bge-m3 и "
            "qwen2.5:7b-instruct. Синглтон OllamaHealth кэширует статус; "
            "tier'ы T2/T3 проверяют его без HTTP. Interval-trigger (не cron)."
        ),
    },
    "match_worker": {
        "display_name": "Match Queue Worker (every 10s)",
        "description": (
            "Обработка match_queue: T2 (bge-m3 cosine) + T3 (qwen LLM-арбитр). "
            "Берёт batch=32 через FOR UPDATE SKIP LOCKED, embed/LLM, "
            "финализирует offer. Interval-trigger (не cron)."
        ),
    },
}

# Interval-jobs (не cron) — не пишутся в scheduler_configs cron_expr,
# а используют specialized resolver. Заводим сюда: ml_health_check, match_worker.
_INTERVAL_JOBS = {"ml_health_check", "match_worker"}


# ── Унифицированный trigger ───────────────────────────────────────────────────


async def trigger_scheduled_job(
    job_id: str,
    params: dict[str, Any],
    trigger: str = "scheduled",
) -> int:
    """Запустить job через ImportJob-паттерн. Возвращает id созданного ImportJob.

    Используется и из APScheduler-cron'а (`trigger='scheduled'`), и из
    `POST /scheduler/jobs/{job_id}/trigger` (`trigger='manual'`). Это даёт
    единую историю в `import_jobs` с фильтром по `payload->>'trigger'`.

    Не блокирует caller'а: job регистрируется, `asyncio.create_task` запускает
    background-runner, возвращаем id. Caller может poll'ить `GET /import/jobs/{id}`.

    Также денормализуем `last_run_*` в `scheduler_configs` для health-блока UI.
    """
    from catalog.db import get_engine
    from catalog.models import ImportJob, SchedulerConfig

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    # Подготавливаем background-функцию по job_id.
    background_fn, import_job_type = _resolve_handler(job_id, params)

    async with SessionFactory() as session:
        # Race-protection: если такой type уже pending/running, не запускаем
        # параллельный. Защита от double-trigger (manual + cron в одну секунду)
        # и от 25-минутного `bgg_top_sync` который может перекрыться следующим
        # cron'ом если зависнет. Не идеально (TOCTOU), но устраняет 99% случаев —
        # для 100% нужен advisory lock или unique partial index по status.
        existing = (
            await session.execute(
                select(ImportJob.id)
                .where(ImportJob.type == import_job_type)
                .where(ImportJob.status.in_(("pending", "running")))
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise JobAlreadyRunning(
                f"job '{job_id}' (type={import_job_type}) уже выполняется "
                f"(import_job_id={existing})"
            )

        job_payload = {**params, "trigger": trigger}
        job = ImportJob(type=import_job_type, payload=job_payload, status="pending")
        session.add(job)
        await session.commit()
        await session.refresh(job)

        # Денормализованные last_run_* в scheduler_configs.
        await session.execute(
            update(SchedulerConfig)
            .where(SchedulerConfig.job_id == job_id)
            .values(
                last_run_job_id=job.id,
                last_run_status="pending",
                last_run_at=_utcnow(),
            )
        )
        await session.commit()

        # Fire-and-forget. background_fn внутри обновит job.status и last_run_status
        # (через тот же scheduler_configs UPDATE на финише).
        asyncio.create_task(
            _run_with_status_update(job_id, job.id, background_fn),
            name=f"sched-{job_id}-{job.id}",
        )

    return job.id


def _resolve_handler(job_id: str, params: dict[str, Any]):
    """Возвращает (background_async_fn, import_job_type) по job_id.

    Обернуто в lazy-import чтобы не тащить routers/importers на module-load.
    """
    if job_id == "bgg_top_sync":
        from catalog.routers.imports import _run_bgg_batch_job
        from catalog.schemas import BggBatchImportRequest

        rank_le = params.get("rank_le", 1000)
        skip = params.get("skip_recent_days", 7)
        req = BggBatchImportRequest(
            rank_le=rank_le,
            batch_size=20,
            skip_recent_days=skip,
            limit=None,
            dry_run=False,
            rate_limit_sec=1.0,
        )
        return (lambda jid: _run_bgg_batch_job(jid, req)), "bgg-batch"

    if job_id == "bgg_hotness_sync":
        from catalog.importers.bgg_hotness import run_hotness_import_job

        return run_hotness_import_job, "bgg-hotness"

    if job_id == "bgg_mini_batch":
        from catalog.routers.imports import _run_bgg_batch_job
        from catalog.schemas import BggBatchImportRequest

        batch_size = params.get("batch_size", 500)
        skip = params.get("skip_recent_days", 30)
        rl = params.get("rate_limit_sec", 2.0)
        req = BggBatchImportRequest(
            all_ranked=True,
            batch_size=20,
            skip_recent_days=skip,
            limit=batch_size,
            dry_run=False,
            rate_limit_sec=rl,
        )
        return (lambda jid: _run_bgg_batch_job(jid, req)), "bgg-mini-batch"

    raise ValueError(f"Unknown scheduler job_id: {job_id}")


# ── Interval-job runners (не используют trigger_scheduled_job + ImportJob) ───
# Эти job'ы — короткие, не нужны polling/log_lines/progress. APScheduler
# вызывает их напрямую без обёртки в _make_cron_job.


async def _ml_health_check_runner() -> None:
    """Periodic poll Ollama health — обновляет OllamaHealth singleton."""
    from catalog.matching.v2.worker import ml_health_check_job

    try:
        await ml_health_check_job()
    except Exception:
        logger.exception("ml_health_check_runner failed")


async def _match_worker_runner() -> None:
    """Один тик match_worker — берёт batch из match_queue, processes T2/T3."""
    from catalog.matching.v2.worker import match_worker_job

    try:
        await match_worker_job()
    except Exception:
        logger.exception("match_worker_runner failed")


def _interval_runner(job_id: str):
    """Возвращает runner для interval-job'а по id."""
    if job_id == "ml_health_check":
        return _ml_health_check_runner
    if job_id == "match_worker":
        return _match_worker_runner
    raise ValueError(f"Unknown interval job_id: {job_id}")


async def _run_with_status_update(job_id: str, import_job_id: int, fn) -> None:
    """Обёртка вокруг background-runner: после завершения денормализует
    last_run_status в scheduler_configs (читает финальный статус ImportJob).
    """
    from catalog.db import get_engine
    from catalog.models import ImportJob, SchedulerConfig

    try:
        await fn(import_job_id)
    except Exception:
        logger.exception("scheduler: %s (job_id=%d) raised", job_id, import_job_id)

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        job = (
            await session.execute(select(ImportJob).where(ImportJob.id == import_job_id))
        ).scalar_one_or_none()
        if job is None:
            return
        await session.execute(
            update(SchedulerConfig)
            .where(SchedulerConfig.job_id == job_id)
            .values(last_run_status=job.status)
        )
        await session.commit()


# ── Создание / hot-reload ─────────────────────────────────────────────────────


def _make_cron_job(job_id: str):
    """Возвращает async-функцию обёртку для APScheduler.add_job.

    APScheduler при срабатывании вызывает этот wrapper; внутри читаем актуальные
    params из scheduler_configs (на случай если их обновили через PATCH без
    рестарта) и зовём `trigger_scheduled_job`.
    """
    async def _runner() -> None:
        from catalog.db import get_engine
        from catalog.models import SchedulerConfig

        try:
            engine = get_engine()
            SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
            async with SessionFactory() as session:
                cfg = (
                    await session.execute(
                        select(SchedulerConfig).where(SchedulerConfig.job_id == job_id)
                    )
                ).scalar_one_or_none()
                if cfg is None or not cfg.enabled:
                    logger.warning(
                        "scheduler: %s — config отсутствует или disabled, пропуск",
                        job_id,
                    )
                    return
                params = dict(cfg.params or {})

            try:
                await trigger_scheduled_job(job_id, params, trigger="scheduled")
            except JobAlreadyRunning as exc:
                # Cron сработал, но предыдущий запуск ещё идёт. Это типично для
                # длинных задач (bgg_top_sync ~25 мин) или для concurrent
                # manual+cron в одну секунду. Не ошибка — просто пропускаем.
                logger.info("scheduler: %s — пропуск (%s)", job_id, exc)
        except Exception:
            logger.exception("scheduler: %s wrapper failed", job_id)

    return _runner


def _register_job(
    scheduler: AsyncIOScheduler,
    job_id: str,
    trigger: CronTrigger,
) -> None:
    """Регистрирует cron-job в scheduler'е с едиными для всего модуля параметрами.

    Унифицирует add_job вызовы из `create_scheduler` и `reload_job_from_db` —
    при добавлении нового параметра (например, `misfire_grace_time`) меняется
    одно место, а не два.
    """
    scheduler.add_job(
        _make_cron_job(job_id),
        trigger,
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


async def create_scheduler() -> AsyncIOScheduler:
    """Создаёт и конфигурирует APScheduler на основе `scheduler_configs` в БД.

    Async — потому что читает БД (миграция 0010 сидит дефолты). Если БД ещё не
    готова или таблицы нет — создаёт пустой scheduler и логирует warning;
    lifespan позднее сделает .start().
    """
    from catalog.db import get_engine
    from catalog.models import SchedulerConfig

    scheduler = AsyncIOScheduler(timezone="UTC")

    try:
        engine = get_engine()
        SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionFactory() as session:
            configs = (
                await session.execute(select(SchedulerConfig))
            ).scalars().all()
    except Exception:
        logger.exception("scheduler: не удалось прочитать scheduler_configs — пустой scheduler")
        return scheduler

    for cfg in configs:
        if not cfg.enabled:
            logger.info("scheduler: %s — disabled, пропускаем регистрацию", cfg.job_id)
            continue

        # Interval-jobs (matching v2): особый путь — не trigger_scheduled_job,
        # а прямой runner с IntervalTrigger. cron_expr игнорируется (но
        # хранится для совместимости PATCH /scheduler/jobs/{id}).
        if cfg.job_id in _INTERVAL_JOBS:
            interval_sec = int(cfg.params.get("interval_sec", 30))
            try:
                runner = _interval_runner(cfg.job_id)
            except ValueError:
                logger.error("scheduler: %s — unknown interval runner", cfg.job_id)
                continue
            scheduler.add_job(
                runner,
                IntervalTrigger(seconds=interval_sec, timezone="UTC"),
                id=cfg.job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "scheduler: %s зарегистрирован (interval=%ds, params=%s)",
                cfg.job_id, interval_sec, cfg.params,
            )
            continue

        try:
            trigger = CronTrigger.from_crontab(cfg.cron_expr, timezone="UTC")
        except Exception:
            logger.error(
                "scheduler: %s — невалидный cron %r, пропускаем",
                cfg.job_id, cfg.cron_expr,
            )
            continue

        _register_job(scheduler, cfg.job_id, trigger)
        logger.info(
            "scheduler: %s зарегистрирован (%s UTC, params=%s)",
            cfg.job_id, cfg.cron_expr, cfg.params,
        )

    return scheduler


async def reload_job_from_db(scheduler: AsyncIOScheduler, job_id: str) -> None:
    """Hot-reload одного job'а после PATCH /scheduler/jobs/{id}.

    Читает актуальный `scheduler_configs` row → reschedule / pause / remove
    в running APScheduler. Безопасно для конкурентных вызовов через одну сессию
    APScheduler (он использует свой собственный SchedulerLock внутри).
    """
    from catalog.db import get_engine
    from catalog.models import SchedulerConfig

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        cfg = (
            await session.execute(
                select(SchedulerConfig).where(SchedulerConfig.job_id == job_id)
            )
        ).scalar_one_or_none()

    if cfg is None:
        # Конфиг удалён → удалить job из scheduler'а если есть.
        try:
            scheduler.remove_job(job_id)
            logger.info("scheduler: %s удалён (конфиг отсутствует)", job_id)
        except Exception:
            pass
        return

    if not cfg.enabled:
        # Disabled → pause или remove существующий.
        try:
            scheduler.remove_job(job_id)
            logger.info("scheduler: %s удалён (enabled=false)", job_id)
        except Exception:
            pass
        return

    try:
        trigger = CronTrigger.from_crontab(cfg.cron_expr, timezone="UTC")
    except Exception:
        logger.error(
            "scheduler: reload %s — невалидный cron %r, оставляем старое расписание",
            job_id, cfg.cron_expr,
        )
        return

    # _register_job делает add_job с replace_existing=True (работает и для update).
    _register_job(scheduler, job_id, trigger)
    logger.info(
        "scheduler: %s reloaded (%s UTC, params=%s)",
        cfg.job_id, cfg.cron_expr, cfg.params,
    )
