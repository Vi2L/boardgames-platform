"""Тесты BGG search-парсера, клиента и endpoint'а `POST /parsers/bgg/search`.

Слои:
- `parse_search_xml` — pure-функция, статичная фикстура (без сети).
- `BggClient.search` — `httpx.MockTransport` подменяет сетевой ответ.
- `search_games` (service) — тонкий оркестратор, тестируется вместе с client'ом.
- endpoint `/parsers/bgg/search` — e2e через httpx.ASGITransport.

Без реального BGG: мы не зависим от сети для CI и не нагружаем чужой API.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from catalog.parsers.bgg import (
    BggClient,
    parse_search_xml,
    search_games,
)
from catalog.parsers.bgg.client import BGG_BASE_URL

FIXTURE_SEARCH = Path(__file__).parent / "fixtures" / "bgg_search_carcassonne.xml"


# ---------- pure parser ----------

def test_parse_search_xml_basic():
    xml = FIXTURE_SEARCH.read_text(encoding="utf-8")
    hits = parse_search_xml(xml)
    # Ожидаем 3 boardgame'а с primary name (4-й — accessory, 5-й — без primary).
    assert len(hits) == 3
    bgg_ids = [h.bgg_id for h in hits]
    assert 822 in bgg_ids
    assert 478 in bgg_ids
    assert 9217 in bgg_ids

    # Точечно проверим первую — самую важную.
    carc = next(h for h in hits if h.bgg_id == 822)
    assert carc.title == "Carcassonne"
    assert carc.year == 2000


def test_parse_search_xml_filters_non_boardgame():
    """`type='boardgameaccessory'` должен быть отфильтрован (search принимает type=boardgame)."""
    xml = FIXTURE_SEARCH.read_text(encoding="utf-8")
    hits = parse_search_xml(xml)
    # Accessory id=999999 должен быть выкинут.
    assert all(h.bgg_id != 999999 for h in hits)


def test_parse_search_xml_skips_alternate_only():
    """Без `type='primary'` имени — позиция бесполезна, пропускаем."""
    xml = FIXTURE_SEARCH.read_text(encoding="utf-8")
    hits = parse_search_xml(xml)
    assert all(h.bgg_id != 100000 for h in hits)


def test_parse_search_xml_empty():
    """BGG отдаёт `<items total='0'/>` для пустого результата."""
    hits = parse_search_xml('<?xml version="1.0"?><items total="0"/>')
    assert hits == []


# ---------- client (httpx.MockTransport) ----------

@pytest.mark.asyncio
async def test_client_search_passes_query_and_type():
    """`BggClient.search('Carc')` → GET /search?query=Carc&type=boardgame."""
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        return httpx.Response(200, text=FIXTURE_SEARCH.read_text(encoding="utf-8"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            xml = await bgg.search("Carcassonne")

    assert "Carcassonne" in xml
    req = captured["req"]
    assert req.url.path == "/xmlapi2/search"
    # type=boardgame обязателен — иначе пришли бы аксессуары/допы.
    assert req.url.params["query"] == "Carcassonne"
    assert req.url.params["type"] == "boardgame"
    assert "exact" not in req.url.params


@pytest.mark.asyncio
async def test_client_search_exact_flag():
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        return httpx.Response(200, text='<?xml version="1.0"?><items total="0"/>')

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            await bgg.search("Carcassonne", exact=True)

    assert captured["req"].url.params["exact"] == "1"


@pytest.mark.asyncio
async def test_client_search_raises_on_5xx():
    """5xx от BGG должен пробрасываться как HTTPStatusError — endpoint обернёт его в 502."""
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="Service Unavailable"))
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            with pytest.raises(httpx.HTTPStatusError):
                await bgg.search("anything")


# ---------- service (search_games) ----------

@pytest.mark.asyncio
async def test_search_games_uses_passed_client():
    """`search_games(client=...)` не должен закрывать переданный извне client."""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, text=FIXTURE_SEARCH.read_text(encoding="utf-8"))
    )
    async with httpx.AsyncClient(transport=transport) as http:
        bgg = BggClient(client=http)
        async with bgg:
            hits = await search_games("Carcassonne", limit=2, client=bgg)

    assert len(hits) == 2  # limit обрезает 3 hits до 2
    assert hits[0].bgg_id == 822


@pytest.mark.asyncio
async def test_search_games_default_limit():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, text=FIXTURE_SEARCH.read_text(encoding="utf-8"))
    )
    async with httpx.AsyncClient(transport=transport) as http:
        bgg = BggClient(client=http)
        async with bgg:
            hits = await search_games("Carcassonne", client=bgg)
    # limit=20 default → возвращает все 3 hits.
    assert len(hits) == 3


# ---------- endpoint `POST /parsers/bgg/search` (e2e) ----------

def _make_mocked_bgg_client(handler) -> BggClient:
    """Хелпер: создаёт BggClient с MockTransport вместо реального httpx."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return BggClient(client=http)


@pytest.mark.asyncio
async def test_endpoint_bgg_search():
    """E2E: вызов через FastAPI → возвращает hits, BGG замокан через DI override."""
    from catalog.api import app
    from catalog.routers.parsers import get_bgg_client

    bgg_client = _make_mocked_bgg_client(
        lambda req: httpx.Response(200, text=FIXTURE_SEARCH.read_text(encoding="utf-8"))
    )
    app.dependency_overrides[get_bgg_client] = lambda: bgg_client
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/parsers/bgg/search",
                json={"query": "Carcassonne", "limit": 5},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "Carcassonne"
    assert body["count"] == 3
    assert {h["bgg_id"] for h in body["items"]} == {822, 478, 9217}


@pytest.mark.asyncio
async def test_endpoint_bgg_search_empty_query_validation():
    """Pydantic должен отказать при пустом query (min_length=1)."""
    from catalog.api import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/parsers/bgg/search", json={"query": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_bgg_search_502_on_bgg_error():
    """Если BGG отдаст 503 — endpoint должен ответить 502."""
    from catalog.api import app
    from catalog.routers.parsers import get_bgg_client

    bgg_client = _make_mocked_bgg_client(
        lambda req: httpx.Response(503, text="upstream down")
    )
    app.dependency_overrides[get_bgg_client] = lambda: bgg_client
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/parsers/bgg/search",
                json={"query": "Carcassonne"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 502
    assert "BGG search failed" in resp.json()["detail"]


def test_bgg_base_url_is_xmlapi2():
    """Регрессионный guard: если кто-то случайно укажет xmlapi (без 2) — старый API без stats."""
    assert BGG_BASE_URL.endswith("/xmlapi2")
