"""Test-сьюты: CRUD + SSE-прогон.

Сьют — список запросов (`SuiteQuery`), которые порталу нужно прогонять
последовательно через parsers и сохранять результат как snapshot. Это
QA-инструмент: один сьют = регрессионный набор запросов.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.db_local import PortalDB, get_portal_db
from app.deps import get_parsers_client
from app.parsers_client import ParsersClient
from app.schemas import SuiteIn, SuiteOut, SuiteQuery, SuiteRunDetail, SuiteRunMeta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/suites", tags=["suites"])


# ── CRUD ──────────────────────────────────────────────────────────────────

@router.post("", response_model=SuiteOut)
async def create_suite(
    payload: SuiteIn,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> SuiteOut:
    sid = await db.create_suite(
        name=payload.name, description=payload.description,
        queries=[q.model_dump() for q in payload.queries],
    )
    suite = await db.get_suite(sid)
    assert suite is not None
    return _suite_to_schema(suite)


@router.get("", response_model=list[SuiteOut])
async def list_suites(
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> list[SuiteOut]:
    return [_suite_to_schema(s) for s in await db.list_suites()]


@router.get("/{suite_id}", response_model=SuiteOut)
async def get_suite(
    suite_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> SuiteOut:
    suite = await db.get_suite(suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite не найден")
    return _suite_to_schema(suite)


@router.put("/{suite_id}", response_model=SuiteOut)
async def update_suite(
    suite_id: int,
    payload: SuiteIn,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> SuiteOut:
    updated = await db.update_suite(
        suite_id, name=payload.name, description=payload.description,
        queries=[q.model_dump() for q in payload.queries],
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Suite не найден")
    suite = await db.get_suite(suite_id)
    assert suite is not None
    return _suite_to_schema(suite)


@router.get("/{suite_id}/baselines")
async def list_baselines(
    suite_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> list[dict]:
    """Все baseline'ы сьюта. UI помечает запросы, для которых baseline есть."""
    suite = await db.get_suite(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="suite not found")
    return await db.list_baselines(suite_id)


