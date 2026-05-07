"""Тесты pure-парсера entity-payload Wikidata. Без сети."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalog.wikidata import (
    WikidataError,
    _entity_sort_key,
    parse_entity,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "wikidata_carcassonne.json"
).read_text(encoding="utf-8")


def test_parse_entity_carcassonne():
    payload = json.loads(FIXTURE)
    e = parse_entity(payload, "Q17262", ["Q17262"], languages=["ru", "en"])

    assert e.found is True
    assert e.entity_id == "Q17262"
    assert e.labels == {"ru": "Каркассон", "en": "Carcassonne"}
    assert e.descriptions["ru"] == "немецкая настольная игра"
    assert e.descriptions["en"].startswith("tile-based")
    # Aliases — массив, порядок сохраняется.
    assert "Каркасон" in e.aliases["ru"]
    assert "Каркассон (настольная игра)" in e.aliases["ru"]
    assert e.aliases["en"] == ["Carcassonne (board game)"]
    # P2339 (BGG ID).
    assert e.bgg_ids == ["822"]
    # raw содержит meta — для аудита.
    assert e.raw["title"] == "Q17262"
    assert e.raw["pageid"] == 18925


def test_parse_entity_only_requested_languages():
    """Не вытягиваем языки, которых не просили (de отсутствует в результате)."""
    payload = json.loads(FIXTURE)
    e = parse_entity(payload, "Q17262", ["Q17262"], languages=["ru"])
    assert "de" not in e.labels
    assert "en" not in e.labels
    assert e.labels == {"ru": "Каркассон"}


def test_parse_entity_missing_id_raises():
    payload = {"entities": {}}
    with pytest.raises(WikidataError):
        parse_entity(payload, "Q1", [], languages=["ru"])


def test_parse_entity_no_aliases_for_lang():
    """Если для запрошенного языка нет aliases — ключ отсутствует, не пустой массив."""
    payload = {
        "entities": {
            "Q1": {
                "labels": {"en": {"value": "X"}},
                "aliases": {"en": [{"value": "Y"}]},
                "descriptions": {},
                "claims": {},
            }
        }
    }
    e = parse_entity(payload, "Q1", ["Q1"], languages=["ru", "en"])
    assert "ru" not in e.aliases  # пустой не записываем
    assert e.aliases["en"] == ["Y"]


def test_entity_sort_key():
    """Q-id сортируются по числу: Q5 < Q100 < Q9999."""
    assert _entity_sort_key("Q5") < _entity_sort_key("Q100")
    assert _entity_sort_key("Q100") < _entity_sort_key("Q9999")
    # Невалидный — в конец.
    assert _entity_sort_key("garbage") > _entity_sort_key("Q9999999")
