from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query

from .db import PriceDatabase
from .service import PriceService
from .stores.gaga import GagaParser
from .stores.hobbygames import HobbyGamesParser
from .stores.lavkaigr import LavkaIgrParser

# ---------------------------------------------------------------------------
# Инициализация (один раз при старте)
# ---------------------------------------------------------------------------

_db: PriceDatabase
_service: PriceService


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _service

    db_path = os.getenv("DB_PATH", "data/prices.sqlite")
    ttl = float(os.getenv("CACHE_TTL_HOURS", "4"))
    proxy = os.getenv("PROXY")

    _db = PriceDatabase(db_path)
    await _db.init()

    parsers = [
        HobbyGamesParser(proxy=proxy),
        LavkaIgrParser(proxy=proxy),
        GagaParser(proxy=proxy),
    ]

    # Регистрируем магазины в БД
    for p in parsers:
        await _db.upsert_store(p.store)

    _service = PriceService(_db, parsers, cache_ttl_hours=ttl)

    yield  # приложение работает

    # Cleanup при остановке (если нужен)


app = FastAPI(title="Board Game Price Parser", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Маршруты
# ---------------------------------------------------------------------------


@app.get("/stores")
async def list_stores():
    """Список подключённых магазинов."""
    stores = await _service.get_stores()
    return [asdict(s) for s in stores]


@app.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Название игры"),
    refresh: bool = Query(False, description="Принудительно обновить кеш"),
    stores: str | None = Query(None, description="Фильтр по магазинам, через запятую: hobbygames,labirint"),
    limit: int = Query(10, ge=1, le=50),
):
    """Найти игру по названию. Возвращает цены из кеша или свежие данные."""
    store_slugs = [s.strip() for s in stores.split(",")] if stores else None
    try:
        result = await _service.search(q, limit=limit, force_refresh=refresh, store_slugs=store_slugs)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "source": result.source,
        "errors": result.errors,
        "products": [_product_to_dict(p) for p in result.products],
    }


@app.get("/history/{product_id}")
async def price_history(product_id: int):
    """История цен на конкретный товар."""
    points = await _service.get_history(product_id)
    if not points:
        raise HTTPException(status_code=404, detail="Товар не найден или истории нет")
    return [{"price": p.price, "fetched_at": p.fetched_at.isoformat()} for p in points]


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _product_to_dict(p) -> dict:
    return {
        "id": p.id,
        "store_slug": p.store_slug,
        "title": p.title,
        "price_rub": round(p.price / 100, 2),  # копейки → рубли
        "url": p.url,
        "image_url": p.image_url,
        "image_url_hd": p.image_url_hd,
        "description": p.description,
        "players": p.players,
        "age_min": p.age_min,
        "playtime": p.playtime,
        "rules_url": p.rules_url,
        "fetched_at": p.fetched_at.isoformat(),
        # raw содержит gallery, tags, dimensions, rating и т.д.
        "extra": p.raw,
    }
