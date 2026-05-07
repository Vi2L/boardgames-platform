"""Импорт настольных игр из BoardGameGeek XML API v2.

Документация API: https://boardgamegeek.com/wiki/page/BGG_XML_API2

Архитектура:
- `fetch_bgg_thing` — чистая HTTP-функция, легко мокается через httpx.MockTransport.
- `parse_bgg_xml` — pure-функция парсинга, тестируется на фикстуре без сети.
- `import_bgg_to_db` — оркестратор: fetch → parse → upsert в games.

Особенности BGG API:
- Endpoint: GET /xmlapi2/thing?id={id}&stats=1
- Возвращает иногда 202 Accepted (queued) — нужно повторить через несколько секунд.
- Множество <name>, тип `primary` — каноническое название, `alternate` — алиасы.
- Designers / publishers — `<link type="boardgamedesigner" .../>`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

import httpx

BGG_BASE_URL = "https://boardgamegeek.com/xmlapi2"
# 202 Accepted = «запрос принят, попробуйте снова». Стандартный паттерн BGG.
_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0)


@dataclass
class BggGame:
    """Распарсенная игра из BGG XML — готова для upsert в catalog.models.Game."""

    bgg_id: int
    title: str  # primary name
    aliases: list[str] = field(default_factory=list)  # alternate names
    year: int | None = None
    description: str | None = None
    cover_url: str | None = None
    thumbnail_url: str | None = None
    designers: list[str] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    players_min: int | None = None
    players_max: int | None = None
    playtime_min: int | None = None
    playtime_max: int | None = None
    age_min: int | None = None
    categories: list[str] = field(default_factory=list)
    mechanics: list[str] = field(default_factory=list)
    rating_avg: float | None = None
    rating_bayes: float | None = None

    def to_meta(self) -> dict[str, Any]:
        """Поля, которые не помещаются в основные колонки → в games.meta (JSONB)."""
        return {
            "bgg": {
                "categories": self.categories,
                "mechanics": self.mechanics,
                "rating_avg": self.rating_avg,
                "rating_bayes": self.rating_bayes,
                "thumbnail_url": self.thumbnail_url,
            }
        }


def _int_attr(elem: ET.Element | None, attr: str = "value") -> int | None:
    if elem is None:
        return None
    val = elem.attrib.get(attr)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _float_attr(elem: ET.Element | None, attr: str = "value") -> float | None:
    if elem is None:
        return None
    val = elem.attrib.get(attr)
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def parse_bgg_xml(xml_text: str) -> BggGame | None:
    """Парсит ответ BGG XML API на запрос /thing?id=X.

    Возвращает None, если игры с таким id нет (BGG отдаёт пустой <items/>).
    """
    root = ET.fromstring(xml_text)
    item = root.find("item")
    if item is None:
        return None

    bgg_id = int(item.attrib["id"])

    # Имена: одно primary + N alternate.
    primary_name = ""
    aliases: list[str] = []
    for name_el in item.findall("name"):
        if name_el.attrib.get("type") == "primary":
            primary_name = name_el.attrib.get("value", "")
        else:
            alt = name_el.attrib.get("value")
            if alt:
                aliases.append(alt)

    # Линки: designers/publishers/categories/mechanics — все через <link type="...">.
    designers: list[str] = []
    publishers: list[str] = []
    categories: list[str] = []
    mechanics: list[str] = []
    for link in item.findall("link"):
        ltype = link.attrib.get("type")
        value = link.attrib.get("value", "")
        if ltype == "boardgamedesigner":
            designers.append(value)
        elif ltype == "boardgamepublisher":
            publishers.append(value)
        elif ltype == "boardgamecategory":
            categories.append(value)
        elif ltype == "boardgamemechanic":
            mechanics.append(value)

    description = None
    desc_el = item.find("description")
    if desc_el is not None and desc_el.text:
        description = desc_el.text

    image_el = item.find("image")
    thumb_el = item.find("thumbnail")

    # Статистика — внутри <statistics><ratings>...
    stats = item.find("statistics/ratings")
    rating_avg = _float_attr(stats.find("average") if stats is not None else None)
    rating_bayes = _float_attr(stats.find("bayesaverage") if stats is not None else None)

    return BggGame(
        bgg_id=bgg_id,
        title=primary_name,
        aliases=aliases,
        year=_int_attr(item.find("yearpublished")),
        description=description,
        cover_url=image_el.text if image_el is not None and image_el.text else None,
        thumbnail_url=thumb_el.text if thumb_el is not None and thumb_el.text else None,
        designers=designers,
        publishers=publishers,
        players_min=_int_attr(item.find("minplayers")),
        players_max=_int_attr(item.find("maxplayers")),
        playtime_min=_int_attr(item.find("minplaytime")),
        playtime_max=_int_attr(item.find("maxplaytime")),
        age_min=_int_attr(item.find("minage")),
        categories=categories,
        mechanics=mechanics,
        rating_avg=rating_avg,
        rating_bayes=rating_bayes,
    )


async def fetch_bgg_thing(
    bgg_id: int, client: httpx.AsyncClient | None = None
) -> str:
    """Скачивает XML по bgg_id. Обрабатывает 202 Accepted с экспоненциальным backoff."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        url = f"{BGG_BASE_URL}/thing"
        params = {"id": bgg_id, "stats": 1}
        for delay in _RETRY_DELAYS:
            assert client is not None
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return response.text
            if response.status_code == 202:
                # BGG прогревает кеш — ждём и пробуем снова.
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
        raise httpx.HTTPError(f"BGG не отдал данные за {len(_RETRY_DELAYS)} попыток")
    finally:
        if own_client and client is not None:
            await client.aclose()


def slug_from_title(title: str, bgg_id: int) -> str:
    """Генерируем slug из английского названия + bgg_id (на случай коллизий).

    Slug должен подходить под regex `^[a-z0-9][a-z0-9\\-]*$` (см. GameCreate.slug).
    """
    import re
    base = title.lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    if not base or not base[0].isalnum():
        base = f"game-{bgg_id}"
    return f"{base}-{bgg_id}"
