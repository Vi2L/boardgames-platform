"""Тесты HTTP-эндпоинтов /api/db/*."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.db_local import PortalDB
from app.schemas import PricePointOut, ProductOut
from tests.conftest import FakeParsersClient


def _mk_product(id_: int, slug: str = "hobbygames", title: str = "Test", price: float = 100.0) -> ProductOut:
    return ProductOut(
        id=id_, store_slug=slug, title=title, price_rub=price,
        url=f"https://example.com/{id_}",
        image_url=None, image_url_hd=None,
        description=None, players=None, age_min=None,
        playtime=None, rules_url=None,
        fetched_at="2026-05-07T10:00:00Z",
        extra={},
    )


@pytest.mark.asyncio
async def test_list_products_empty(http_client: AsyncClient) -> None:
    resp = await http_client.get("/api/db/products")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"items": [], "total": 0, "page": 1, "page_size": 50}


@pytest.mark.asyncio
async def test_list_products_with_filters(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    await portal_db.upsert_products([
        _mk_product(1, "hobbygames", "Каркассон", 1990.0),
        _mk_product(2, "lavkaigr",   "Манчкин",   790.0),
    ])

    resp = await http_client.get("/api/db/products?store=hobbygames")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["store_slug"] == "hobbygames"


@pytest.mark.asyncio
async def test_get_product_returns_history(
    http_client: AsyncClient, portal_db: PortalDB, fake_client: FakeParsersClient,
) -> None:
    await portal_db.upsert_products([_mk_product(7, "gaga", "Test", 500.0)])
    fake_client.histories[7] = [
        PricePointOut(price=50000, price_rub=500.0, fetched_at="2026-05-07T10:00:00Z"),
    ]

    resp = await http_client.get("/api/db/products/7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 7
    assert len(data["observations"]) == 1
    assert data["observations"][0]["price_rub"] == 500.0


@pytest.mark.asyncio
async def test_get_product_404(http_client: AsyncClient) -> None:
    resp = await http_client.get("/api/db/products/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_product_handles_history_failure(
    http_client: AsyncClient, portal_db: PortalDB, fake_client: FakeParsersClient,
) -> None:
    """Если parsers упал — карточка всё равно отдаётся, history=[]."""
    await portal_db.upsert_products([_mk_product(8, "gaga", "Test", 500.0)])

    # Подменяем get_history так, чтобы он бросал
    async def boom(_pid: int):
        raise RuntimeError("parsers died")
    fake_client.get_history = boom  # type: ignore[method-assign]

    resp = await http_client.get("/api/db/products/8")
    assert resp.status_code == 200
    assert resp.json()["observations"] == []


@pytest.mark.asyncio
async def test_delete_product(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    await portal_db.upsert_products([_mk_product(11)])
    resp = await http_client.delete("/api/db/products/11")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "id": 11}

    # 404 при повторном удалении
    resp = await http_client.delete("/api/db/products/11")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_searches(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    await portal_db.log_search(
        query="Каркассон", stores=["gaga"], source="cache",
        total_ms=200, products_count=5, error_count=0,
    )
    resp = await http_client.get("/api/db/searches")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["query"] == "Каркассон"


@pytest.mark.asyncio
async def test_search_writes_to_portal_db(
    http_client: AsyncClient, portal_db: PortalDB,
) -> None:
    """E2E: SSE search → запись в local_searches и local_products."""
    # Запрос /api/search; результаты приходят из FakeParsersClient (1 товар)
    resp = await http_client.get("/api/search?q=test")
    # SSE — нужно прочесть весь стрим
    text = resp.text  # ASGITransport читает всё сразу
    assert "results" in text

    # Сразу после SSE _log_to_portal_db уже отработал (await в _run_search)
    page = await portal_db.list_searches()
    assert page["total"] == 1
    assert page["items"][0]["query"] == "test"
    assert page["items"][0]["products_count"] == 1

    products = await portal_db.list_products()
    assert products["total"] == 1
    assert products["items"][0].title == "Каркассон"
