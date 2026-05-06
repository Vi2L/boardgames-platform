"""Тесты CRUD сьютов и SSE-прогона."""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from app.db_local import PortalDB
from tests.conftest import collect_sse_events


@pytest.mark.asyncio
async def test_create_and_list_suites(http_client: AsyncClient) -> None:
    payload = {
        "name": "smoke",
        "description": "smoke test",
        "queries": [
            {"q": "Каркассон", "stores": ["hobbygames"], "limit": 5, "refresh": False},
            {"q": "Манчкин", "stores": None, "limit": 10, "refresh": True},
        ],
    }
    resp = await http_client.post("/api/suites", json=payload)
    assert resp.status_code == 200
    suite = resp.json()
    assert suite["id"] > 0
    assert suite["name"] == "smoke"
    assert len(suite["queries"]) == 2

    listing = (await http_client.get("/api/suites")).json()
    assert any(s["id"] == suite["id"] for s in listing)


@pytest.mark.asyncio
async def test_run_suite_emits_full_progress(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    sid = await portal_db.create_suite(
        name="run-test", description=None,
        queries=[
            {"q": "Каркассон"},
            {"q": "Манчкин"},
        ],
    )
    events = await collect_sse_events(http_client, f"/api/suites/{sid}/run")

    names = [e[0] for e in events]
    # Каждому запросу — пара start/done; в конце — summary
    assert names.count("suite-item-start") == 2
    assert names.count("suite-item-done") == 2
    assert names[-1] == "suite-summary"

    summary = json.loads(events[-1][1])
    assert summary["total"] == 2
    assert summary["passed"] + summary["failed"] == 2
    assert summary["ms_total"] >= 0
    assert summary["ms_per_query"] >= 0

    # В БД появился run и его items
    runs = await portal_db.list_suite_runs(sid)
    assert len(runs) == 1
    run_id = runs[0]["id"]
    detail = await portal_db.get_suite_run(run_id)
    assert detail is not None
    assert len(detail["items"]) == 2
    assert all(it["status"] in {"ok", "partial"} for it in detail["items"])
    # Каждый item должен ссылаться на созданный snapshot
    assert all(it["snapshot_id"] is not None for it in detail["items"])


@pytest.mark.asyncio
async def test_run_suite_records_error_per_item(
    http_client: AsyncClient, portal_db: PortalDB, fake_client,
) -> None:
    sid = await portal_db.create_suite(
        name="failing", description=None,
        queries=[{"q": "Каркассон"}],
    )
    fake_client.should_fail_search = True
    events = await collect_sse_events(http_client, f"/api/suites/{sid}/run")
    item_done = next(e for e in events if e[0] == "suite-item-done")
    payload = json.loads(item_done[1])
    assert payload["status"] == "error"
    assert "parsers search failed" in payload["error"]


@pytest.mark.asyncio
async def test_get_suite_returns_404(http_client: AsyncClient) -> None:
    resp = await http_client.get("/api/suites/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_suite_cascades_runs(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    sid = await portal_db.create_suite(
        name="to-delete", description=None,
        queries=[{"q": "x"}],
    )
    run_id = await portal_db.create_suite_run(sid)
    await portal_db.add_suite_run_item(
        run_id=run_id, query="x", snapshot_id=None, ms=10, status="ok",
    )

    resp = await http_client.delete(f"/api/suites/{sid}")
    assert resp.status_code == 200

    # Run и run-items должны быть удалены каскадно
    assert await portal_db.list_suite_runs(sid) == []
