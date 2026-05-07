"""Импорт настольных игр с tesera.ru.

API: https://api.tesera.ru/help — JSON-эндпоинты.
- GET /games/{alias}  — детали игры по slug'у (canonical способ)
- GET /games/{id}     — также работает по числовому id

Tesera-специфика:
- `title` — английское/оригинальное название, `title2` — русское.
  Для каталога мы делаем `title2 || title` основным (приоритет ru-локали).
- `alias` — slug на сайте Tesera, удобен для повторного импорта.
- Метаданные о механиках/категориях возвращаются другими endpoint'ами;
  для этапа 4 ограничимся базовыми полями + рейтингом.

Архитектура повторяет catalog.importers.bgg (fetch / parse / upsert),
чтобы тестируемость и инжект моков были одинаковыми.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

TESERA_BASE_URL = "https://api.tesera.ru"


@dataclass
class TeseraGame:
    tesera_id: int
    alias: str
    title: str  # приоритет: title2 (ru) > title (en)
    title_en: str | None = None  # title из API, если был передан title2
    aliases: list[str] = field(default_factory=list)
    year: int | None = None
    description: str | None = None
    cover_url: str | None = None
    players_min: int | None = None
    players_max: int | None = None
    playtime_min: int | None = None
    playtime_max: int | None = None
    age_min: int | None = None
    rating_user: float | None = None
    rating_tesera: float | None = None

    def to_meta(self) -> dict[str, Any]:
        return {
            "tesera": {
                "alias": self.alias,
                "title_en": self.title_en,
                "rating_user": self.rating_user,
                "rating_tesera": self.rating_tesera,
            }
        }


def _opt_int(v: Any) -> int | None:
    if v is None or v == 0 or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_float(v: Any) -> float | None:
    if v is None or v == 0 or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_tesera_json(payload: str | dict[str, Any]) -> TeseraGame | None:
    """Парсит ответ Tesera /games/{alias} в TeseraGame.

    API иногда оборачивает игру в `{"game": {...}}`, иногда отдаёт объект
    напрямую — обрабатываем оба случая.
    """
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not data:
        return None
    game = data.get("game", data) if isinstance(data, dict) else None
    if not game or not game.get("id"):
        return None

    title_en = _opt_str(game.get("title"))
    title_ru = _opt_str(game.get("title2"))
    primary = title_ru or title_en or ""
    if not primary:
        return None

    aliases: list[str] = []
    if title_ru and title_en and title_ru != title_en:
        aliases.append(title_en)

    return TeseraGame(
        tesera_id=int(game["id"]),
        alias=str(game.get("alias", "")),
        title=primary,
        title_en=title_en if title_ru else None,
        aliases=aliases,
        year=_opt_int(game.get("year")),
        description=_opt_str(game.get("descriptionShort") or game.get("description")),
        cover_url=_opt_str(game.get("photoUrl")),
        players_min=_opt_int(game.get("playersMin")),
        players_max=_opt_int(game.get("playersMax")),
        playtime_min=_opt_int(game.get("playtimeMin")),
        playtime_max=_opt_int(game.get("playtimeMax")),
        age_min=_opt_int(game.get("playersAgeMin") or game.get("agePlayers")),
        rating_user=_opt_float(game.get("ratingUser")),
        rating_tesera=_opt_float(game.get("ratingTesera")),
    )


async def fetch_tesera_thing(
    alias_or_id: str | int, client: httpx.AsyncClient | None = None
) -> str:
    """GET /games/{alias_or_id}. Возвращает сырой JSON-текст."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        assert client is not None
        url = f"{TESERA_BASE_URL}/games/{alias_or_id}"
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    finally:
        if own_client and client is not None:
            await client.aclose()
