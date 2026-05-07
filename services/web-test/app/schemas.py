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


class PriceStatsOut(BaseModel):
    """Агрегаты цены по истории — min за 30 дней и за всё время.

    Считается по тем же точкам price_observations, что и /history. None,
    если истории нет (товар увидели впервые в этом запуске).
    """
    product_id: int
    min_30d_rub: float | None = None
    min_all_rub: float | None = None
    points_30d: int = 0
    points_all: int = 0


# ── DatabasePage схемы (фаза 3) ─────────────────────────────────────────────

class ProductsPage(BaseModel):
    """Пагинированный ответ для /api/db/products."""
    items: list[ProductOut]
    total: int
    page: int
    page_size: int


class SearchLogOut(BaseModel):
    """Запись из local_searches: запрос, прошедший через портал."""
    id: int
    query: str
    stores: str | None
    source: str | None
    total_ms: int | None
    products_count: int
    error_count: int
    errors_json: str
    created_at: str


class SearchesPage(BaseModel):
    items: list[SearchLogOut]
    total: int
    page: int
    page_size: int


# ── Snapshots / Suites / Favorites (фаза 4) ─────────────────────────────────

class SnapshotCreate(BaseModel):
    """POST /api/snapshots — параметры сохраняемого прогона."""
    name: str | None = None
    query: str
    stores: list[str] | None = None
    limit: int = 10
    refresh: bool = False


class SnapshotMeta(BaseModel):
    """Краткая запись для списка."""
    id: int
    name: str | None
    query: str
    stores: str | None
    limit_n: int
    refresh: bool
    source: str | None
    total_ms: int | None
    error_count: int
    summary: dict
    created_at: str


class SnapshotsPage(BaseModel):
    items: list[SnapshotMeta]
    total: int
    page: int
    page_size: int


class FavoriteIn(BaseModel):
    query: str
    stores: list[str] | None = None
    limit: int | None = None
    refresh: bool = False
    # Доп. UI-настройки (фильтр out-of-stock, конфиг лояльности).
    # Хранятся opaque-JSON-ом в одной колонке БД, чтобы не плодить миграций.
    show_out_of_stock: bool | None = None
    loyalty: dict | None = None


class FavoriteOut(BaseModel):
    id: int
    query: str
    stores: str | None
    limit_n: int | None
    refresh: bool
    created_at: str
    show_out_of_stock: bool | None = None
    loyalty: dict | None = None


class SuiteQuery(BaseModel):
    """Один пункт test-сьюта — параметры одного прогона search."""
    q: str
    stores: list[str] | None = None
    limit: int | None = None
    refresh: bool = False


class SuiteIn(BaseModel):
    name: str
    description: str | None = None
    queries: list[SuiteQuery]


class SuiteOut(BaseModel):
    id: int
    name: str
    description: str | None
    queries: list[SuiteQuery]
    created_at: str
    updated_at: str


class SuiteRunMeta(BaseModel):
    id: int
    suite_id: int
    started_at: str
    finished_at: str | None
    summary: dict


class SuiteRunItem(BaseModel):
    id: int
    query: str
    snapshot_id: int | None
    ms: int | None
    status: str
    error: str | None


class SuiteRunDetail(SuiteRunMeta):
    items: list[SuiteRunItem]

