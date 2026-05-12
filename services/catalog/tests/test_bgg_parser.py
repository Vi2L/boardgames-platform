"""Тесты парсера BGG XML — без сети, на статичной фикстуре."""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import pytest

from catalog.importers.bgg import (
    fetch_bgg_thing,
    parse_bgg_xml,
    slug_from_title,
)
from catalog.parsers.bgg.parser import (
    _age_transform,
    _parse_age_poll,
    _parse_lang_dependence_poll,
    _parse_numplayers_poll,
    _poll_winner,
    parse_thing_xml,
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
    # Расширенная статистика (CAT-5) — из <statistics><ratings>.
    assert bgg.users_rated == 118000
    assert bgg.average_weight == 1.89
    assert bgg.num_weights == 24000
    # Polls (CAT-6) — в fixture три poll'а с продуманными граничными случаями.
    assert bgg.recommended_players is not None
    # 3 игрока: Best=250 — это max; 2 игрока: Recommended=200 — best лишь 100.
    assert bgg.recommended_players["3"]["best"] == 250
    assert bgg.recommended_players["6+"]["not_recommended"] == 300
    # suggested_playerage: max numvotes у "8" (120 голосов) → 8.
    assert bgg.recommended_age == 8
    # language_dependence: tie между level=1 и level=2 (по 180 голосов) → min = 1.
    assert bgg.language_dependence == 1


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


# ── helpers: poll-парсеры (CAT-6) ─────────────────────────────────────────────


def test_age_transform_numeric():
    assert _age_transform("8") == 8
    assert _age_transform("12") == 12


def test_age_transform_21_and_up():
    """BGG bucket «21 and up» — храним как нижнюю границу (21)."""
    assert _age_transform("21 and up") == 21


def test_age_transform_invalid():
    assert _age_transform("") is None
    assert _age_transform("xxx") is None


def _make_item(inner: str) -> ET.Element:
    """Хелпер для тестов: парсит фрагмент XML, возвращает <item> элемент."""
    return ET.fromstring(f"<item>{inner}</item>")


def test_poll_winner_basic():
    """Простой случай: max numvotes → этот value."""
    item = _make_item(
        '<poll name="test" totalvotes="100">'
        '<results>'
        '<result value="2" numvotes="30"/>'
        '<result value="3" numvotes="50"/>'
        '<result value="4" numvotes="20"/>'
        '</results></poll>'
    )
    results = item.findall("poll/results/result")
    winner = _poll_winner(results, lambda e: _age_transform(e.attrib.get("value", "")))
    assert winner == 3


def test_poll_winner_tie_resolves_to_min():
    """Tie между двумя значениями → берём меньшее (консервативный выбор)."""
    item = _make_item(
        '<poll name="test" totalvotes="100">'
        '<results>'
        '<result value="2" numvotes="50"/>'
        '<result value="3" numvotes="50"/>'
        '<result value="4" numvotes="20"/>'
        '</results></poll>'
    )
    results = item.findall("poll/results/result")
    winner = _poll_winner(results, lambda e: _age_transform(e.attrib.get("value", "")))
    assert winner == 2


def test_poll_winner_zero_votes():
    """Все numvotes=0 → None."""
    item = _make_item(
        '<poll name="test" totalvotes="0">'
        '<results>'
        '<result value="2" numvotes="0"/>'
        '<result value="3" numvotes="0"/>'
        '</results></poll>'
    )
    results = item.findall("poll/results/result")
    assert _poll_winner(results, lambda e: _age_transform(e.attrib.get("value", ""))) is None


def test_parse_age_poll_totalvotes_zero():
    """totalvotes=0 в poll-атрибуте → None даже если есть результаты."""
    item = _make_item(
        '<poll name="suggested_playerage" totalvotes="0">'
        '<results><result value="8" numvotes="0"/></results>'
        '</poll>'
    )
    assert _parse_age_poll(item) is None


def test_parse_age_poll_missing():
    """Нет poll'а вовсе → None (не падаем)."""
    item = _make_item("<otherstuff/>")
    assert _parse_age_poll(item) is None


def test_parse_lang_dependence_via_level_attr():
    """BGG language_dependence хранит уровень в атрибуте level, не value."""
    item = _make_item(
        '<poll name="language_dependence" totalvotes="100">'
        '<results>'
        '<result level="1" value="No text" numvotes="20"/>'
        '<result level="2" value="Some text" numvotes="60"/>'
        '<result level="3" value="Moderate" numvotes="20"/>'
        '</results></poll>'
    )
    assert _parse_lang_dependence_poll(item) == 2


def test_parse_numplayers_poll_buckets():
    """Сохраняем все per-count подсчёты включая bucket «6+»."""
    item = _make_item(
        '<poll name="suggested_numplayers" totalvotes="100">'
        '<results numplayers="2">'
        '<result value="Best" numvotes="40"/>'
        '<result value="Recommended" numvotes="30"/>'
        '<result value="Not Recommended" numvotes="5"/>'
        '</results>'
        '<results numplayers="6+">'
        '<result value="Best" numvotes="0"/>'
        '<result value="Recommended" numvotes="2"/>'
        '<result value="Not Recommended" numvotes="50"/>'
        '</results>'
        '</poll>'
    )
    out = _parse_numplayers_poll(item)
    assert out is not None
    assert out["2"] == {"best": 40, "recommended": 30, "not_recommended": 5}
    assert out["6+"]["not_recommended"] == 50


def test_parse_numplayers_poll_empty():
    """totalvotes=0 → None (poll не информативен)."""
    item = _make_item(
        '<poll name="suggested_numplayers" totalvotes="0">'
        '<results numplayers="2">'
        '<result value="Best" numvotes="0"/>'
        '</results></poll>'
    )
    assert _parse_numplayers_poll(item) is None


def test_parse_thing_xml_missing_polls_and_stats():
    """Игра без <statistics> и без <poll> — новые поля None, не crash."""
    minimal = """<?xml version="1.0"?>
<items>
  <item type="boardgame" id="999">
    <name type="primary" value="Test Game"/>
  </item>
</items>"""
    bgg = parse_thing_xml(minimal)
    assert bgg is not None
    assert bgg.users_rated is None
    assert bgg.average_weight is None
    assert bgg.num_weights is None
    assert bgg.recommended_players is None
    assert bgg.recommended_age is None
    assert bgg.language_dependence is None
