"""Тесты CRUD snapshot-ов и diff."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.db_local import PortalDB


@pytest.mark.asyncio
async def test_create_snapshot_persists_products(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    resp = await http_client.post("/api/snapshots", json={
        "name": "test-1", "query": "Каркассон", "limit": 5,
    })
    assert resp.status_code == 200
    sid = resp.json()["id"]
    assert sid > 0

    snap = await portal_db.get_snapshot(sid)
    assert snap is not None
    assert snap["query"] == "Каркассон"
    assert snap["source"] == "cache"
    assert len(snap["products"]) == 1


@pytest.mark.asyncio
async def test_list_snapshots(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    await portal_db.create_snapshot(
        name="a", query="Q1", stores=None, limit_n=5, refresh=False,
        source="cache", total_ms=100, error_count=0, errors=None, products=[],
    )
    await portal_db.create_snapshot(
        name="b", query="Q2", stores=None, limit_n=5, refresh=False,
        source="network", total_ms=200, error_count=0, errors=None, products=[],
    )
    resp = await http_client.get("/api/snapshots")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_diff_endpoint(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    products_a = [
        {"id": 1, "store_slug": "hobbygames", "title": "Каркассон",
         "price_rub": 1000.0, "url": "u",
         "image_url": None, "image_url_hd": None, "description": None,
         "players": None, "age_min": None, "playtime": None, "rules_url": None,
         "fetched_at": "2026-05-01T00:00:00Z",
         "extra": {"sku": "X1"}},
    ]
    products_b = [
        {**products_a[0], "price_rub": 1200.0},
    ]

    # Создаём snapshot напрямую через PortalDB (минуя HTTP), чтобы control был полный
    from app.schemas import ProductOut
    a_id = await portal_db.create_snapshot(
        name=None, query="Каркассон", stores=None, limit_n=5, refresh=False,
        source="cache", total_ms=100, error_count=0, errors=None,
        products=[ProductOut(**products_a[0])],
    )
    b_id = await portal_db.create_snapshot(
        name=None, query="Каркассон", stores=None, limit_n=5, refresh=False,
        source="cache", total_ms=120, error_count=0, errors=None,
        products=[ProductOut(**products_b[0])],
    )

    resp = await http_client.get(f"/api/snapshots/diff?a={a_id}&b={b_id}")
    assert resp.status_code == 200
    diff = resp.json()
    assert diff["summary"]["changed"] == 1
    assert diff["summary"]["ms_a"] == 100
    assert diff["summary"]["ms_b"] == 120
    item = diff["products"][0]
    assert item["status"] == "changed"
    assert item["fields"]["price_rub"]["delta_pct"] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_delete_snapshot(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    sid = await portal_db.create_snapshot(
        name=None, query="x", stores=None, limit_n=5, refresh=False,
        source="cache", total_ms=10, error_count=0, errors=None, products=[],
    )
    resp = await http_client.delete(f"/api/snapshots/{sid}")
    assert resp.status_code == 200
    assert (await portal_db.get_snapshot(sid)) is None


@pytest.mark.asyncio
async def test_create_favorite_and_list(http_client: AsyncClient) -> None:
    resp = await http_client.post("/api/favorites", json={
        "query": "Каркассон", "stores": ["hobbygames"], "limit": 10, "refresh": False,
    })
    assert resp.status_code == 200
    fav = resp.json()
    assert fav["query"] == "Каркассон"

    listing = (await http_client.get("/api/favorites")).json()
    assert any(f["id"] == fav["id"] for f in listing)

    # Удаление
    resp = await http_client.delete(f"/api/favorites/{fav['id']}")
    assert resp.status_code == 200
