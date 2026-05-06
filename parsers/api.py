from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

from .db import PriceDatabase
from .service import PriceService
from .stats_api import router as stats_router
from .stats_api import set_db as stats_set_db
from .stores.crowdgames import CrowdGamesParser
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
        CrowdGamesParser(proxy=proxy),
    ]

    # Регистрируем магазины в БД и подмешиваем _db для SnapshotRecorder.
    # Парсер не зависит от БД для базовой работы; _db нужен только при
    # ENABLE_RAW_SNAPSHOTS=1, иначе остаётся неиспользованным.
    for p in parsers:
        await _db.upsert_store(p.store)
        p._db = _db

    _service = PriceService(_db, parsers, cache_ttl_hours=ttl)
    stats_set_db(_db)

    yield  # приложение работает

    # Cleanup при остановке (если нужен)


app = FastAPI(title="Board Game Price Parser", lifespan=lifespan)
app.include_router(stats_router)

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


def _parsed_product_to_dict_full(p) -> dict:
    """Сериализатор ParsedProduct прямо из парсера (минуя БД).

    Отдаёт оба формата цены: price (копейки) для отладки и price_rub (рубли)
    для удобства чтения.
    """
    return {
        "store_slug": p.store_slug,
        "external_id": p.external_id,
        "title": p.title,
        "price": p.price,  # копейки — сырое значение из парсера
        "price_rub": round(p.price / 100, 2),
        "url": p.url,
        "image_url": p.image_url,
        "image_url_hd": p.image_url_hd,
        "description": p.description,
        "players": p.players,
        "age_min": p.age_min,
        "playtime": p.playtime,
        "rules_url": p.rules_url,
        "raw": p.raw,
    }


# ---------------------------------------------------------------------------
# Live Test — диагностический endpoint мимо кеша
# ---------------------------------------------------------------------------


@app.get("/api/debug/parse")
async def debug_parse(
    q: str = Query(..., min_length=1, description="Запрос для парсера"),
    stores: str | None = Query(None, description="Фильтр по магазинам через запятую"),
    limit: int = Query(5, ge=1, le=20),
):
    """Запустить парсеры мимо кеша и вернуть сырые ParsedProduct + метрики.

    В отличие от /search этот endpoint:
    - НЕ читает кеш
    - НЕ сохраняет товары в products / price_observations
    - НЕ пишет в request_log
    - В parser_log пишет с is_test=1 — все аналитические запросы это исключают
    """
    target_slugs = (
        [s.strip() for s in stores.split(",")] if stores else list(_service._parsers)
    )

    async def _run(slug: str):
        parser = _service._parsers.get(slug)
        if parser is None:
            return slug, {"error": f"unknown store: {slug}", "products": [], "count": 0}
        t0 = time.monotonic()
        try:
            products = await parser.search(q, limit=limit)
            elapsed = int((time.monotonic() - t0) * 1000)
            metrics = getattr(parser, "last_metrics", None)
            # await, не create_task — диагностический endpoint, доли мс не важны,
            # зато гарантия записи (важно для тестов и для отладки самих логов)
            await _db.log_parser(
                store_slug=slug, success=True, result_count=len(products),
                duration_ms=elapsed, error_msg=None,
                ts=datetime.now(timezone.utc).isoformat(),
                search_ms=metrics.search_ms if metrics else None,
                enrich_ms=metrics.enrich_ms if metrics else None,
                http_requests=metrics.http_requests if metrics else None,
                result_after_enrich=metrics.result_after_enrich if metrics else None,
                is_test=True,
            )
            return slug, {
                "products": [_parsed_product_to_dict_full(p) for p in products],
                "count": len(products),
                "duration_ms": elapsed,
                "metrics": asdict(metrics) if metrics else None,
                "error": None,
            }
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            await _db.log_parser(
                store_slug=slug, success=False, result_count=0,
                duration_ms=elapsed, error_msg=str(e),
                ts=datetime.now(timezone.utc).isoformat(),
                is_test=True,
            )
            return slug, {
                "products": [], "count": 0,
                "duration_ms": elapsed,
                "metrics": None, "error": str(e),
            }

    results = await asyncio.gather(*[_run(s) for s in target_slugs])
    return {"query": q, "results": dict(results)}
