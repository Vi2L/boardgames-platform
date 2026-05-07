"""API для snapshot-ов прогонов поиска и diff между ними."""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db_local import PortalDB, get_portal_db
from app.deps import get_parsers_client
from app.diff import diff_snapshots
from app.parsers_client import ParsersClient
from app.schemas import SnapshotCreate, SnapshotMeta, SnapshotsPage

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.post("")
async def create_snapshot(
    payload: SnapshotCreate,
    db: Annotated[PortalDB, Depends(get_portal_db)],
    client: Annotated[ParsersClient, Depends(get_parsers_client)],
) -> dict:
    """Выполняет search через parsers и сохраняет snapshot в локальную БД.

    Бенчмарк-метрики (ms_per_product, error_rate) считаются здесь же и
    сохраняются в `summary_json` — для тренда и быстрого просмотра в
    SnapshotsList без декодирования products_json.
    """
    t0 = time.monotonic()
    try:
        result = await client.search(
            payload.query, stores=payload.stores,
            limit=payload.limit, refresh=payload.refresh,
        )
    except Exception as exc:  # noqa: BLE001
        # Сохраняем «провальный» snapshot тоже — для журнала тестов.
        elapsed = int((time.monotonic() - t0) * 1000)
        sid = await db.create_snapshot(
            name=payload.name, query=payload.query, stores=payload.stores,
            limit_n=payload.limit, refresh=payload.refresh,
            source=None, total_ms=elapsed,
            error_count=1, errors={"_": str(exc)},
            products=[],
            summary={"ms_per_product": None, "error_rate": 1.0, "failed": True},
        )
        raise HTTPException(status_code=502, detail={
            "id": sid, "error": str(exc),
        })

    elapsed = int((time.monotonic() - t0) * 1000)
    products_count = len(result.products)
    error_count = len(result.errors)
    active_stores = max(1, len(payload.stores or [s.slug for s in await client.get_stores()]))
    summary = {
        "ms_per_product": round(elapsed / max(1, products_count), 2),
        "error_rate": round(error_count / active_stores, 3),
        "failed": False,
        "products_count": products_count,
    }

    sid = await db.create_snapshot(
        name=payload.name, query=payload.query, stores=payload.stores,
        limit_n=payload.limit, refresh=payload.refresh,
        source=result.source, total_ms=elapsed,
        error_count=error_count, errors=result.errors,
        products=result.products,
        summary=summary,
    )
    return {"id": sid, "summary": summary}


@router.get("", response_model=SnapshotsPage)
async def list_snapshots(
    db: Annotated[PortalDB, Depends(get_portal_db)],
    query: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> SnapshotsPage:
    result = await db.list_snapshots(query=query, page=page, page_size=page_size)
    return SnapshotsPage(
        items=[SnapshotMeta(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/diff")
async def diff_two_snapshots(
    db: Annotated[PortalDB, Depends(get_portal_db)],
    a: int = Query(..., description="ID первого снапшота"),
    b: int = Query(..., description="ID второго снапшота"),
) -> dict:
    snap_a = await db.get_snapshot(a)
    snap_b = await db.get_snapshot(b)
    if snap_a is None or snap_b is None:
        raise HTTPException(status_code=404, detail="Один из snapshot-ов не найден")
    diff = diff_snapshots(snap_a["products"], snap_b["products"])
    diff["summary"]["ms_a"] = snap_a.get("total_ms")
    diff["summary"]["ms_b"] = snap_b.get("total_ms")
    diff["meta"] = {
        "a": {"id": snap_a["id"], "query": snap_a["query"], "created_at": snap_a["created_at"]},
        "b": {"id": snap_b["id"], "query": snap_b["query"], "created_at": snap_b["created_at"]},
    }
    return diff


@router.get("/{snapshot_id}")
async def get_snapshot(
    snapshot_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> dict:
    snap = await db.get_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot не найден")
    return snap


@router.delete("/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> dict:
    deleted = await db.delete_snapshot(snapshot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Snapshot не найден")
    return {"deleted": True, "id": snapshot_id}
