"""Status page API — история пингов и timeline unmatched-counter'а.

POST /status/ping   — вызывает health/all, сохраняет в ping_history,
                      возвращает тот же payload что /health/all.
GET  /status/history — список записей ping_history за заданный период.

Используется /status page фронтенда для ретроспектив: графики unmatched
и total_games во времени + лента статусов сервисов.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.catalog_client import CatalogClient
from app.db_local import PortalDB, get_portal_db
from app.deps import get_catalog_client, get_parsers_client
from app.parsers_client import ParsersClient

router = APIRouter(prefix="/status", tags=["status"])


async def _collect_health(
    parsers: ParsersClient,
    catalog: CatalogClient,
) -> dict:
    """Опрашивает оба сервиса параллельно — та же логика что /health/all."""

    async def _parsers_block() -> dict:
        block: dict = {"status": "down", "url": parsers.base_url}
        try:
            await parsers.get_stores()
            block["status"] = "ok"
            try:
                meta = await parsers.get_db_metadata()
                block["meta"] = {
                    "size_bytes": meta.get("size_bytes"),
                    "product_count": meta.get("product_count"),
                    "observation_count": meta.get("observation_count"),
                    "newest_observation": meta.get("newest_observation"),
                }
            except Exception:  # noqa: BLE001
                block["meta"] = None
        except Exception as e:  # noqa: BLE001
            block["error"] = str(e)
        return block

    async def _catalog_block() -> dict:
        block: dict = {"status": "down", "url": catalog.base_url}
        try:
            h = await catalog.health()
            block["status"] = h.get("status", "ok")
            try:
                games_page = await catalog.list_games(limit=1, offset=0)
                block["total_games"] = games_page.get("total")
            except Exception:  # noqa: BLE001
                block["total_games"] = None
            try:
                ms = await catalog.matching_stats()
                block["unmatched_offers"] = ms.get("total_unmatched")
                by_bucket = ms.get("by_bucket") or {}
                block["unmatched_good"] = by_bucket.get("good", 0)
            except Exception:  # noqa: BLE001
                block["unmatched_offers"] = None
        except Exception as e:  # noqa: BLE001
            block["error"] = str(e)
        return block

    p, c = await asyncio.gather(_parsers_block(), _catalog_block())
    return {
        "app": "ok",
        "parsers": p,
        "catalog": c,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/ping")
async def ping(
    parsers: Annotated[ParsersClient, Depends(get_parsers_client)],
    catalog: Annotated[CatalogClient, Depends(get_catalog_client)],
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> dict:
    """Опрашивает оба сервиса, сохраняет в ping_history, возвращает результат.

    Идентичен /health/all, но дополнительно персистирует данные для /status/history.
    Вызывается фронтендом при входе на /status и каждые 30 сек.
    """
    data = await _collect_health(parsers, catalog)

    p = data["parsers"]
    c = data["catalog"]
    await db.save_ping(
        parsers_status=p["status"],
        catalog_status=c["status"],
        unmatched_offers=c.get("unmatched_offers"),
        unmatched_good=c.get("unmatched_good"),
        total_games=c.get("total_games"),
        parsers_error=p.get("error"),
        catalog_error=c.get("error"),
    )
    return data


@router.get("/history")
async def history(
    db: Annotated[PortalDB, Depends(get_portal_db)],
    hours: int = Query(24, ge=1, le=168, description="Период в часах (1..168 = 7 дней)"),
    limit: int = Query(1000, ge=1, le=5000),
) -> dict:
    """История пингов за последние `hours` часов.

    Возвращает записи от новых к старым — для chart'а фронт разворачивает.
    """
    items = await db.get_ping_history(hours=hours, limit=limit)
    return {"items": items, "total": len(items), "hours": hours}