@router.put("/{suite_id}/baselines")
async def upsert_baseline(
    suite_id: int,
    body: dict,  # {query, baseline: {min_count?, expected_stores?, min_field_coverage?, notes?}}
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> dict:
    """Сохранить/обновить baseline для (suite, query).

    UNIQUE по (suite_id, query) — повторный вызов перезаписывает baseline.
    """
    suite = await db.get_suite(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="suite not found")
    query = body.get("query")
    baseline = body.get("baseline")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(status_code=400, detail="query (str) required")
    if not isinstance(baseline, dict):
        raise HTTPException(status_code=400, detail="baseline (dict) required")
    return await db.upsert_baseline(suite_id, query, baseline)


@router.delete("/{suite_id}/baselines/{baseline_id}", status_code=204)
async def delete_baseline(
    suite_id: int,
    baseline_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> None:
    ok = await db.delete_baseline(baseline_id)
    if not ok:
        raise HTTPException(status_code=404, detail="baseline not found")


@router.delete("/{suite_id}")
async def delete_suite(
    suite_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> dict:
    deleted = await db.delete_suite(suite_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Suite не найден")
    return {"deleted": True, "id": suite_id}


# ── SSE прогон ────────────────────────────────────────────────────────────

@router.get("/{suite_id}/run")
async def run_suite(
    suite_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
    client: Annotated[ParsersClient, Depends(get_parsers_client)],
) -> StreamingResponse:
    """Последовательно прогоняет каждый item, эмитит SSE.

    События:
      suite-item-start  {idx, total, query}
      suite-item-done   {idx, total, query, status, ms, snapshot_id, error?}
      suite-summary     {total, passed, failed, errors_count, ms_total,
                         ms_per_query, source_breakdown}
    """
    suite = await db.get_suite(suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite не найден")

    queue: asyncio.Queue = asyncio.Queue()
    asyncio.create_task(_run_suite_task(queue, db, client, suite))

    return StreamingResponse(
        _stream(queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{suite_id}/runs", response_model=list[SuiteRunMeta])
async def list_runs(
    suite_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
    limit: int = 10,
) -> list[SuiteRunMeta]:
    return [SuiteRunMeta(**r) for r in await db.list_suite_runs(suite_id, limit=limit)]


@router.get("/{suite_id}/runs/{run_id}", response_model=SuiteRunDetail)
async def get_run(
    suite_id: int,
    run_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> SuiteRunDetail:
    run = await db.get_suite_run(run_id)
    if run is None or run["suite_id"] != suite_id:
        raise HTTPException(status_code=404, detail="Run не найден")
    return SuiteRunDetail(**run)


# ── Вспомогательные ──────────────────────────────────────────────────────

def _suite_to_schema(suite: dict) -> SuiteOut:
    return SuiteOut(
        id=suite["id"], name=suite["name"], description=suite["description"],
        queries=[SuiteQuery(**q) for q in suite["queries"]],
        created_at=suite["created_at"], updated_at=suite["updated_at"],
    )


async def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            yield ": heartbeat\n\n"
            continue
        if item is None:
            break
        event_name, data = item
        yield await _sse(event_name, data)


async def _run_suite_task(
    queue: asyncio.Queue,
    db: PortalDB,
    client: ParsersClient,
    suite: dict,
) -> None:
    """Сама петля прогона. Любой Exception ловим, чтобы не утратить summary."""
    queries: list[dict] = suite["queries"]
    total = len(queries)
    run_id = await db.create_suite_run(suite_id=suite["id"])

    t_total = time.monotonic()
    passed, failed = 0, 0
    sources: dict[str, int] = {}

    try:
        for idx, q_dict in enumerate(queries, start=1):
            q = q_dict.get("q", "")
            stores = q_dict.get("stores")
            limit = q_dict.get("limit") or 10
            refresh = bool(q_dict.get("refresh", False))

            await queue.put(("suite-item-start", {"idx": idx, "total": total, "query": q}))

            t0 = time.monotonic()
            status: str = "ok"
            error: str | None = None
            snapshot_id: int | None = None
            product_count: int = 0

            try:
                result = await client.search(q, stores=stores, limit=limit, refresh=refresh)
                ms = int((time.monotonic() - t0) * 1000)
                product_count = len(result.products)
                sources[result.source] = sources.get(result.source, 0) + 1

                if result.errors:
                    status = "partial"
                snapshot_id = await db.create_snapshot(
                    name=f"suite#{suite['id']}-{idx}",
                    query=q, stores=stores, limit_n=limit, refresh=refresh,
                    source=result.source, total_ms=ms,
                    error_count=len(result.errors), errors=result.errors,
                    products=result.products,
                    summary={
                        "ms_per_product": round(ms / max(1, len(result.products)), 2),
                        "error_rate": round(len(result.errors) / max(1, len(stores or [])) , 3) if stores else 0.0,
                        "failed": False,
                    },
                )
                if status == "partial":
                    failed += 1
                else:
                    passed += 1
            except Exception as exc:  # noqa: BLE001
                ms = int((time.monotonic() - t0) * 1000)
                status, error = "error", str(exc)
                failed += 1
                logger.warning("suite item failed: %s", exc)

            await db.add_suite_run_item(
                run_id=run_id, query=q, snapshot_id=snapshot_id,
                ms=ms, status=status, error=error,
                product_count=product_count,
            )
            await queue.put(("suite-item-done", {
                "idx": idx, "total": total, "query": q,
                "status": status, "ms": ms,
                "snapshot_id": snapshot_id,
                "error": error,
                "product_count": product_count,
            }))

        ms_total = int((time.monotonic() - t_total) * 1000)
        summary = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "ms_total": ms_total,
            "ms_per_query": round(ms_total / max(1, total), 2),
            "source_breakdown": sources,
        }
        await db.finalize_suite_run(run_id, summary)
        await queue.put(("suite-summary", summary))
    finally:
        await queue.put(None)
