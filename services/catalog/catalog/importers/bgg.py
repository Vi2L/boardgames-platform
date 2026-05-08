"""Re-export shim для обратной совместимости.

Реализация BGG-парсера переехала в `catalog/parsers/bgg/` — см. план
`~/.claude/plans/modular-knitting-sloth.md`. Этот файл сохранён, чтобы
не ломать импорты в:
- `catalog/routers/imports.py` (POST /import/bgg)
- `catalog/scripts/import_bgg_ranks.py` (slug)
- `tests/test_bgg_parser.py` (обращается к `_RETRY_DELAYS` для теста ретраев)

Новый код должен импортить из `catalog.parsers.bgg`.

Когда все потребители переключатся на новый путь, файл будет удалён.
"""
from __future__ import annotations

from catalog.parsers.bgg import (
    BGG_BASE_URL,
    BggClient,
    BggGame,
    BggSearchHit,
    fetch_bgg_thing,
    parse_bgg_xml,
    parse_search_xml,
    parse_thing_xml,
    search_games,
    slug_from_title,
)

# `_RETRY_DELAYS` живёт в client.py — re-export по старому имени для тестов,
# которые подменяют его через monkeypatch (см. `tests/test_bgg_parser.py`).
from catalog.parsers.bgg import client as _bgg_client_module


def __getattr__(name: str) -> object:
    """Делегирует `_RETRY_DELAYS` к источнику в `parsers.bgg.client`.

    Тесты, которые подменяют `_RETRY_DELAYS`, должны делать это на модуле-
    источнике (`catalog.parsers.bgg.client._RETRY_DELAYS = ...`), потому
    что CPython не вызывает module-level `__setattr__` — простое
    `bgg_mod._RETRY_DELAYS = (0,...)` создаст локальный атрибут в shim'е,
    а реальный `_fetch_thing_url` его не увидит.
    """
    if name == "_RETRY_DELAYS":
        return _bgg_client_module._RETRY_DELAYS
    raise AttributeError(f"module 'catalog.importers.bgg' has no attribute {name!r}")


__all__ = [
    "BGG_BASE_URL",
    "BggClient",
    "BggGame",
    "BggSearchHit",
    "fetch_bgg_thing",
    "parse_bgg_xml",
    "parse_search_xml",
    "parse_thing_xml",
    "search_games",
    "slug_from_title",
]
