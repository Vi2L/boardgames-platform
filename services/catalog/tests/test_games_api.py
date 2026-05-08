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


async def test_search_substring_short_query(client: AsyncClient):
    """Короткий запрос (4 символа) должен находить ВСЁ, что содержит подстроку.

    pg_trgm % с дефолтным similarity_threshold=0.3 на 4-буквенных запросах часто
    отсекает релевантные результаты — фикс через ILIKE-substring дополнение.
    Регресс-тест на проблему: 'Azul' возвращал только 6 игр из ~162K.
    """
    titles = ["Azul", "Azul Mini", "Azul: Summer Pavilion", "FUCAZUL!", "Settlers"]
    for i, t in enumerate(titles):
        await client.post("/games", json={"slug": f"sub{i}", "title": t})

    r = await client.get("/games", params={"q": "Azul", "limit": 50})
    assert r.status_code == 200
    body = r.json()
    found = {item["title"] for item in body["items"]}
    # Все 4 игры с подстрокой "Azul" (case-insensitive) должны найтись:
    assert {"Azul", "Azul Mini", "Azul: Summer Pavilion", "FUCAZUL!"} <= found
    assert "Settlers" not in found


async def test_search_substring_priority_over_fuzzy(client: AsyncClient):
    """Точные substring-matches идут первыми в выдаче, fuzzy — после.

    'Azul Mini' содержит подстроку — score=1.0. 'Azuleo' только похож по
    триграммам — score < 1.0. Substring должен быть выше в результатах.
    """
    await client.post("/games", json={"slug": "az1", "title": "Azuleo"})
    await client.post("/games", json={"slug": "az2", "title": "Azul Mini"})
    r = await client.get("/games", params={"q": "Azul"})
    titles = [item["title"] for item in r.json()["items"]]
    assert "Azul Mini" in titles
    assert "Azuleo" in titles
    assert titles.index("Azul Mini") < titles.index("Azuleo")


async def test_search_escapes_like_wildcards(client: AsyncClient):
    """Символы % и _ в запросе — литералы, не LIKE-wildcards.

    Иначе пользовательский ввод 'A%' матчил бы вообще всё, что начинается с 'A'.
    """
    await client.post("/games", json={"slug": "p1", "title": "100% Pure"})
    await client.post("/games", json={"slug": "p2", "title": "Other game"})
    r = await client.get("/games", params={"q": "100%"})
    titles = [item["title"] for item in r.json()["items"]]
    assert "100% Pure" in titles
    assert "Other game" not in titles


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


async def test_game_offers_endpoint(client: AsyncClient):
    """GET /games/{id}/offers — возвращает offers, привязанные к игре,
    с группировкой по магазину (через сортировку store_slug ASC, last_price)."""
    g = (await client.post("/games", json={"slug": "g1", "title": "Game 1"})).json()
    # Два offer'а в разных магазинах с auto-match через ingest.
    await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [{"external_id": "h1", "title": "Game 1", "url": "https://h/1",
                           "price": 10000, "sku": "HB-1", "in_stock": True}],
        },
    )
    await client.post(
        "/ingest/offers",
        json={
            "store_slug": "lavkaigr",
            "products": [{"external_id": "l1", "title": "Game 1", "url": "https://l/1",
                           "price": 9500}],
        },
    )
    r = await client.get(f"/games/{g['id']}/offers")
    assert r.status_code == 200
    body = r.json()
    assert body["game_id"] == g["id"]
    assert body["total"] == 2
    # Сортировка по store_slug
    assert [it["store_slug"] for it in body["items"]] == ["hobbygames", "lavkaigr"]
    # Нормализованные поля переехали в колонки
    hg = next(it for it in body["items"] if it["store_slug"] == "hobbygames")
    assert hg["sku"] == "HB-1"
    assert hg["in_stock"] is True


async def test_game_offers_404(client: AsyncClient):
    """Запрос offers для несуществующей игры → 404 (важно отличать от
    «нет offers у существующей»)."""
    r = await client.get("/games/99999/offers")
    assert r.status_code == 404


async def test_game_children(client: AsyncClient):
    """GET /games/{id}/children — игры с parent_game_id = текущая.
    Сортировка по kind (expansion → promo → accessory)."""
    base = (await client.post("/games", json={"slug": "base", "title": "Base"})).json()
    # Создаём детей с разными kind через PATCH (POST не принимает parent_game_id?
    # принимает, см. GameCreate)
    exp = (await client.post(
        "/games", json={"slug": "exp", "title": "Expansion", "kind": "expansion",
                          "parent_game_id": base["id"]},
    )).json()
    promo = (await client.post(
        "/games", json={"slug": "pr", "title": "Promo", "kind": "promo",
                          "parent_game_id": base["id"]},
    )).json()

    r = await client.get(f"/games/{base['id']}/children")
    assert r.status_code == 200
    body = r.json()
    assert body["parent_game_id"] == base["id"]
    assert body["total"] == 2
    # expansion раньше promo по нашему CASE-ordering
    assert [c["kind"] for c in body["items"]] == ["expansion", "promo"]
    assert {c["id"] for c in body["items"]} == {exp["id"], promo["id"]}

    # У ребёнка нет своих детей
    r = await client.get(f"/games/{exp['id']}/children")
    assert r.json()["total"] == 0


async def test_404_on_missing_game(client: AsyncClient):
    r = await client.get("/games/99999")
    assert r.status_code == 404
