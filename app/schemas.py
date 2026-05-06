"""Pydantic v2 схемы ответов API.

ProductOut отражает богатый ответ parsers REST API:
- price_rub (float, рубли) — не копейки
- image_url_hd, description, players, age_min, playtime, rules_url — новые поля
- extra (dict) — store-specific поля (gallery, sku, rating, tags, etc.)
"""

from __future__ import annotations

from pydantic import BaseModel


class StoreOut(BaseModel):
    slug: str
    name: str
    base_url: str


class ProductOut(BaseModel):
    id: int
    store_slug: str
    title: str
    price_rub: float              # рубли (из parsers API)
    url: str
    image_url: str | None = None
    image_url_hd: str | None = None
    description: str | None = None
    players: str | None = None    # "2-5" или null (у HobbyGames нет)
    age_min: int | None = None
    playtime: str | None = None   # "30-45 мин." или null
    rules_url: str | None = None
    fetched_at: str = ""
    extra: dict = {}              # gallery, sku, rating, tags, offline_price, ...


class PricePointOut(BaseModel):
    price: int        # копейки (из /history endpoint)
    price_rub: float  # вычислено: price / 100
    fetched_at: str


class ParserStatsOut(BaseModel):
    slug: str
    name: str
    base_url: str
    # Статус подключения — заполняется при проверке
    available: bool | None = None


class ProductDetailOut(ProductOut):
    observations: list[PricePointOut] = []


class PriceDeltaOut(BaseModel):
    """Дельта между двумя последними точками истории.

    Используется в ResultsTable для колонки «Δ цена», чтобы показать тренд
    без открытия Drawer. None во всех числовых полях — если истории < 2 точек.
    """
    product_id: int
    prev_price_rub: float | None = None
    curr_price_rub: float | None = None
    delta_pct: float | None = None      # положительная — рост, отрицательная — падение
    days_between: float | None = None

