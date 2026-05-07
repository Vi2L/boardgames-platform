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
    # Сетевая ошибка — store-done должен пометить магазины как упавшие
    store_done = [json.loads(d) for n, d in events if n == "store-done"]
    assert all(s["error"] == "parsers search failed" for s in store_done)


@pytest.mark.asyncio
async def test_search_503_from_parsers_emits_typed_api_error(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    """503 от parsers («нет данных и кеша нет») → понятный api-error и
    магазины НЕ помечаются как упавшие — это решение parsers, а не сбой."""
    fake_client.service_error = (
        503,
        "Все магазины вернули ошибку и кеша нет. Ошибки: {}",
    )
    events = await collect_sse_events(http_client, "/api/search?q=Геркулес")

    names = [n for n, _ in events]
    assert "api-error" in names
    assert "results" not in names

    error_payload = json.loads(next(d for n, d in events if n == "api-error"))
    assert error_payload["status_code"] == 503
    assert "Все магазины вернули ошибку" in error_payload["error"]
    # Технические HTTPStatusError-сообщения не должны просачиваться
    assert "Server error" not in error_payload["error"]

    # store-done без error: магазины не виноваты
    store_done = [json.loads(d) for n, d in events if n == "store-done"]
    assert store_done, "ожидаем хотя бы один store-done"
    assert all(s.get("error") is None for s in store_done)
