"""Интеграционные тесты CRUD-эндпоинтов /games через FastAPI ASGITransport.

Перед каждым тестом таблицы каталога TRUNCATE'ятся — мы хотим воспроизводимое
состояние, а не накопительное. Это интеграционный, не unit-тест: он ходит в
живую БД, в отличие от test_bgg_parser.py.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from catalog.api import app
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]


@pytest_asyncio.fixture
async def clean_db(engine: AsyncEngine) -> None:
    """Чистит каталоговые таблицы перед каждым api-тестом.

    `RESTART IDENTITY` сбрасывает sequences — id всегда начинается с 1, что делает
    тесты предсказуемыми (но не зависимыми от конкретного id).
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE games, game_aliases, offers, offer_prices, "
                "import_jobs RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def client(clean_db: None) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_create_and_get_game(client: AsyncClient):
    r = await client.post(
        "/games",
        json={"slug": "carcassonne", "title": "Каркассон", "year": 2000},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["slug"] == "carcassonne"
    assert created["title"] == "Каркассон"

    r = await client.get(f"/games/{created['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Каркассон"
    assert body["aliases"] == []


async def test_duplicate_slug_409(client: AsyncClient):
    payload = {"slug": "dup", "title": "A"}
    r1 = await client.post("/games", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/games", json={"slug": "dup", "title": "B"})
    assert r2.status_code == 409


async def test_search_with_pg_trgm(client: AsyncClient):
    await client.post(
        "/games", json={"slug": "carc", "title": "Каркассон", "year": 2000}
    )
    await client.post(
        "/games", json={"slug": "catan", "title": "Колонизаторы", "year": 1995}
    )
    # Опечатка в запросе — должны найти Каркассон.
    r = await client.get("/games", params={"q": "каркасон"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Каркассон"


async def test_patch_partial(client: AsyncClient):
    r = await client.post("/games", json={"slug": "p", "title": "Old"})
    gid = r.json()["id"]
    r = await client.patch(f"/games/{gid}", json={"title": "New", "year": 2024})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "New"
    assert body["year"] == 2024
    # slug не должен поменяться (его в payload не было).
    assert body["slug"] == "p"


async def test_add_alias(client: AsyncClient):
    r = await client.post("/games", json={"slug": "a", "title": "Carcassonne"})
    gid = r.json()["id"]
    r = await client.post(f"/games/{gid}/aliases", json={"alias": "Каркассон"})
    assert r.status_code == 201
    # Дубликат → 409.
    r = await client.post(f"/games/{gid}/aliases", json={"alias": "Каркассон"})
    assert r.status_code == 409
    # GET карточки показывает алиас.
    r = await client.get(f"/games/{gid}")
    assert len(r.json()["aliases"]) == 1


async def test_pagination_and_total(client: AsyncClient):
    for i in range(5):
        await client.post("/games", json={"slug": f"g{i}", "title": f"Game {i}"})
    r = await client.get("/games", params={"limit": 2, "offset": 1})
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 1


async def test_404_on_missing_game(client: AsyncClient):
    r = await client.get("/games/99999")
    assert r.status_code == 404
