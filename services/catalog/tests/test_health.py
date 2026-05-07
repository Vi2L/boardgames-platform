"""Smoke-тест skeleton'а. БД не нужна — /health синхронный.

Этот тест намеренно не покрывает /health/db — для него нужен живой Postgres,
такие тесты появятся на этапе 2 (модель данных + миграции) с pytest-fixtures
поверх testcontainers/реального docker-compose.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from catalog.api import app


@pytest.mark.asyncio
async def test_health_returns_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "boardgames-catalog"
