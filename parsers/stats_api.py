from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .db import PriceDatabase

router = APIRouter()

# db инжектируется из api.py после старта приложения
_db: PriceDatabase


def set_db(db: PriceDatabase) -> None:
    global _db
    _db = db


@router.get("/dashboard", include_in_schema=False)
async def dashboard():
    """HTML-дашборд мониторинга."""
    import pathlib
    html_path = pathlib.Path(__file__).parent / "dashboard.html"
    return FileResponse(html_path, media_type="text/html")


@router.get("/api/stats")
async def stats_summary(hours: int = 24):
    """Сводная статистика запросов к /search за последние N часов."""
    return await _db.get_stats(hours=hours)


@router.get("/api/stats/stores")
async def store_health():
    """Здоровье каждого парсера за последние 24 часа."""
    return await _db.get_store_stats()


@router.get("/api/stats/errors")
async def recent_errors(limit: int = 20):
    """Последние N ошибок парсеров."""
    return await _db.get_recent_errors(limit=limit)


# ---------------------------------------------------------------------------
# Расширенная аналитика
# ---------------------------------------------------------------------------


@router.get("/api/stats/top-queries")
async def top_queries(hours: int = 168, limit: int = 20):
    """Самые популярные поисковые запросы за период."""
    return await _db.get_top_queries(hours=hours, limit=limit)


@router.get("/api/stats/latency")
async def latency_percentiles(hours: int = 24):
    """Перцентили latency (/search): p50, p95, p99, max, avg."""
    return await _db.get_latency_percentiles(hours=hours)


@router.get("/api/stats/timeline")
async def requests_timeline(hours: int = 24, bucket: str = "hour"):
    """Распределение запросов по времени с разбивкой по source.

    bucket: 'hour' или 'day'.
    """
    return await _db.get_requests_timeline(hours=hours, bucket=bucket)


@router.get("/api/stats/cache-timeline")
async def cache_rate_timeline(hours: int = 168, bucket: str = "hour"):
    """Динамика cache hit rate во времени."""
    return await _db.get_cache_rate_timeline(hours=hours, bucket=bucket)


@router.get("/api/stats/store-distribution")
async def store_distribution(hours: int = 24):
    """Распределение нагрузки парсеров по магазинам — для pie/bar chart."""
    return await _db.get_store_distribution(hours=hours)


@router.get("/api/stats/empty-responses")
async def empty_responses(hours: int = 24, limit: int = 50):
    """Успешные вызовы парсеров, вернувшие 0 товаров — 'тихие' сбои."""
    return await _db.get_empty_responses(hours=hours, limit=limit)


@router.get("/api/stats/latency-histogram")
async def latency_histogram(hours: int = 24):
    """Гистограмма распределения latency: бины <100, 100-300, 300-1000, 1000-3000, >3000 мс."""
    return await _db.get_latency_histogram(hours=hours)


@router.get("/api/stats/field-coverage")
async def field_coverage():
    """Покрытие опциональных полей товара per-store (data quality)."""
    return await _db.get_field_coverage()


@router.get("/api/stats/raw-keys")
async def raw_keys(top_n: int = 15):
    """Топ ключей в price_observations.raw_json per-store — фактический контракт парсера."""
    return await _db.get_raw_keys_distribution(top_n=top_n)


@router.get("/api/stats/parser-breakdown")
async def parser_breakdown(hours: int = 24):
    """Per-store разбиение времени parser.search() на search vs enrich + http counter."""
    return await _db.get_parser_breakdown(hours=hours)


@router.get("/api/stats/parser-breakdown-timeline")
async def parser_breakdown_timeline(hours: int = 24, bucket: str = "hour"):
    """Timeline search/enrich latency per-store для line chart."""
    return await _db.get_parser_breakdown_timeline(hours=hours, bucket=bucket)


# ---------------------------------------------------------------------------
# Database Explorer
# ---------------------------------------------------------------------------


@router.get("/api/db/meta")
async def db_meta():
    """Сводка по БД: размер файла, кол-во строк в таблицах, диапазон наблюдений."""
    return await _db.get_db_metadata()


@router.get("/api/db/stores-inventory")
async def db_stores_inventory():
    """Per-store инвентарь: число товаров, наблюдений, диапазон цен и дат."""
    return await _db.get_store_inventory()


@router.get("/api/db/products")
async def db_list_products(
    store: str | None = None,
    q: str | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
):
    """Список товаров с пагинацией и поиском."""
    items, total = await _db.list_products(
        store=store, query=q, sort=sort, limit=limit, offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/api/db/product/{product_id}")
async def db_product(product_id: int):
    """Полная карточка товара + последние 50 точек истории цен."""
    p = await _db.get_product_full(product_id)
    if p is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Товар не найден")
    return p


@router.get("/api/db/price-distribution")
async def db_price_distribution(store: str | None = None):
    """Перцентили цены (в рублях) по последним наблюдениям."""
    return await _db.get_price_distribution(store_slug=store)
