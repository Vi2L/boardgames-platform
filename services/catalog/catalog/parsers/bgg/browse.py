"""CAT-10: парсер HTML страниц `boardgamegeek.com/browse/boardgame`.

BGG XML API не отдаёт фильтр по `yearpublished` с сортировкой по `numvoters`,
а это два главных сигнала для отбора «новинок года» (свежие + получили внимание
сообщества). Решение — HTML-скрейп browse-страниц через BeautifulSoup.

Структура страницы (на 2026-05):
- `<table id="collectionitems">` — главная таблица.
- `<tr id="row_">` — одна строка на игру.
- В строке: thing-id из `<a href="/boardgame/X/...">`, title, year, rating
  из колонки `collection_bggrating` (или `collection_rating`).

Хрупкость: вёрстка BGG может измениться. Защита — фикстура HTML-снэпшота
в тестах + явный сигнал ParseError если структура поломалась (а не silent empty).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag


class BrowseParseError(Exception):
    """Парсер не нашёл ожидаемых элементов — вёрстка BGG, скорее всего, изменилась.

    Поднимается с понятным message, чтобы оператор мог быстро диагностировать.
    Не глотать «тихо» — пустая выдача из browse-страницы это всегда баг.
    """


@dataclass(slots=True)
class BrowseRow:
    """Одна строка с browse-страницы: thing-id + минимум данных для дедупликации.

    Дальнейшее обогащение идёт через стандартный `enrich_one(bgg_id)` — год/название
    из browse-страницы носят только информационный характер, BGG XML API даст
    канонические значения.
    """
    bgg_id: int
    title: str
    year: int | None
    rating: float | None


_HREF_RE = re.compile(r"^/boardgame(?:expansion|accessory)?/(\d+)/")
_YEAR_RE = re.compile(r"\((\d{4})\)")


def parse_browse_html(html: str) -> list[BrowseRow]:
    """Извлекает список игр со страницы browse.

    Идемпотентность дубликатов — на caller'е (cмежные страницы могут пересекаться
    в редких случаях; обычно нет, но мы не полагаемся).

    Поднимает `BrowseParseError`, если не нашли ключевые элементы — лучше упасть
    с диагностикой, чем молча вернуть `[]` и не заметить сломанный парсер.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Таблица может быть `collectionitems` или похожий id; ищем по наличию
    # строк `row_*`. Берём первую такую таблицу.
    rows = soup.select("tr[id^='row_']")
    if not rows:
        # Не падаем сразу — может быть пустая страница (yearpublished = далёкое
        # будущее или фильтр без результатов). Но проверим, что таблица вообще
        # существует — иначе это сломанная вёрстка.
        if soup.find("table", id="collectionitems") is None:
            raise BrowseParseError(
                "browse-страница не содержит <table id='collectionitems'> — "
                "вёрстка BGG могла измениться"
            )
        return []

    out: list[BrowseRow] = []
    for row in rows:
        item = _parse_row(row)
        if item is not None:
            out.append(item)
    return out


def _parse_row(row: Tag) -> BrowseRow | None:
    """Один <tr> → BrowseRow. None если в строке нет ссылки на /boardgame/."""
    # Сначала ищем primary-ссылку (текстовая, в `collection_objectname`).
    # Thumbnail-ссылка имеет тот же href, но `get_text() == ''` — её title не даст.
    candidates = row.find_all("a", href=_HREF_RE)
    link: Tag | None = None
    for c in candidates:
        if isinstance(c, Tag) and c.get_text(strip=True):
            link = c
            break
    if link is None:
        return None
    href = link.get("href", "")
    m = _HREF_RE.match(href if isinstance(href, str) else "")
    if not m:
        return None
    bgg_id = int(m.group(1))

    title = link.get_text(strip=True)

    # Год — отдельный <span> рядом с заголовком: «Caverna (2013)». Иногда
    # стилизуется как `.smallerfont.dull`. Регекс по тексту строки берёт его
    # независимо от классов CSS.
    year: int | None = None
    title_cell = link.find_parent("td")
    if isinstance(title_cell, Tag):
        cell_text = title_cell.get_text(" ", strip=True)
        ym = _YEAR_RE.search(cell_text)
        if ym:
            year = int(ym.group(1))

    # Rating — колонка `collection_bggrating` (geek rating, bayes-сглажен).
    rating: float | None = None
    rating_cell = row.find("td", class_="collection_bggrating")
    if isinstance(rating_cell, Tag):
        txt = rating_cell.get_text(strip=True)
        try:
            rating = float(txt)
        except ValueError:
            rating = None  # «N/A» или пусто — для нашей задачи не критично

    return BrowseRow(bgg_id=bgg_id, title=title, year=year, rating=rating)
