"""Интеграционные тесты /import/bgg.

Чтобы не ходить в реальный BGG, monkey-patch'им httpx.AsyncClient.get
на уровне `catalog.importers.bgg` (там создаётся клиент в _run_bgg_import_job
через with httpx.AsyncClient(...)). Точка перехвата — функция fetch_bgg_thing,
её и подменяем целиком на async-функцию, читающую фикстуру.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from catalog import api as api_mod
from catalog.importers import bgg as bgg_mod
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]

FIXTURE = (Path(__file__).parent / "fixtures" / "bgg_carcassonne.xml").read_text(
    encoding="utf-8"
)


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
async def client(clean_db: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    # Подмена fetch_bgg_thing — НЕ ходим в сеть, читаем фикстуру.
    async def fake_fetch(bgg_id: int, client=None) -> str:
        return FIXTURE.replace('id="822"', f'id="{bgg_id}"')

    monkeypatch.setattr("catalog.routers.imports.fetch_bgg_thing", fake_fetch)

    transport = ASGITransport(app=api_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_bgg_import_creates_game_and_aliases(client: AsyncClient):
    r = await client.post(
        "/import/bgg", params={"wait": "true"}, json={"bgg_id": 822}
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done"
    assert len(job["result"]["imported"]) == 1
    game_id = job["result"]["imported"][0]["game_id"]

    # Проверяем итог: game создан, алиасы есть, основные поля заполнены.
    r = await client.get(f"/games/{game_id}")
    assert r.status_code == 200
    g = r.json()
    assert g["title"] == "Carcassonne"
    assert g["bgg_id"] == 822
    assert g["year"] == 2000
    assert g["source"] == "bgg"
    assert "Klaus-Jürgen Wrede" in g["designers"]
    aliases = {a["alias"] for a in g["aliases"]}
    assert "Каркассон" in aliases


async def test_bgg_import_idempotent(client: AsyncClient):
    """Повторный импорт того же id — обновляет, не падает на uniq и не плодит алиасы."""
    await client.post("/import/bgg", params={"wait": "true"}, json={"bgg_id": 822})
    r2 = await client.post("/import/bgg", params={"wait": "true"}, json={"bgg_id": 822})
    assert r2.status_code == 200
    assert r2.json()["status"] == "done"

    r = await client.get("/games", params={"q": "carcass"})
    body = r.json()
    assert body["total"] == 1  # один Carcassonne, не два

    g = body["items"][0]
    detail = (await client.get(f"/games/{g['id']}")).json()
    aliases = [a["alias"] for a in detail["aliases"]]
    # Каркассон встречается ровно один раз — uq_alias_per_game отрабатывает.
    assert aliases.count("Каркассон") == 1


async def test_bgg_import_400_without_id(client: AsyncClient):
    r = await client.post("/import/bgg", json={})
    assert r.status_code == 400


async def test_get_job_status(client: AsyncClient):
    r = await client.post("/import/bgg", params={"wait": "true"}, json={"bgg_id": 822})
    job_id = r.json()["id"]
    r = await client.get(f"/import/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "done"
