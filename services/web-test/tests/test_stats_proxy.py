"""Тесты прокси /api/stats/*."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import FakeParsersClient


@pytest.mark.asyncio
async def test_stats_summary_proxies(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    async def fake_summary(hours: int = 24):
        return {"total_requests": 42, "cache_hit_rate": 0.7, "hours": hours}
    fake_client.get_summary_stats = fake_summary  # type: ignore[method-assign]

    resp = await http_client.get("/api/stats/summary?hours=12")
    assert resp.status_code == 200
    assert resp.json() == {"total_requests": 42, "cache_hit_rate": 0.7, "hours": 12}


@pytest.mark.asyncio
async def test_stats_summary_falls_back_when_parsers_down(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    async def boom(hours: int = 24):
        raise RuntimeError("parsers down")
    fake_client.get_summary_stats = boom  # type: ignore[method-assign]

    resp = await http_client.get("/api/stats/summary")
    # 200 — не валим UI, отдаём _unavailable
    assert resp.status_code == 200
    data = resp.json()
    assert data["_unavailable"] is True
    assert "parsers down" in data["_error"]


@pytest.mark.asyncio
async def test_stats_stores_proxies(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    async def fake_stores():
        return [
            {"slug": "hobbygames", "success_rate": 0.95, "avg_ms": 1234},
        ]
    fake_client.get_store_stats = fake_stores  # type: ignore[method-assign]

    resp = await http_client.get("/api/stats/stores")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["slug"] == "hobbygames"


@pytest.mark.asyncio
async def test_stats_errors_proxies(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    async def fake_errors(limit: int = 20):
        return [{"slug": "lavkaigr", "error_msg": "timeout", "ts": "2026-05-07T10:00:00Z"}]
    fake_client.get_recent_errors = fake_errors  # type: ignore[method-assign]

    resp = await http_client.get("/api/stats/errors?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["error_msg"] == "timeout"
