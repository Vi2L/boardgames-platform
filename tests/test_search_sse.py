"""Тесты SSE-потока /api/search.

Проверяем порядок и комплект событий, которые фронт ожидает от backend.
Поскольку именно этот контракт ломался при миграции (см. фикс P1.1 в
lib/sse.ts), важно зафиксировать его тестами.
"""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from tests.conftest import FakeParsersClient, collect_sse_events


@pytest.mark.asyncio
async def test_search_emits_events_in_expected_order(
    http_client: AsyncClient,
) -> None:
    events = await collect_sse_events(http_client, "/api/search?q=test")

    names = [name for name, _ in events]
    # Ключевые события в правильном порядке (между ними могут быть store-* per-store)
    assert "store-start" in names
    assert "api-request" in names
    assert "api-response" in names
    assert "store-done" in names
    assert "results" in names

    # api-request должен идти после store-start, results — последним
    assert names.index("store-start") < names.index("api-request")
    assert names.index("api-request") < names.index("api-response")
    assert names.index("api-response") < names.index("store-done")
    assert names.index("results") == len(names) - 1


@pytest.mark.asyncio
async def test_search_results_contain_products(http_client: AsyncClient) -> None:
    events = await collect_sse_events(http_client, "/api/search?q=test")
    results_payload = next((data for name, data in events if name == "results"), None)
    assert results_payload is not None

    parsed = json.loads(results_payload)
    assert parsed["query"] == "test"
    assert parsed["source"] == "cache"
    assert isinstance(parsed["products"], list)
    assert len(parsed["products"]) == 1
    assert parsed["products"][0]["title"] == "Каркассон"


@pytest.mark.asyncio
async def test_search_emits_api_error_when_parsers_fail(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    fake_client.should_fail_search = True
    events = await collect_sse_events(http_client, "/api/search?q=test")

    names = [name for name, _ in events]
    assert "api-error" in names
    # results не должен прийти — поток завершён ошибкой
    assert "results" not in names

    error_payload = next(data for name, data in events if name == "api-error")
    parsed = json.loads(error_payload)
    assert "parsers search failed" in parsed["error"]
    assert "elapsed_ms" in parsed
