"""BGG-парсер: BoardGameGeek XML API v2.

Документация API: https://boardgamegeek.com/wiki/page/BGG_XML_API2

Архитектура (см. `catalog/parsers/__init__.py`):
- `client.py`     — `BggClient` (rate-limit, 202-backoff, batch до 20 ID)
- `parser.py`     — `parse_thing_xml`, `parse_search_xml` (pure)
- `models.py`     — `BggGame`, `BggSearchHit`
- `repository.py` — `slug_from_title`, upsert (на этапе 2)
- `service.py`    — `search_games`, `enrich_one` (на этапе 2)

Публичное API модуля — через этот __init__: импортить из `catalog.parsers.bgg`,
не из под-модулей напрямую (это даёт стабильную поверхность при рефакторингах).
"""
from __future__ import annotations

from catalog.parsers.bgg.client import BGG_BASE_URL, BggClient, fetch_bgg_thing
from catalog.parsers.bgg.models import (
    BggGame,
    BggGeeklistItem,
    BggGeeklistMeta,
    BggHotnessItem,
    BggSearchHit,
)
from catalog.parsers.bgg.parser import (
    parse_geeklist_xml,
    parse_hot_xml,
    parse_search_xml,
    parse_thing_xml,
)
from catalog.parsers.bgg.repository import slug_from_title, upsert_bgg_data
from catalog.parsers.bgg.service import enrich_one, search_games

# Алиас старого имени — фасад для shim'а в catalog/importers/bgg.py.
parse_bgg_xml = parse_thing_xml

__all__ = [
    "BGG_BASE_URL",
    "BggClient",
    "BggGame",
    "BggGeeklistItem",
    "BggGeeklistMeta",
    "BggHotnessItem",
    "BggSearchHit",
    "enrich_one",
    "fetch_bgg_thing",
    "parse_bgg_xml",  # legacy alias
    "parse_geeklist_xml",
    "parse_hot_xml",
    "parse_search_xml",
    "parse_thing_xml",
    "search_games",
    "slug_from_title",
    "upsert_bgg_data",
]
