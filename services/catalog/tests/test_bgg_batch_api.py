"""Интеграционные тесты `POST /import/bgg/batch`.

Слои:
- Валидация (rank_le / all_ranked взаимоисключают, обязателен один) — без БД.
- E2E с БД через `wait=true` + MockTransport: dry_run, реальная запись,
  прогресс/лог в ImportJob.

Подмена BGG: вместо реальной сети делаем `httpx.MockTransport` через
`app.dependency_overrides[get_batch_bgg_client]`, чтобы возвращать
заранее заготовленный batch-XML.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from catalog import api as api_mod
from catalog.parsers.bgg import BggClient
from catalog.routers.imports import get_batch_bgg_client
from tests.conftest import requires_db

FIXTURE_BATCH = (
    Path(__file__).parent / "fixtures" / "bgg_things_batch.xml"
).read_text(encoding="utf-8")


# ─── валидация (без БД) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_400_without_scope():
    """Ни rank_le, ни all_ranked → 400."""
    transport = httpx.ASGITransport(app=api_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/import/bgg/batch", json={})
    assert r.status_code == 400
    assert "rank_le" in r.json()["detail"]


@pytest.mark.asyncio
async def test_batch_400_with_both_scopes():
    """rank_le И all_ranked одновременно → 400."""
    transport = httpx.ASGITransport(app=api_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/import/bgg/batch", json={"rank_le": 100, "all_ranked": True})
    assert r.status_code == 400
    assert "взаимоисключ" in r.json()["detail"]


@pytest.mark.asyncio
async def test_batch_422_invalid_batch_size():
    """batch_size > 20 → 422 (Pydantic le=20)."""
    transport = httpx.ASGITransport(app=api_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/import/bgg/batch",
            json={"rank_le": 100, "batch_size": 50},
        )
    assert r.status_code == 422


# ─── E2E (требует БД) ────────────────────────────────────────────────────────

pytestmark = []  # `requires_db` ставим только на классы с БД ниже.


def _mock_client_factory(handler):
    """Подменяет get_batch_bgg_client на BggClient с MockTransport."""

    def _factory():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return BggClient(client=http)

    return _factory


@pytest_asyncio.fixture
async def clean_batch_db(engine: AsyncEngine) -> None:
    """TRUNCATE + seed: одна игра в game_bgg как кандидат для enrich."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE games, game_aliases, game_bgg, game_wikidata, "
                "offers, offer_prices, import_jobs RESTART IDENTITY CASCADE"
            )
        )
        # Сидим slim-Game (как от import_bgg_ranks.py) — без описания,
        # mechanics и т.п., чтобы enrich мог их заполнить.
        await conn.execute(
            text(
                """
                INSERT INTO games (slug, title, year, bgg_id, source, status)
                VALUES ('carcassonne-822', 'Carcassonne', 2000, 822,
                        'bgg-ranks', 'published')
                RETURNING id
                """
            )
        )
        # game_bgg: rank=20, source='csv-ranks', чтобы попасть в кандидаты enrich'а.
        await conn.execute(
            text(
                """
                INSERT INTO game_bgg (game_id, bgg_id, rank, source, raw)
                SELECT g.id, 822, 20, 'csv-ranks', '{}'::jsonb FROM games g WHERE g.bgg_id = 822
                """
            )
        )


@pytest_asyncio.fixture
async def batch_client(clean_batch_db) -> AsyncIterator[httpx.AsyncClient]:
    """API-клиент с подменённым BGG-клиентом (MockTransport)."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Возвращаем фикстуру с двумя играми; в ней Carcassonne (id=822) и Catan (id=13).
        return httpx.Response(200, text=FIXTURE_BATCH)

    api_mod.app.dependency_overrides[get_batch_bgg_client] = _mock_client_factory(handler)
    try:
        transport = httpx.ASGITransport(app=api_mod.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        api_mod.app.dependency_overrides.clear()


@pytest.mark.asyncio
@requires_db
async def test_batch_dry_run_does_not_write(batch_client: httpx.AsyncClient):
    """dry_run=true: HTTP идёт, но в БД ничего не меняется."""
    r = await batch_client.post(
        "/import/bgg/batch",
        params={"wait": "true"},
        json={"rank_le": 100, "dry_run": True, "rate_limit_sec": 0.0},
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done"
    assert job["result"]["enriched"] == 1
    assert job["result"]["skipped"] == 0
    assert job["result"]["failed"] == 0

    # Игра остаётся slim — description пуст.
    g = (await batch_client.get("/games/1")).json()
    assert g["description"] is None


@pytest.mark.asyncio
@requires_db
async def test_batch_writes_to_satellite(batch_client: httpx.AsyncClient):
    """Реальный прогон: games обогащается, game_bgg + aliases пишутся."""
    r = await batch_client.post(
        "/import/bgg/batch",
        params={"wait": "true"},
        json={"rank_le": 100, "rate_limit_sec": 0.0, "skip_recent_days": 0},
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done"
    assert job["result"]["enriched"] == 1

    # 1. games обогатилась: description, designers, players_*
    g = (await batch_client.get("/games/1")).json()
    assert g["description"] == "Tile-laying game."
    assert g["players_min"] == 2
    assert g["players_max"] == 5
    assert "Klaus-Jürgen Wrede" in g["designers"]

    # 2. game_aliases — Каркассон с source='bgg'
    aliases = g["aliases"]
    bgg_aliases = [a for a in aliases if a["source"] == "bgg"]
    assert any(a["alias"] == "Каркассон" for a in bgg_aliases)

    # 3. game_bgg satellite — mechanics/categories
    detail = g  # GameDetailOut приходит с bgg
    assert detail["bgg"]["mechanics"] is not None
    assert "Tile Placement" in detail["bgg"]["mechanics"]
    assert detail["bgg"]["source"] == "xml-api"


@pytest.mark.asyncio
@requires_db
async def test_batch_progress_and_log_filled(batch_client: httpx.AsyncClient):
    """После прогона ImportJob.progress и log_lines содержат строки."""
    r = await batch_client.post(
        "/import/bgg/batch",
        params={"wait": "true"},
        json={"rank_le": 100, "rate_limit_sec": 0.0, "skip_recent_days": 0},
    )
    job_id = r.json()["id"]
    job = (await batch_client.get(f"/import/jobs/{job_id}")).json()

    # progress должен быть в финальном состоянии phase='done'.
    assert job["progress"] is not None
    assert job["progress"]["phase"] == "done"

    # log_lines содержит хотя бы одну строку.
    assert isinstance(job["log_lines"], list)
    assert len(job["log_lines"]) > 0
    assert any("BGG batch enrich" in line for line in job["log_lines"])


@pytest.mark.asyncio
@requires_db
async def test_batch_idempotent_skips_recent(batch_client: httpx.AsyncClient):
    """Повторный прогон с skip_recent_days>0 пропускает только что обогащённые."""
    # Первый — обогащает.
    await batch_client.post(
        "/import/bgg/batch",
        params={"wait": "true"},
        json={"rank_le": 100, "rate_limit_sec": 0.0, "skip_recent_days": 0},
    )
    # Второй — skip_recent_days=30 → ничего не должно быть в кандидатах.
    r = await batch_client.post(
        "/import/bgg/batch",
        params={"wait": "true"},
        json={"rank_le": 100, "rate_limit_sec": 0.0, "skip_recent_days": 30},
    )
    job = r.json()
    assert job["result"] == {"enriched": 0, "skipped": 0, "failed": 0, "errors": []}
