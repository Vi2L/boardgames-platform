"""Тесты парсера BGG XML — без сети, на статичной фикстуре."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from catalog.importers.bgg import (
    fetch_bgg_thing,
    parse_bgg_xml,
    slug_from_title,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bgg_carcassonne.xml"


def test_parse_bgg_xml_carcassonne():
    xml = FIXTURE.read_text(encoding="utf-8")
    bgg = parse_bgg_xml(xml)
    assert bgg is not None
    assert bgg.bgg_id == 822
    assert bgg.title == "Carcassonne"
    assert "Каркассон" in bgg.aliases
    assert bgg.year == 2000
    assert bgg.players_min == 2
    assert bgg.players_max == 5
    assert bgg.playtime_min == 30
    assert bgg.playtime_max == 45
    assert bgg.age_min == 7
    assert "Klaus-Jürgen Wrede" in bgg.designers
    assert "Hans im Glück" in bgg.publishers
    assert "City Building" in bgg.categories
    assert "Tile Placement" in bgg.mechanics
    assert bgg.rating_avg == 7.42
    assert bgg.rating_bayes == 7.32
    assert bgg.cover_url and bgg.cover_url.startswith("https://")


def test_parse_empty_response():
    """BGG отдаёт пустой <items/> для несуществующих id."""
    bgg = parse_bgg_xml('<?xml version="1.0"?><items/>')
    assert bgg is None


def test_slug_generation():
    assert slug_from_title("Carcassonne", 822) == "carcassonne-822"
    assert slug_from_title("7 Wonders Duel", 173346) == "7-wonders-duel-173346"
    # Кириллица слетает в дефис, остаётся только bgg_id-фоллбэк.
    assert slug_from_title("Каркассон", 822).endswith("-822")


@pytest.mark.asyncio
async def test_fetch_bgg_with_mock_transport():
    """Имитируем 202→200 retry-сценарий."""
    fixture_xml = FIXTURE.read_text(encoding="utf-8")
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(202, text="queued")
        return httpx.Response(200, text=fixture_xml)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # Ускоряем тест: monkeypatch не нужен — _RETRY_DELAYS первый = 1с.
        # Для unit-теста этого достаточно, но лучше подменить sleep.
        import catalog.importers.bgg as bgg_mod

        original = bgg_mod._RETRY_DELAYS
        bgg_mod._RETRY_DELAYS = (0.0, 0.0, 0.0, 0.0)
        try:
            xml = await fetch_bgg_thing(822, client=client)
        finally:
            bgg_mod._RETRY_DELAYS = original

    assert call_count["n"] == 2
    assert "Carcassonne" in xml
