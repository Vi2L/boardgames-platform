"""Debug-эндпоинты: проксирование диагностических ручек parsers.

Web-test — тонкий прокси: ловит ParsersServiceError и маппит его в HTTPException,
чтобы фронт получал структурированный {"detail": "..."} вместо stack-trace.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.deps import get_parsers_client
from app.parsers_client import ParsersClient, ParsersServiceError

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/parse")
async def debug_parse(
    q: str = Query(..., min_length=1, description="Поисковый запрос для парсера"),
    stores: str | None = Query(None, description="Магазины через запятую (опционально)"),
    limit: int = Query(5, ge=1, le=20),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    """Live Test — запустить парсеры мимо кеша.

    Возвращает структуру от parsers как есть:
    `{"query": str, "results": {<slug>: {products, count, duration_ms, metrics, error}}}`.
    """
    store_list = [s.strip() for s in stores.split(",") if s.strip()] if stores else None
    try:
        return await client.debug_parse(q=q, stores=store_list, limit=limit)
    except ParsersServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ── URL probe (F1.4) ───────────────────────────────────────────────────────


@router.get("/fetch-url")
async def debug_fetch_url(
    url: str = Query(..., description="URL целевой страницы магазина"),
    encoding_hint: str | None = Query(None, description="Принудительный encoding"),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    """Пробный GET через parsers (тот же UA/прокси/таймаут что у парсеров).

    Возвращает status_code, encoding, content_type, body_text (≤200KB),
    final_url (после redirect-ов) и history редиректов.
    """
    try:
        return await client.debug_fetch_url(url=url, encoding_hint=encoding_hint)
    except ParsersServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ── Compare: cache vs live ─────────────────────────────────────────────────


@router.get("/compare")
async def debug_compare(
    q: str = Query(..., min_length=1),
    stores: str | None = Query(None),
    limit: int = Query(10, ge=1, le=20),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    """Параллельно запустить /search (с кешем) и /api/debug/parse (мимо кеша).

    Diff считается на бэкенде: ключ — url товара. Возвращаем три категории:
    only_cache, only_live, changed (title/price различаются), плюс счётчик same.

    Зачем делать на сервере: фронту нужно один запрос вместо двух, у обоих
    путей разные форматы продукта (ProductOut vs DebugProduct), и общий ключ
    надо расчитывать в одном месте — иначе расхождения будут трудно ловить.
    """
    store_list = [s.strip() for s in stores.split(",") if s.strip()] if stores else None

    async def _safe_search():
        try:
            r = await client.search(q=q, stores=store_list, limit=limit, refresh=False)
            return {
                "source": r.source,
                "errors": r.errors,
                "products": [p.model_dump() for p in r.products],
            }
        except ParsersServiceError as e:
            return {"source": None, "errors": {}, "products": [], "_error": e.detail}

    async def _safe_debug():
        try:
            return await client.debug_parse(q=q, stores=store_list, limit=limit)
        except ParsersServiceError as e:
            return {"query": q, "results": {}, "_error": e.detail}

    cache_resp, live_resp = await asyncio.gather(_safe_search(), _safe_debug())

    # Группируем cache-products по магазину
    cache_by_store: dict[str, list[dict]] = {}
    for p in cache_resp.get("products", []):
        cache_by_store.setdefault(p["store_slug"], []).append(p)

    # Live результаты уже сгруппированы parsers
    live_results: dict = live_resp.get("results", {})

    target_slugs = set(cache_by_store) | set(live_results)
    if store_list:
        target_slugs &= set(store_list)

    out: dict = {}
    for slug in sorted(target_slugs):
        cache_products = cache_by_store.get(slug, [])
        live_block = live_results.get(slug) or {"products": [], "count": 0,
                                                "duration_ms": None, "metrics": None,
                                                "error": None}
        live_products = live_block.get("products", [])

        # Индексируем по url — у cache-product `url` всегда есть, у live тоже
        cache_idx = {p["url"]: p for p in cache_products if p.get("url")}
        live_idx = {p["url"]: p for p in live_products if p.get("url")}

        only_cache = [u for u in cache_idx if u not in live_idx]
        only_live = [u for u in live_idx if u not in cache_idx]

        changed: list[dict] = []
        same = 0
        for u in cache_idx.keys() & live_idx.keys():
            c, l = cache_idx[u], live_idx[u]
            c_price = c.get("price_rub")
            l_price = l.get("price_rub")
            c_title = c.get("title")
            l_title = l.get("title")
            if c_price != l_price or c_title != l_title:
                changed.append({
                    "url": u,
                    "cache": {"title": c_title, "price_rub": c_price},
                    "live":  {"title": l_title, "price_rub": l_price},
                })
            else:
                same += 1

        out[slug] = {
            "cache": {
                "count": len(cache_products),
                "error": cache_resp.get("errors", {}).get(slug),
                "products": cache_products,
            },
            "live": {
                "count": live_block.get("count", 0),
                "error": live_block.get("error"),
                "duration_ms": live_block.get("duration_ms"),
                "metrics": live_block.get("metrics"),
                "products": live_products,
            },
            "diff": {
                "only_cache": only_cache,
                "only_live": only_live,
                "changed": changed,
                "same_count": same,
            },
        }

    return {
        "query": q,
        "cache_source": cache_resp.get("source"),
        "results": out,
        "errors": {
            "cache": cache_resp.get("_error"),
            "live": live_resp.get("_error"),
        },
    }


# ── Raw HTTP snapshots ─────────────────────────────────────────────────────


@router.get("/features")
async def debug_features(
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    """GET /api/debug/features → флаг raw_snapshots и т.п."""
    try:
        return await client.debug_features()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/snapshots")
async def list_snapshots(
    store: str | None = Query(None),
    query: str | None = Query(None),
    hours: int = Query(72, ge=1, le=720),
    limit: int = Query(50, ge=1, le=500),
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    """GET /api/debug/snapshots → метаданные снепшотов (без body)."""
    try:
        return await client.list_raw_snapshots(
            store=store, query=query, hours=hours, limit=limit,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(
    snapshot_id: int,
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    """GET /api/debug/snapshots/{id} → полный snapshot c body_text."""
    snap = await client.get_raw_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot не найден")
    return snap


@router.get("/snapshots/{snapshot_id}/raw")
async def get_snapshot_raw(
    snapshot_id: int,
    client: ParsersClient = Depends(get_parsers_client),
) -> Response:
    """GET /api/debug/snapshots/{id}/raw → text/plain декодированное body."""
    res = await client.get_raw_snapshot_text(snapshot_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Snapshot не найден")
    text, content_type = res
    return Response(content=text, media_type=content_type)
