"""Unit-тесты для CAT-10 HTML browse-парсера.

Фикстура `bgg_browse_2025.html` — уменьшенный snapshot реальной страницы BGG
(4 строки вместо 100). Если BGG поменяет вёрстку, эти тесты упадут первыми —
тогда обновляем фикстуру и поправляем `parse_browse_html`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from catalog.parsers.bgg.browse import BrowseParseError, parse_browse_html

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_browse_html_extracts_rows():
    rows = parse_browse_html(_load("bgg_browse_2025.html"))
    assert len(rows) == 4

    # Ожидаем порядок строк = порядок в HTML (sort=numvoters DESC уже применён BGG).
    assert rows[0].bgg_id == 444444
    assert rows[0].title == "Sample Game One"
    assert rows[0].year == 2025
    assert rows[0].rating == pytest.approx(7.123)

    # Expansion имеет другой path-сегмент /boardgameexpansion/ — он тоже должен парситься.
    assert rows[2].bgg_id == 666666
    assert rows[2].title == "Expansion Pack"
    # «N/A» рейтинг → None (не падаем).
    assert rows[2].rating is None

    # Игра без года в HTML → year=None.
    assert rows[3].bgg_id == 777777
    assert rows[3].year is None


def test_parse_browse_html_raises_on_unexpected_structure():
    # Полностью сломанная страница без таблицы — должен поднять BrowseParseError,
    # чтобы шумно сигнализировать «BGG поменял вёрстку».
    with pytest.raises(BrowseParseError):
        parse_browse_html("<html><body><p>not a browse page</p></body></html>")


def test_parse_browse_html_empty_table_returns_empty():
    # Пустая страница (фильтр без результатов) — НЕ ошибка, просто [].
    empty_html = """
    <html><body>
      <table id="collectionitems">
        <thead><tr><th>Title</th></tr></thead>
        <tbody></tbody>
      </table>
    </body></html>
    """
    assert parse_browse_html(empty_html) == []
