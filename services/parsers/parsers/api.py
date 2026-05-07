from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

from .catalog_publisher import CatalogPublisher
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
_catalog_publisher: CatalogPublisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _service, _catalog_publisher

    db_path = os.getenv("DB_PATH", "data/prices.sqlite")
    ttl = float(os.getenv("CACHE_TTL_HOURS", "4"))
    proxy = os.getenv("PROXY")

    _db = PriceDatabase(db_path)
    await _db.init()

    # Опциональный publisher оффер'ов в boardgames-catalog. Если URL не задан —
    # no-op, search работает как раньше. Подключение из infra-репо:
    # CATALOG_INGEST_URL=http://catalog:8002/ingest/offers
    _catalog_publisher = CatalogPublisher(
        url=os.getenv("CATALOG_INGEST_URL"),
        api_key=os.getenv("CATALOG_API_KEY"),
    )
    # F5.1: при сбое отправки payload фолбэкается в DLQ (catalog_dlq table).
    _catalog_publisher.attach_db(_db)
    await _catalog_publisher.start()

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

    _service = PriceService(
        _db, parsers, cache_ttl_hours=ttl, catalog_publisher=_catalog_publisher
    )
    stats_set_db(_db)

    yield  # приложение работает

    await _catalog_publisher.close()


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
    limit: int = Query(10, ge=1, le=500),
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


@app.get("/api/debug/contract")
async def debug_contract():
    """Контракт парсера: schema ParsedProduct (требуемые/опциональные поля).

    ParsedProduct — frozen dataclass, не pydantic, поэтому собираем схему
    вручную через `dataclasses.fields`. Этот endpoint используется UI как
    «source of truth» для heatmap coverage и валидации новых парсеров.
    """
    import dataclasses
    from .models import ParsedProduct

    fields_out: list[dict] = []
    for f in dataclasses.fields(ParsedProduct):
        # MISSING значит «без default» → required
        no_default = f.default is dataclasses.MISSING
        no_factory = f.default_factory is dataclasses.MISSING  # type: ignore[misc]
        required = no_default and no_factory

        default_repr: object = None
        if not no_default:
            default_repr = f.default
        elif not no_factory:
            try:
                default_repr = f.default_factory()  # type: ignore[misc]
            except Exception:  # noqa: BLE001
                default_repr = None

        # f.type — string из __future__ annotations, оставляем как есть
        type_str = f.type if isinstance(f.type, str) else str(f.type)
        fields_out.append({
            "name": f.name,
            "type": type_str,
            "required": required,
            "default": default_repr,
        })

    return {
        "model": "ParsedProduct",
        "module": "parsers.models",
        "fields": fields_out,
    }


@app.get("/api/debug/fetch-url")
async def debug_fetch_url(
    url: str = Query(..., description="URL для пробного GET-запроса"),
    encoding_hint: str | None = Query(
        None, description="Подсказка декодинга, если httpx угадывает неверно"),
):
    """URL probe — пробный HTTP GET через те же UA/прокси, что у парсеров.

    Полезен при отладке: «магазин отдаёт 200?», «redirect ведёт куда?»,
    «cp1251 правильно декодируется?». Это не запуск парсера на URL — он не
    извлекает структурированный ParsedProduct (для этого нужны магазинные
    селекторы), но даёт raw материал, на котором можно проверить регулярки
    или CSS-селекторы прежде чем встраивать в код парсера.
    """
    import httpx
    proxy = os.getenv("PROXY")
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            proxy=proxy or None,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; boardgames-debug-portal) "
                    "AppleWebKit/537.36 (KHTML, like Gecko)"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
            },
        ) as c:
            resp = await c.get(url)
    except Exception as e:  # noqa: BLE001
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        raise HTTPException(
            status_code=502,
            detail=f"fetch failed after {elapsed_ms}ms: {e}",
        ) from e

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    enc = encoding_hint or resp.encoding or resp.charset_encoding or "utf-8"
    try:
        body_text = resp.content.decode(enc, errors="replace")
    except (LookupError, TypeError):
        enc = "utf-8"
        body_text = resp.content.decode("utf-8", errors="replace")

    BODY_LIMIT = 200_000  # 200KB декодированного — избегаем бесконечных страниц
    truncated = len(body_text) > BODY_LIMIT
    if truncated:
        body_text = body_text[:BODY_LIMIT]

    return {
        "status_code": resp.status_code,
        "encoding": enc,
        "content_type": resp.headers.get("content-type"),
        "body_size": len(resp.content),
        "duration_ms": elapsed_ms,
        "body_text": body_text,
        "truncated": truncated,
        "final_url": str(resp.url),
        "headers": dict(resp.headers),
        "history": [
            {"status": h.status_code, "url": str(h.url)}
            for h in resp.history
        ],
    }


# ---------------------------------------------------------------------------
# DLQ для catalog ingest (F5.1)
# ---------------------------------------------------------------------------


@app.get("/api/dlq")
async def dlq_list(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    """Список DLQ-записей без payload (для UI-таблицы)."""
    return await _db.dlq_list(limit=limit, offset=offset)


@app.post("/api/dlq/{dlq_id}/replay")
async def dlq_replay(dlq_id: int):
    """Повторить отправку одного DLQ-payload в catalog.

    При успехе запись удаляется из DLQ. При повторной ошибке — обновляются
    attempt_count и last_error, payload остаётся для следующих попыток.
    """
    item = await _db.dlq_get(dlq_id)
    if item is None:
        raise HTTPException(status_code=404, detail="DLQ item not found")
    ok, err = await _catalog_publisher.replay(item["payload_json"])
    if ok:
        await _db.dlq_delete(dlq_id)
        return {"status": "ok", "deleted": True}
    await _db.dlq_mark_attempt(dlq_id, err)
    return {"status": "failed", "error": err}


@app.post("/api/dlq/replay-all")
async def dlq_replay_all(limit: int = Query(50, ge=1, le=200)):
    """Batch-replay: попытать первые N записей по created_at."""
    page = await _db.dlq_list(limit=limit, offset=0)
    success = 0
    failed = 0
    for meta in page["items"]:
        item = await _db.dlq_get(meta["id"])
        if item is None:
            continue
        ok, err = await _catalog_publisher.replay(item["payload_json"])
        if ok:
            await _db.dlq_delete(item["id"])
            success += 1
        else:
            await _db.dlq_mark_attempt(item["id"], err)
            failed += 1
    return {"replayed": success + failed, "success": success, "failed": failed}


@app.delete("/api/dlq/{dlq_id}", status_code=204)
async def dlq_delete(dlq_id: int):
    ok = await _db.dlq_delete(dlq_id)
    if not ok:
        raise HTTPException(status_code=404, detail="DLQ item not found")


@app.delete("/api/cache")
async def clear_cache(
    store: str | None = Query(None, description="Магазин (slug). Без — все магазины"),
    q: str | None = Query(
        None,
        description="Подстрока запроса (LIKE %q%); без — все запросы",
    ),
    confirm: bool = Query(
        False,
        description="Обязательное подтверждение для wipe-all (без store и q)",
    ),
):
    """Удалить кеш products + price_observations (для отладки парсеров).

    Без store/q — wipe всей БД, требует confirm=true. С store или q —
    точечная инвалидация.
    """
    if not store and not q and not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "wipe всей БД требует confirm=true. Иначе укажи store или q "
                "для точечной инвалидации."
            ),
        )
    return await _db.clear_cache(store_slug=store, query=q)


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
