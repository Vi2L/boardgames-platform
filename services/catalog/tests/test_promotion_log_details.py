"""Тесты GET /promotion/log/{id}/details.

Покрытие:
- happy path: запись + связанные raw/game/alias возвращаются;
- 404 на несуществующем log_id;
- reverted_by_entry_id корректно ссылается на revert-запись.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from catalog.api import app
from catalog.models import (
    DicefestRawGame,
    Game,
    GameAlias,
    ImportPromotionLog,
)
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]


@pytest_asyncio.fixture
async def clean_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE import_promotion_log, game_dicefest, "
                "dicefest_raw_games, offers, offer_prices, game_aliases, "
                "game_bgg, game_wikidata, games "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def client(clean_db: None) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_log_details_happy_path(client: AsyncClient, engine: AsyncEngine) -> None:
    """Полный happy-path: log + связанные raw/game/alias подгружаются."""
    # Готовим инфраструктуру напрямую через ORM — promotion-логику здесь
    # не тестируем, нам нужен «состоявшийся» лог с заполненными FK.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Factory = async_sessionmaker(engine, expire_on_commit=False)
    async with Factory() as s:
        game = Game(slug="myth", title="Mythologies")
        s.add(game)
        await s.flush()

        raw = DicefestRawGame(
            slug="mythologies",
            page_url="https://dicefest.ru/game/mythologies/",
            title_ru="Mythologies",
            title_en="Mythologies",
            publisher="4GAMES",
            preorder_price=290000,
            external_links=[],
            raw={},
            fetched_at=datetime.now(timezone.utc),
            status="promoted",
        )
        s.add(raw)
        await s.flush()

        alias = GameAlias(
            game_id=game.id,
            alias="Mythologies",
            source="dicefest",
            language="ru",
            verified=True,
        )
        s.add(alias)
        await s.flush()

        log = ImportPromotionLog(
            provider="dicefest",
            raw_id=raw.id,
            action="link",
            game_id=game.id,
            alias_id=alias.id,
            satellite_created=True,
            performed_by="operator",
            notes="manual link",
        )
        s.add(log)
        await s.commit()
        log_id = log.id

    r = await client.get(f"/promotion/log/{log_id}/details")
    assert r.status_code == 200, r.text
    body = r.json()

    # entry — все 11 полей самой записи
    assert body["entry"]["id"] == log_id
    assert body["entry"]["action"] == "link"
    assert body["entry"]["satellite_created"] is True
    assert body["entry"]["notes"] == "manual link"

    # raw_game — подтянулся по raw_id
    assert body["raw_game"] is not None
    assert body["raw_game"]["slug"] == "mythologies"
    assert body["raw_game"]["title_ru"] == "Mythologies"
    assert body["raw_game"]["publisher"] == "4GAMES"
    assert body["raw_game"]["preorder_price"] == 290000

    # game — подтянулся по game_id
    assert body["game"] is not None
    assert body["game"]["slug"] == "myth"
    assert body["game"]["title"] == "Mythologies"

    # alias — подтянулся по alias_id
    assert body["alias"] is not None
    assert body["alias"]["alias"] == "Mythologies"
    assert body["alias"]["source"] == "dicefest"
    assert body["alias"]["verified"] is True

    # ещё не reverted
    assert body["reverted_by_entry_id"] is None


async def test_log_details_404_on_missing(client: AsyncClient) -> None:
    """Несуществующий log_id → 404 с понятным detail."""
    r = await client.get("/promotion/log/99999/details")
    assert r.status_code == 404
    assert "log_id=99999" in r.json()["detail"]


async def test_log_details_returns_revert_pointer(
    client: AsyncClient, engine: AsyncEngine,
) -> None:
    """После revert исходная запись должна вернуть id revert-записи."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Factory = async_sessionmaker(engine, expire_on_commit=False)
    async with Factory() as s:
        raw = DicefestRawGame(
            slug="x",
            page_url="https://dicefest.ru/game/x/",
            external_links=[],
            raw={},
            fetched_at=datetime.now(timezone.utc),
            status="skipped",
        )
        s.add(raw)
        await s.flush()

        # Исходная запись — skip, потом помечена reverted.
        original_perf = datetime.now(timezone.utc)
        original = ImportPromotionLog(
            provider="dicefest",
            raw_id=raw.id,
            action="skip",
            performed_by="operator",
            performed_at=original_perf,
            reverted_at=datetime.now(timezone.utc),
            reverted_by="operator",
        )
        s.add(original)
        await s.flush()

        # Revert-запись с тем же raw_id, action='revert', performed_at >= reverted_at
        revert_entry = ImportPromotionLog(
            provider="dicefest",
            raw_id=raw.id,
            action="revert",
            performed_by="operator",
            notes=f"revert of log #{original.id}",
        )
        s.add(revert_entry)
        await s.commit()
        original_id = original.id
        revert_id = revert_entry.id

    r = await client.get(f"/promotion/log/{original_id}/details")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entry"]["reverted_at"] is not None
    assert body["reverted_by_entry_id"] == revert_id
