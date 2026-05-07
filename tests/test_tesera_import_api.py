"""Интеграционные тесты /import/tesera через ASGI + живой Postgres."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from catalog import api as api_mod
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]

FIXTURE = (
    Path(__file__).parent / "fixtures" / "tesera_carcassonne.json"
).read_text(encoding="utf-8")


@pytest_asyncio.fixture
async def clean_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE games, game_aliases, offers, offer_prices, "
                "import_jobs RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def client(
    clean_db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    async def fake_fetch(item, client=None) -> str:
        return FIXTURE

    monkeypatch.setattr(
        "catalog.routers.imports.fetch_tesera_thing", fake_fetch
    )
    transport = ASGITransport(app=api_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_tesera_import_creates_game(client: AsyncClient):
    r = await client.post(
        "/import/tesera", params={"wait": "true"}, json={"alias": "carcassonne"}
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done"
    gid = job["result"]["imported"][0]["game_id"]

    g = (await client.get(f"/games/{gid}")).json()
    assert g["title"] == "Каркассон"
    assert g["tesera_id"] == 822
    assert g["source"] == "tesera"
    aliases = {a["alias"] for a in g["aliases"]}
    assert "Carcassonne" in aliases  # title_en вынесен в alias


async def test_tesera_import_idempotent(client: AsyncClient):
    await client.post(
        "/import/tesera", params={"wait": "true"}, json={"alias": "carcassonne"}
    )
    r2 = await client.post(
        "/import/tesera", params={"wait": "true"}, json={"tesera_id": 822}
    )
    assert r2.json()["status"] == "done"

    body = (await client.get("/games", params={"q": "каркасон"})).json()
    assert body["total"] == 1
    detail = (await client.get(f"/games/{body['items'][0]['id']}")).json()
    assert sum(1 for a in detail["aliases"] if a["alias"] == "Carcassonne") == 1


async def test_tesera_400_without_args(client: AsyncClient):
    r = await client.post("/import/tesera", json={})
    assert r.status_code == 400


async def test_tesera_batch(client: AsyncClient):
    r = await client.post(
        "/import/tesera",
        params={"wait": "true"},
        json={"items": ["carcassonne", "carcassonne"]},
    )
    body = r.json()
    # Два запроса возвращают одинаковый объект — итого один game.
    assert body["status"] == "done"
    assert len(body["result"]["imported"]) == 2
    games = (await client.get("/games")).json()
    assert games["total"] == 1
