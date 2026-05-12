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
    # Расширенная статистика из <statistics><ratings> (CAT-5). XML — источник
    # истины: при upsert эти значения перетирают то, что пришло из CSV-выгрузки
    # (BGG ranks CSV отстаёт от XML на неделю).
    users_rated: int | None = None
    average_weight: float | None = None  # complexity 1.00–5.00
    num_weights: int | None = None
    # BGG `<poll>` — рекомендации сообщества (CAT-6). recommended_players держит
    # raw-подсчёты per player count: {"1": {best, recommended, not_recommended}, ...}
    # включая bucket "6+". Это позволяет фронту самому решать, как агрегировать
    # (best ≥ recommended ≥ not_recommended, etc.).
    recommended_players: dict[str, dict[str, int]] | None = None
    # winning value среди poll-результатов; tie → меньшее. "21 and up" → 21.
    # None если у poll нет голосов (totalvotes=0 или сумма numvotes=0).
    recommended_age: int | None = None
    # 1 (no in-game text) ... 5 (unplayable in foreign language); winning level.
    language_dependence: int | None = None

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
class BggGeeklistItem:
    """Одна позиция из BGG GeekList (`/xmlapi2/geeklist/{id}`).

    BGG возвращает `<item>` с атрибутами objectid (=bgg_id), objectname (=name)
    и опциональным дочерним `<body>` (комментарий куратора). Thumbnail и year
    в endpoint'е НЕ приходят — нужно отдельно `/thing?id=X` (это делает
    auto-import после snapshot'а).

    rank — позиция в списке (1-based), считается по порядку appearance в XML.
    Для «Top 50 Most Played» этот порядок и есть искомый ранг.
    """

    rank: int
    bgg_id: int
    name: str
    body: str | None = None


@dataclass
class BggGeeklistMeta:
    """Header GeekList'а: title, description, owner, item_count.

    Парсится из root `<geeklist>` элемента вместе с items на одном XML pass.
    """

    geeklist_id: int
    title: str | None
    description: str | None
    username: str | None
    item_count: int


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
