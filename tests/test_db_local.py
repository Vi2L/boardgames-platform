"""Тесты PortalDB — миграции, upsert/list/get/delete, log_search."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.db_local import PortalDB
from app.schemas import ProductOut


def _mk(id_: int, slug: str, title: str, price: float, **extra) -> ProductOut:
    return ProductOut(
        id=id_, store_slug=slug, title=title, price_rub=price,
        url=f"https://example.com/{id_}",
        image_url=None, image_url_hd=None,
        description=None, players=None, age_min=None,
        playtime=None, rules_url=None,
        fetched_at="2026-05-07T10:00:00Z",
        extra=extra,
    )


@pytest.mark.asyncio
async def test_init_creates_schema(tmp_path: Path) -> None:
    db = PortalDB(tmp_path / "p.sqlite")
    await db.init()
    # повторный init не должен падать (миграции идемпотентны)
    await db.init()
    await db.close()


@pytest.mark.asyncio
async def test_upsert_and_list(portal_db: PortalDB) -> None:
    await portal_db.upsert_products([
        _mk(1, "hobbygames", "Каркассон", 1990.0),
        _mk(2, "lavkaigr",   "Манчкин",   790.0),
    ])

    page = await portal_db.list_products(page=1, page_size=10)
    assert page["total"] == 2
    assert {p.id for p in page["items"]} == {1, 2}


@pytest.mark.asyncio
async def test_upsert_updates_existing(portal_db: PortalDB) -> None:
    await portal_db.upsert_products([_mk(1, "hobbygames", "Каркассон", 1990.0)])
    await portal_db.upsert_products([_mk(1, "hobbygames", "Каркассон. Новая", 2090.0)])

    page = await portal_db.list_products()
    assert page["total"] == 1
    assert page["items"][0].title == "Каркассон. Новая"
    assert page["items"][0].price_rub == 2090.0


@pytest.mark.asyncio
async def test_filter_by_query(portal_db: PortalDB) -> None:
    await portal_db.upsert_products([
        _mk(1, "hobbygames", "Каркассон", 1990.0),
        _mk(2, "hobbygames", "Манчкин",   790.0),
        _mk(3, "lavkaigr",   "КаРкаССон. Расширение", 990.0),  # case-insensitive поиск
    ])

    page = await portal_db.list_products(q="каркассон")
    assert page["total"] == 2
    assert {p.id for p in page["items"]} == {1, 3}


@pytest.mark.asyncio
async def test_filter_by_store(portal_db: PortalDB) -> None:
    await portal_db.upsert_products([
        _mk(1, "hobbygames", "Каркассон", 1990.0),
        _mk(2, "lavkaigr",   "Манчкин",   790.0),
    ])

    page = await portal_db.list_products(store="hobbygames")
    assert page["total"] == 1
    assert page["items"][0].store_slug == "hobbygames"


@pytest.mark.asyncio
async def test_sort_by_price(portal_db: PortalDB) -> None:
    await portal_db.upsert_products([
        _mk(1, "hobbygames", "Дорогой", 5000.0),
        _mk(2, "hobbygames", "Дешёвый", 100.0),
        _mk(3, "hobbygames", "Средний", 1500.0),
    ])

    page_asc = await portal_db.list_products(sort="price_asc")
    assert [p.price_rub for p in page_asc["items"]] == [100.0, 1500.0, 5000.0]

    page_desc = await portal_db.list_products(sort="price_desc")
    assert [p.price_rub for p in page_desc["items"]] == [5000.0, 1500.0, 100.0]


@pytest.mark.asyncio
async def test_pagination(portal_db: PortalDB) -> None:
    await portal_db.upsert_products([
        _mk(i, "hobbygames", f"Игра {i}", float(i * 100))
        for i in range(1, 11)
    ])

    page1 = await portal_db.list_products(page=1, page_size=3, sort="price_asc")
    page2 = await portal_db.list_products(page=2, page_size=3, sort="price_asc")
    assert page1["total"] == 10
    assert [p.id for p in page1["items"]] == [1, 2, 3]
    assert [p.id for p in page2["items"]] == [4, 5, 6]


@pytest.mark.asyncio
async def test_get_and_delete(portal_db: PortalDB) -> None:
    await portal_db.upsert_products([_mk(42, "gaga", "Test", 100.0)])
    assert (await portal_db.get_product(42)) is not None

    assert await portal_db.delete_product(42) is True
    assert (await portal_db.get_product(42)) is None
    # повторное удаление возвращает False
    assert await portal_db.delete_product(42) is False


@pytest.mark.asyncio
async def test_extra_json_roundtrip(portal_db: PortalDB) -> None:
    """extra сериализуется/десериализуется корректно, в т.ч. вложенные структуры."""
    await portal_db.upsert_products([
        _mk(1, "gaga", "Каркассон", 1990.0,
            tags=["плитки", "семейная"],
            dimensions="27×19×6",
            offline_price=234000),
    ])
    p = await portal_db.get_product(1)
    assert p is not None
    assert p.extra["tags"] == ["плитки", "семейная"]
    assert p.extra["dimensions"] == "27×19×6"
    assert p.extra["offline_price"] == 234000


@pytest.mark.asyncio
async def test_log_search_and_list(portal_db: PortalDB) -> None:
    sid1 = await portal_db.log_search(
        query="Каркассон", stores=["hobbygames", "gaga"], source="cache",
        total_ms=420, products_count=8, error_count=0,
    )
    sid2 = await portal_db.log_search(
        query="Манчкин", stores=None, source="network",
        total_ms=1200, products_count=3, error_count=1,
        errors={"lavkaigr": "timeout"},
    )
    assert sid1 > 0 and sid2 > sid1

    page = await portal_db.list_searches()
    assert page["total"] == 2
    # Сортировка по created_at DESC
    assert page["items"][0]["query"] == "Манчкин"
    assert page["items"][1]["query"] == "Каркассон"
    assert page["items"][0]["error_count"] == 1
