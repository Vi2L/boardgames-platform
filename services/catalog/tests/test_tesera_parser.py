"""Тесты парсера Tesera JSON — без сети."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from catalog.importers.tesera import (
    fetch_tesera_thing,
    parse_tesera_json,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tesera_carcassonne.json"


def test_parse_tesera_basic():
    tg = parse_tesera_json(FIXTURE.read_text(encoding="utf-8"))
    assert tg is not None
    assert tg.tesera_id == 822
    assert tg.alias == "carcassonne"
    # title2 (ru) приоритетнее title (en).
    assert tg.title == "Каркассон"
    assert tg.title_en == "Carcassonne"
    assert "Carcassonne" in tg.aliases
    assert tg.year == 2000
    assert tg.players_min == 2
    assert tg.players_max == 5
    assert tg.playtime_min == 30
    assert tg.playtime_max == 45
    assert tg.age_min == 7
    assert tg.rating_user == 8.1
    assert tg.cover_url and tg.cover_url.startswith("https://")


def test_parse_tesera_without_wrapper():
    """API иногда отдаёт объект без обёртки `game`."""
    raw = '{"id": 1, "alias": "x", "title": "X"}'
    tg = parse_tesera_json(raw)
    assert tg is not None
    assert tg.tesera_id == 1
    assert tg.title == "X"


def test_parse_tesera_empty():
    assert parse_tesera_json("{}") is None
    assert parse_tesera_json('{"game": null}') is None


@pytest.mark.asyncio
async def test_fetch_with_mock_transport():
    fixture = FIXTURE.read_text(encoding="utf-8")
    seen_url = {"url": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_url["url"] = str(request.url)
        return httpx.Response(200, text=fixture)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        text = await fetch_tesera_thing("carcassonne", client=client)
    assert "carcassonne" in seen_url["url"]
    assert "Каркассон" in text
