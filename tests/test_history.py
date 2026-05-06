"""Тесты эндпоинтов истории цен."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.schemas import PricePointOut
from tests.conftest import FakeParsersClient


@pytest.mark.asyncio
async def test_history_returns_empty_when_no_data(http_client: AsyncClient) -> None:
    resp = await http_client.get("/api/products/999/history")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_recent_deltas_returns_none_for_short_history(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    # Только одна точка — дельты быть не может.
    fake_client.histories[1] = [
        PricePointOut(price=199000, price_rub=1990.0, fetched_at="2026-05-01T10:00:00Z"),
    ]

    resp = await http_client.get("/api/products/recent-deltas?ids=1")
    assert resp.status_code == 200

    [delta] = resp.json()
    assert delta["product_id"] == 1
    assert delta["delta_pct"] is None
    assert delta["prev_price_rub"] is None
    assert delta["curr_price_rub"] is None


@pytest.mark.asyncio
async def test_recent_deltas_computes_pct_for_two_points(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    fake_client.histories[1] = [
        # parsers возвращает в DESC, мы дополнительно сортируем — порядок здесь не важен
        PricePointOut(price=219000, price_rub=2190.0, fetched_at="2026-05-07T10:00:00Z"),  # curr
        PricePointOut(price=199000, price_rub=1990.0, fetched_at="2026-05-01T10:00:00Z"),  # prev
    ]

    resp = await http_client.get("/api/products/recent-deltas?ids=1")
    [delta] = resp.json()

    assert delta["product_id"] == 1
    assert delta["prev_price_rub"] == 1990.0
    assert delta["curr_price_rub"] == 2190.0
    # (2190 - 1990) / 1990 * 100 ≈ 10.05%
    assert delta["delta_pct"] == pytest.approx(10.05, abs=0.01)
    assert delta["days_between"] == pytest.approx(6.0, abs=0.01)


@pytest.mark.asyncio
async def test_recent_deltas_handles_multiple_ids(
    http_client: AsyncClient, fake_client: FakeParsersClient,
) -> None:
    fake_client.histories[1] = [
        PricePointOut(price=219000, price_rub=2190.0, fetched_at="2026-05-07T10:00:00Z"),
        PricePointOut(price=199000, price_rub=1990.0, fetched_at="2026-05-01T10:00:00Z"),
    ]
    fake_client.histories[2] = []   # пустая история

    resp = await http_client.get("/api/products/recent-deltas?ids=1,2,3")
    deltas = resp.json()
    assert len(deltas) == 3

    by_id = {d["product_id"]: d for d in deltas}
    assert by_id[1]["delta_pct"] == pytest.approx(10.05, abs=0.01)
    assert by_id[2]["delta_pct"] is None
    assert by_id[3]["delta_pct"] is None  # отсутствующий id


@pytest.mark.asyncio
async def test_recent_deltas_empty_for_no_ids(http_client: AsyncClient) -> None:
    resp = await http_client.get("/api/products/recent-deltas?ids=")
    assert resp.status_code == 200
    assert resp.json() == []
