"""Dataclasses для распарсенных данных BGG."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BggGame:
    """Распарсенная игра из BGG XML — готова для upsert в catalog.models.Game.

    Соответствует ответу `/xmlapi2/thing?id=<bgg_id>&stats=1`.
    """

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
        """Поля, которые не помещаются в основные колонки → в games.meta (JSONB).

        Используется legacy-роутером `routers/imports.py` (через shim
        `catalog.importers.bgg`). Новый upsert (этап 2) пишет эти поля
        в satellite-таблицу `game_bgg` напрямую.
        """
        return {
            "bgg": {
                "categories": self.categories,
                "mechanics": self.mechanics,
                "rating_avg": self.rating_avg,
                "rating_bayes": self.rating_bayes,
                "thumbnail_url": self.thumbnail_url,
            }
        }


@dataclass
class BggHotnessItem:
    """Одна позиция из ответа BGG `/hot?type=boardgame`.

    BGG hotness — ежедневно обновляемый список 50 «горячих» игр. Содержит
    минимум полей: ранг, id, название, год, thumbnail. Детальные данные
    (описание, механики) — через `/thing?id=<bgg_id>`.
    """

    rank: int
    bgg_id: int
    name: str
    year: int | None = None
    thumbnail_url: str | None = None


@dataclass
class BggSearchHit:
    """Одна позиция в результатах `/xmlapi2/search?query=<q>&type=boardgame`.

    BGG search-endpoint отдаёт минимум полей — только id, primary name и
    год публикации. Для полной карточки нужен повторный запрос
    `/thing?id=<bgg_id>` (см. `BggClient.fetch_thing`).
    """

    bgg_id: int
    title: str
    year: int | None = None
