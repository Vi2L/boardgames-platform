"""Тесты вычисления title_ru в GameOut.

Backend выбирает «лучший» alias-ru по приоритету:
  1) manual + verified=true
  2) dicefest
  3) wikidata
  4) остальные

В list_games берётся через PG DISTINCT ON, в get_game — в Python из уже
загруженных aliases. Оба пути должны давать одинаковый результат.
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


async def _create_game_with_aliases(
    client: AsyncClient, slug: str, title: str,
    aliases: list[dict],
) -> int:
    """Создаёт игру и добавляет к ней набор aliases (PATCH-ом не получится
    указать verified=true, поэтому идём через POST /games/{id}/aliases)."""
    r = await client.post("/games", json={"slug": slug, "title": title})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    for a in aliases:
        ra = await client.post(f"/games/{gid}/aliases", json=a)
        assert ra.status_code == 201, ra.text
    return gid


async def test_title_ru_prefers_verified_manual(client: AsyncClient) -> None:
    """manual+verified=true должен победить dicefest и wikidata."""
    gid = await _create_game_with_aliases(
        client, "myth", "Mythologies",
        aliases=[
            {"alias": "Мифологии (wiki)", "source": "wikidata", "language": "ru"},
            {"alias": "Мифологии (РФ)", "source": "dicefest", "language": "ru"},
            {"alias": "Мифологии", "source": "manual", "language": "ru", "verified": True},
        ],
    )
    r = await client.get(f"/games/{gid}")
    assert r.status_code == 200
    assert r.json()["title_ru"] == "Мифологии"

    # Та же логика в листинге.
    rl = await client.get("/games?q=Mythologies")
    assert rl.status_code == 200
    items = rl.json()["items"]
    assert any(it["id"] == gid and it["title_ru"] == "Мифологии" for it in items)


async def test_title_ru_falls_back_to_dicefest(client: AsyncClient) -> None:
    """Без verified-manual выбирается dicefest, а не wikidata."""
    gid = await _create_game_with_aliases(
        client, "azul", "Azul",
        aliases=[
            {"alias": "Азул (wiki)", "source": "wikidata", "language": "ru"},
            {"alias": "Азул (РФ)", "source": "dicefest", "language": "ru"},
        ],
    )
    r = await client.get(f"/games/{gid}")
    assert r.json()["title_ru"] == "Азул (РФ)"


async def test_title_ru_none_when_no_ru_alias(client: AsyncClient) -> None:
    """Без RU-aliases title_ru должен быть None."""
    gid = await _create_game_with_aliases(
        client, "wingspan", "Wingspan",
        aliases=[
            # Только английский — title_ru должен остаться None.
            {"alias": "Wingspan (BGG)", "source": "bgg", "language": "en"},
        ],
    )
    r = await client.get(f"/games/{gid}")
    assert r.json()["title_ru"] is None


async def test_title_ru_ignores_non_ru_language(client: AsyncClient) -> None:
    """Алиасы с language!='ru' не учитываются при выборе title_ru."""
    gid = await _create_game_with_aliases(
        client, "everdell", "Everdell",
        aliases=[
            # de-aliase — не должен попасть в title_ru
            {"alias": "Everdell DE", "source": "manual", "language": "de", "verified": True},
            {"alias": "Эвердэлл", "source": "wikidata", "language": "ru"},
        ],
    )
    r = await client.get(f"/games/{gid}")
    assert r.json()["title_ru"] == "Эвердэлл"
