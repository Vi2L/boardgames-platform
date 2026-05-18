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
from datetime import datetime, timezone
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
    SchedulerBulkActionOut,
    SchedulerJobOut,
    SchedulerRescheduleRequest,
)
from catalog.scheduler import (
    JOB_METADATA,
    JobAlreadyRunning,
    get_tick_history,
    reload_job_from_db,
    trigger_scheduled_job,
    validate_params_against_schema,
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
        tick_history=get_tick_history(cfg.job_id),
        # WT-F7: schema-driven редактирование params. None для legacy job'ов
        # без зарегистрированной схемы — UI отрисует JSON-textarea.
        params_schema=meta.get("params_schema"),
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
        # WT-F7: server-side валидация против `params_schema` зарегистрированного
        # job'а — UI присылает строки из текстовых input'ов, тут мы их коэрсим к
        # правильным типам и ловим out-of-range. Для job'ов без схемы — no-op.
        try:
            merged = validate_params_against_schema(job_id, merged)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid params: {exc}")
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


# ── Bulk actions (WT-F7) ──────────────────────────────────────────────────────
# UI «панические кнопки» при инциденте: остановить всё / включить всё / пнуть
# просроченные. Каждая — атомарная транзакция в БД, hot-reload по каждому job'у
# делается best-effort (если что-то упало — записываем в errors, не откатываем
# остальные).


async def _bulk_apply(
    session: AsyncSession,
    request: Request,
    *,
    target_enabled: bool,
) -> SchedulerBulkActionOut:
    """Общая логика для pause-all / resume-all — обновить enabled у всех конфигов
    и hot-reload в APScheduler."""
    rows = (await session.execute(select(SchedulerConfig))).scalars().all()
    affected: list[str] = []
    errors: list[dict[str, str]] = []
    for cfg in rows:
        if cfg.enabled == target_enabled:
            continue  # nothing to do — не считаем affected
        cfg.enabled = target_enabled
        affected.append(cfg.job_id)
    await session.commit()

    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        for job_id in affected:
            try:
                await reload_job_from_db(scheduler, job_id)
            except Exception as exc:
                logger.exception("scheduler bulk: reload %s failed", job_id)
                errors.append({"job_id": job_id, "error": str(exc)})

    return SchedulerBulkActionOut(
        action="resume-all" if target_enabled else "pause-all",
        affected=affected,
        errors=errors,
    )


@router.post(
    "/jobs/pause-all",
    response_model=SchedulerBulkActionOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def pause_all_jobs(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SchedulerBulkActionOut:
    """Disable все scheduler-job'ы. Применять при инциденте — потом resume-all."""
    return await _bulk_apply(session, request, target_enabled=False)


@router.post(
    "/jobs/resume-all",
    response_model=SchedulerBulkActionOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def resume_all_jobs(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SchedulerBulkActionOut:
    """Enable все scheduler-job'ы — обратное к pause-all."""
    return await _bulk_apply(session, request, target_enabled=True)


@router.post(
    "/jobs/trigger-overdue",
    response_model=SchedulerBulkActionOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def trigger_overdue_jobs(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SchedulerBulkActionOut:
    """Найти enabled cron-job'ы, у которых next_run_at в прошлом, и запустить.

    Используется когда сервис был долго down: APScheduler.coalesce=True уже
    схлопывает пропуски, но кнопка нужна чтобы оператор вручную добил пропущенные
    запуски прямо сейчас, не дожидаясь следующего cron'а.
    """
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler not initialized")

    rows = (
        await session.execute(
            select(SchedulerConfig).where(SchedulerConfig.enabled == True)  # noqa: E712
        )
    ).scalars().all()

    now_utc = datetime.now(timezone.utc)
    affected: list[str] = []
    triggered: list[int] = []
    errors: list[dict[str, str]] = []
    for cfg in rows:
        ap_job = scheduler.get_job(cfg.job_id)
        if ap_job is None or ap_job.next_run_time is None:
            continue
        if ap_job.next_run_time > now_utc:
            continue  # ещё не пора
        affected.append(cfg.job_id)
        try:
            import_job_id = await trigger_scheduled_job(
                cfg.job_id, dict(cfg.params or {}), trigger="manual"
            )
            triggered.append(import_job_id)
        except JobAlreadyRunning as exc:
            errors.append({"job_id": cfg.job_id, "error": f"already running: {exc}"})
        except Exception as exc:
            logger.exception("trigger-overdue: %s failed", cfg.job_id)
            errors.append({"job_id": cfg.job_id, "error": str(exc)})

    return SchedulerBulkActionOut(
        action="trigger-overdue",
        affected=affected,
        triggered_import_job_ids=triggered,
        errors=errors,
    )
