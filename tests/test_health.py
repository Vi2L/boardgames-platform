"""Тесты /api/health.

Проверяем, что health всегда отвечает 200 — даже при недоступности parsers.
Это контракт: фронт строит индикатор именно на содержимом ответа, а не
на HTTP-коде.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import FakeParsersClient


@pytest.mark.asyncio
async def test_health_ok_when_parsers_reachable(http_client: AsyncClient) -> None:
    resp = await http_client.get("/api/health")
    assert resp.status_code == 200

    data = resp.json()
    assert data["app"] == "ok"
    assert data["parsers_api"] == "ok"
    assert "parsers_url" in data
    assert "error" not in data


@pytest.mark.asyncio
async def test_health_reports_unreachable_parsers(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    fake_client.should_fail_stores = True

    resp = await http_client.get("/api/health")
    # Все ещё 200 — индикатор строится на полях ответа, а не на коде.
    assert resp.status_code == 200

    data = resp.json()
    assert data["app"] == "ok"
    assert data["parsers_api"] == "unreachable"
    assert "error" in data
    assert "parsers unreachable" in data["error"]
