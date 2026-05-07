"""Health-check для фронта.

Возвращает не только своё состояние («приложение поднято»), но и проверяет
доступность вышестоящего parsers API. Это нужно для индикатора в сайдбаре —
без него пользователь видит «всё ОК» при работающем фронте, но получает
ошибку только в момент реального запроса.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends

from app.catalog_client import CatalogClient
from app.deps import get_catalog_client, get_parsers_client
from app.parsers_client import ParsersClient

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    client: Annotated[ParsersClient, Depends(get_parsers_client)],
) -> dict:
    """Проверка здоровья портала и подключения к parsers.

    Не падает 5xx даже если parsers недоступен — мы хотим, чтобы фронт
    мог получить статус и показать плашку «parsers down», а не пустой экран.
    """
    info: dict = {"app": "ok", "parsers_url": client.base_url}
    try:
        # /stores на стороне parsers возвращает кешированный список — самый
        # дешёвый запрос для пинга. Network-IO здесь оправдан: мы хотим знать,
        # реально ли можно достучаться, а не просто иметь URL в конфиге.
        await client.get_stores()
        info["parsers_api"] = "ok"
    except Exception as exc:  # noqa: BLE001 — намеренно ловим всё для health
        info["parsers_api"] = "unreachable"
        info["error"] = str(exc)
    return info


@router.get("/health/all")
async def health_all(
    parsers: Annotated[ParsersClient, Depends(get_parsers_client)],
    catalog: Annotated[CatalogClient, Depends(get_catalog_client)],
) -> dict:
    """Cross-service health: ping + ключевые счётчики обоих соседей.

    Вызывает оба сервиса параллельно (asyncio.gather), не падает при
    недоступности любого — каждый блок возвращает status=down + error.
    Это намеренно: для UI приборной панели нужны данные о всех сервисах,
    даже если один лежит.

    Метрики выбраны по запоминаемости при отладке: parsers — размер БД и
    счётчики observations; catalog — total games (берём пагинированный
    list с limit=1) и unmatched-counter.
    """
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
