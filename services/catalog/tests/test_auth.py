"""Тесты X-API-Key auth со scope'ами.

Существующие тесты ходят без ключа — это работает, пока REQUIRE_AUTH=False
(дефолт). Здесь же мы временно включаем флаг и проверяем 401/403/200 матрицу.

Стратегия: monkeypatch на get_settings — заставляем его вернуть настройки с
require_auth=True. Сами ключи кладём в БД через ORM.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from catalog import api as api_mod
from catalog import config as config_mod
from catalog.auth import generate_key, hash_key
from catalog.config import Settings
from catalog.models import ApiKey
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]


@pytest_asyncio.fixture
async def clean_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE games, game_aliases, offers, offer_prices, "
                "import_jobs, api_keys RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def auth_settings(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Включает require_auth=True на время теста.

    Нюанс: catalog.auth делает `from catalog.config import get_settings` —
    при этом создаётся локальное связывание имени, и monkeypatch на
    catalog.config.get_settings не виден из auth. Поэтому патчим именно
    catalog.auth.get_settings.
    """
    auth_on = Settings(require_auth=True)
    config_mod.get_settings.cache_clear()
    monkeypatch.setattr("catalog.auth.get_settings", lambda: auth_on)
    yield
    config_mod.get_settings.cache_clear()


async def _create_key(engine: AsyncEngine, owner: str, scopes: list[str]) -> str:
    plaintext = generate_key()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        session.add(ApiKey(key_hash=hash_key(plaintext), owner=owner, scopes=scopes))
        await session.commit()
    return plaintext


@pytest_asyncio.fixture
async def client(clean_db: None) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ─── REQUIRE_AUTH=False (дефолт) ───────────────────────────────────────────

async def test_default_auth_off_allows_everything(client: AsyncClient):
    r = await client.post("/games", json={"slug": "x", "title": "X"})
    assert r.status_code == 201


# ─── REQUIRE_AUTH=True ─────────────────────────────────────────────────────

async def test_no_key_returns_401(client: AsyncClient, auth_settings: None):
    r = await client.get("/games")
    assert r.status_code == 401
    assert "X-API-Key" in r.json()["detail"]


async def test_invalid_key_returns_401(client: AsyncClient, auth_settings: None):
    r = await client.get("/games", headers={"X-API-Key": "totally-bogus"})
    assert r.status_code == 401


async def test_read_scope_can_list_but_not_create(
    client: AsyncClient, engine: AsyncEngine, auth_settings: None,
):
    key = await _create_key(engine, "web_test", ["read"])
    h = {"X-API-Key": key}

    r = await client.get("/games", headers=h)
    assert r.status_code == 200

    r = await client.post("/games", headers=h, json={"slug": "x", "title": "X"})
    assert r.status_code == 403
    assert "admin" in r.json()["detail"]


async def test_ingest_scope_can_only_ingest(
    client: AsyncClient, engine: AsyncEngine, auth_settings: None,
):
    key = await _create_key(engine, "parsers", ["ingest"])
    h = {"X-API-Key": key}

    r = await client.post(
        "/ingest/offers",
        headers=h,
        json={
            "store_slug": "hobbygames",
            "products": [
                {"external_id": "1", "title": "Каркассон", "url": "https://h/1"}
            ],
        },
    )
    assert r.status_code == 200

    # Тот же ключ не может листать каталог.
    r = await client.get("/games", headers=h)
    assert r.status_code == 403


async def test_admin_scope_covers_everything(
    client: AsyncClient, engine: AsyncEngine, auth_settings: None,
):
    key = await _create_key(engine, "admin", ["admin"])
    h = {"X-API-Key": key}

    assert (await client.post("/games", headers=h, json={"slug": "a", "title": "A"})).status_code == 201
    assert (await client.get("/games", headers=h)).status_code == 200
    assert (
        await client.post(
            "/ingest/offers",
            headers=h,
            json={
                "store_slug": "x",
                "products": [{"external_id": "1", "title": "T", "url": "u"}],
            },
        )
    ).status_code == 200


async def test_revoked_key_rejected(
    client: AsyncClient, engine: AsyncEngine, auth_settings: None,
):
    """revoked_at != NULL — ключ перестал работать."""
    from datetime import datetime, timezone

    key = await _create_key(engine, "x", ["read"])
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        await session.execute(
            text(
                "UPDATE api_keys SET revoked_at = :ts WHERE key_hash = :h"
            ).bindparams(ts=datetime.now(timezone.utc), h=hash_key(key))
        )
        await session.commit()

    r = await client.get("/games", headers={"X-API-Key": key})
    assert r.status_code == 401
    assert "revoked" in r.json()["detail"]


async def test_health_does_not_require_auth(
    client: AsyncClient, auth_settings: None
):
    """Liveness/readiness — без auth, иначе compose-healthcheck не работает."""
    r = await client.get("/health")
    assert r.status_code == 200
