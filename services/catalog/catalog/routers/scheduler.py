"""Управление APScheduler-job'ами через REST API.

Что делает:
- `GET  /scheduler/jobs`            — список конфигов + runtime info из APScheduler.
- `PATCH /scheduler/jobs/{job_id}`  — обновить cron/enabled/params + hot-reload.
- `POST /scheduler/jobs/{job_id}/trigger` — manual trigger (создаёт ImportJob).

Зачем: UI BGG Sync должен показывать здоровье периодических задач, позволять
поправить расписание без рестарта сервиса и руками тригерить cron-задачи на
лету (для отладки или catch-up).

Scheduler-инстанс берётся из `request.app.state.scheduler` (хранится в lifespan
`api.py:lifespan`). Без него реальный hot-reload невозможен — PATCH вернёт 503.
"""
from __future__ import annotations

import logging
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.models import SchedulerConfig
from catalog.schemas import (
    ImportJobOut,
    SchedulerJobOut,
    SchedulerRescheduleRequest,
)
from catalog.scheduler import (
    JOB_METADATA,
    JobAlreadyRunning,
    reload_job_from_db,
    trigger_scheduled_job,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scheduler", tags=["scheduler"])


def _enrich_with_runtime(
    cfg: SchedulerConfig,
    scheduler,  # apscheduler.schedulers.asyncio.AsyncIOScheduler | None
) -> SchedulerJobOut:
    """Собирает SchedulerJobOut из БД-конфига + APScheduler runtime + JOB_METADATA."""
    next_run = None
    if scheduler is not None:
        try:
            job = scheduler.get_job(cfg.job_id)
            if job is not None:
                next_run = job.next_run_time
        except Exception:
            logger.exception("scheduler: get_job(%s) failed", cfg.job_id)

    meta = JOB_METADATA.get(cfg.job_id, {})

    return SchedulerJobOut(
        job_id=cfg.job_id,
        cron_expr=cfg.cron_expr,
        enabled=cfg.enabled,
        params=cfg.params or {},
        last_run_job_id=cfg.last_run_job_id,
        last_run_status=cfg.last_run_status,
        last_run_at=cfg.last_run_at,
        next_run_at=next_run,
        display_name=meta.get("display_name"),
        description=meta.get("description"),
    )


@router.get(
    "/jobs",
    response_model=list[SchedulerJobOut],
    dependencies=[Depends(require_scope("read"))],
)
async def list_jobs(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[SchedulerJobOut]:
    """Список всех scheduler-конфигов с next_run_at из APScheduler runtime.

    `next_run_at` доступен только если сервис уже стартовал и `app.state.scheduler`
    инициализирован. В тестах с TestClient lifespan может не подняться — тогда
    next_run_at=None.
    """
    scheduler = getattr(request.app.state, "scheduler", None)
    rows = (
        await session.execute(select(SchedulerConfig).order_by(SchedulerConfig.job_id))
    ).scalars().all()
    return [_enrich_with_runtime(cfg, scheduler) for cfg in rows]


@router.patch(
    "/jobs/{job_id}",
    response_model=SchedulerJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def reschedule_job(
    job_id: str,
    payload: SchedulerRescheduleRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SchedulerJobOut:
    """Обновить cron/enabled/params + hot-reload в APScheduler.

    `params` мерджится с существующими (не replace) — UI редактирует одно поле,
    остальные не трогаются. Если хочешь сбросить — отправь полный объект явно.
    """
    cfg = (
        await session.execute(select(SchedulerConfig).where(SchedulerConfig.job_id == job_id))
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}' not found")

    # Валидация cron перед записью — иначе reload подымет невалидный cron.
    if payload.cron_expr is not None:
        try:
            CronTrigger.from_crontab(payload.cron_expr, timezone="UTC")
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"invalid cron expression: {exc}",
            )
        cfg.cron_expr = payload.cron_expr

    if payload.enabled is not None:
        cfg.enabled = payload.enabled

    if payload.params is not None:
        # Merge: новые ключи добавляются/перезаписывают, старые не удаляются.
        merged: dict[str, Any] = dict(cfg.params or {})
        merged.update(payload.params)
        cfg.params = merged

    await session.commit()
    await session.refresh(cfg)

    # Hot-reload в running APScheduler.
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        try:
            await reload_job_from_db(scheduler, job_id)
        except Exception:
            logger.exception("scheduler: hot-reload %s failed", job_id)
            raise HTTPException(
                status_code=503,
                detail="config обновлён в БД, но hot-reload в scheduler упал — рестартуйте сервис",
            )

    return _enrich_with_runtime(cfg, scheduler)


@router.post(
    "/jobs/{job_id}/trigger",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def trigger_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    """Manual trigger scheduled-job'а: создаёт ImportJob с trigger='manual'.

    Эквивалентно автоматическому срабатыванию по cron, но в `payload.trigger`
    стоит 'manual'. Прогресс — `GET /import/jobs/{id}`.
    """
    cfg = (
        await session.execute(select(SchedulerConfig).where(SchedulerConfig.job_id == job_id))
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}' not found")

    try:
        import_job_id = await trigger_scheduled_job(
            job_id=job_id,
            params=dict(cfg.params or {}),
            trigger="manual",
        )
    except JobAlreadyRunning as exc:
        # 409 Conflict — текущее состояние сервера (running job) не позволяет операцию.
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Ре-fetch ImportJob для response_model.
    from catalog.models import ImportJob

    job = (
        await session.execute(select(ImportJob).where(ImportJob.id == import_job_id))
    ).scalar_one()
    return ImportJobOut.model_validate(job)
