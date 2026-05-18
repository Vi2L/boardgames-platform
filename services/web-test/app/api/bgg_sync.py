"""Proxy-роутер для UI BGG Sync.

Под `/api/bgg-sync/*` форвардим вызовы к catalog'у:
- история ImportJob с фильтрами (`/import/jobs`),
- управление scheduler (`/scheduler/jobs/...`),
- read-API снимков Hotness и GeekList (`/bgg/hotness/...`, `/bgg/geeklists/...`),
- запуск ручного импорта GeekList и mini-batch.

Архитектура — тонкий слой: каждый endpoint форвардит в `CatalogClient`,
маппит `CatalogServiceError` → HTTPException. Никакой бизнес-логики.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.catalog_client import CatalogClient, CatalogServiceError
from app.deps import get_catalog_client

router = APIRouter(prefix="/bgg-sync", tags=["bgg-sync"])


def _err(e: CatalogServiceError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.detail)


# ── Scheduler control ─────────────────────────────────────────────────────────


@router.get("/scheduler/jobs")
async def list_scheduler_jobs(
    client: CatalogClient = Depends(get_catalog_client),
) -> list[dict]:
    """Список scheduler-job'ов с runtime info (next_run, last_run)."""
    try:
        return await client.list_scheduler_jobs()
    except CatalogServiceError as e:
        raise _err(e) from e


@router.patch("/scheduler/jobs/{job_id}")
async def reschedule_job(
    job_id: str,
    payload: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Изменить cron/enabled/params + hot-reload в scheduler'е."""
    try:
        return await client.reschedule_job(job_id, payload)
    except CatalogServiceError as e:
        raise _err(e) from e


@router.post("/scheduler/jobs/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Manual trigger scheduled-job'а — создаёт ImportJob с trigger='manual'."""
    try:
        return await client.trigger_scheduler_job(job_id)
    except CatalogServiceError as e:
        raise _err(e) from e


# WT-F7 bulk actions. job_id-сегменты `pause-all`/`resume-all`/`trigger-overdue`
# реально не job_id'ы, а action-имена — они НЕ пересекаются с разрешёнными
# job_id (snake_case в БД) благодаря тире. Если позднее придёт job_id вида
# `pause-all` — это поломает роутинг; пока маловероятно.
_BULK_ACTIONS = {"pause-all", "resume-all", "trigger-overdue"}


@router.post("/scheduler/jobs/{action}")
async def bulk_scheduler_action(
    action: str,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """WT-F7: bulk action над всеми scheduler-job'ами."""
    if action not in _BULK_ACTIONS:
        raise HTTPException(status_code=404, detail=f"unknown bulk action: {action}")
    try:
        return await client.scheduler_bulk_action(action)
    except CatalogServiceError as e:
        raise _err(e) from e


@router.get("/settings/bgg")
async def get_bgg_settings(
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """WT-F7: сводка Global BGG Settings — token flag + cascade-настройки."""
    try:
        return await client.get_bgg_runtime_summary()
    except CatalogServiceError as e:
        raise _err(e) from e


# ── Job history ───────────────────────────────────────────────────────────────


@router.get("/jobs")
async def list_jobs(
    type: str | None = Query(None),
    status: str | None = Query(None),
    trigger: str | None = Query(None, description="manual | scheduled | api"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> list[dict]:
    """История ImportJob'ов с фильтрами для таблицы истории UI."""
    try:
        return await client.list_import_jobs(
            type=type,
            status=status,
            trigger=trigger,
            limit=limit,
            offset=offset,
        )
    except CatalogServiceError as e:
        raise _err(e) from e


# ── Manual imports ────────────────────────────────────────────────────────────


@router.post("/imports/geeklist")
async def import_geeklist(
    payload: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Запуск snapshot'а кураторского BGG GeekList'а.

    payload: {geeklist_id: int, auto_import?: bool}.
    """
    try:
        return await client.import_bgg_geeklist(payload)
    except CatalogServiceError as e:
        raise _err(e) from e


@router.post("/imports/mini-batch")
async def import_mini_batch(
    payload: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Daily catch-up enrichment (500-1000 игр)."""
    try:
        return await client.import_bgg_mini_batch(payload)
    except CatalogServiceError as e:
        raise _err(e) from e


# ── BGG snapshots (Hotness + GeekList) ────────────────────────────────────────


@router.get("/hotness/dates")
async def hotness_dates(
    limit: int = Query(30, ge=1, le=365),
    client: CatalogClient = Depends(get_catalog_client),
) -> list[str]:
    """Список snapshot_date hotness в БД (ISO YYYY-MM-DD), DESC."""
    try:
        return await client.bgg_hotness_dates(limit=limit)
    except CatalogServiceError as e:
        raise _err(e) from e


@router.get("/hotness")
async def hotness_snapshot(
    date: str | None = Query(None, description="YYYY-MM-DD"),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Snapshot hotness на дату (или последний доступный)."""
    try:
        return await client.bgg_hotness_snapshot(date)
    except CatalogServiceError as e:
        raise _err(e) from e


@router.get("/geeklists")
async def list_geeklists(
    client: CatalogClient = Depends(get_catalog_client),
) -> list[dict]:
    """Список импортированных GeekList'ов с последним snapshot_date."""
    try:
        return await client.bgg_geeklists()
    except CatalogServiceError as e:
        raise _err(e) from e


@router.get("/geeklists/{geeklist_id}")
async def get_geeklist(
    geeklist_id: int,
    date: str | None = Query(None),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Snapshot одного GeekList'а на дату."""
    try:
        return await client.bgg_geeklist_snapshot(
            geeklist_id, snapshot_date=date
        )
    except CatalogServiceError as e:
        raise _err(e) from e
