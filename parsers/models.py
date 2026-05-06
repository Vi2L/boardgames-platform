from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class StoreInfo:
    slug: str       # уникальный идентификатор магазина, e.g. "hobbygames"
    name: str       # человекочитаемое название
    base_url: str


@dataclass(frozen=True)
class ParsedProduct:
    """Товар, полученный из парсера (поиск + обогащение страницей товара)."""
    store_slug: str
    external_id: str  # ID или slug товара на стороне магазина
    title: str
    price: int        # в копейках: 1990 руб. = 199000 коп.
    url: str
    image_url: str | None = None       # thumbnail со страницы поиска
    # --- поля со страницы товара ---
    image_url_hd: str | None = None    # главное изображение высокого разрешения
    description: str | None = None     # описание игры
    players: str | None = None         # кол-во игроков, e.g. "2-5"
    age_min: int | None = None         # минимальный возраст, e.g. 8
    playtime: str | None = None        # время партии, e.g. "30-45 мин"
    rules_url: str | None = None       # ссылка на основной PDF правил
    raw: dict = field(default_factory=dict)  # gallery, tags, dimensions и т.д.


@dataclass
class ProductRecord:
    """Товар из БД с последней известной ценой."""
    id: int
    store_slug: str
    external_id: str
    title: str
    price: int        # в копейках
    url: str
    fetched_at: datetime
    image_url: str | None = None
    image_url_hd: str | None = None
    description: str | None = None
    players: str | None = None
    age_min: int | None = None
    playtime: str | None = None
    rules_url: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PricePoint:
    """Одна точка истории цен."""
    price: int       # в копейках
    fetched_at: datetime


@dataclass
class SearchResult:
    products: list[ProductRecord]
    # "cache"         — все магазины свежие, сеть не трогали
    # "network"       — хотя бы один магазин обновился по сети
    # "partial-cache" — все магазины упали, вернули устаревший кеш
    source: str
    errors: dict[str, str] = field(default_factory=dict)  # slug → текст ошибки
