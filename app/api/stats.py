"""Прокси для эндпоинтов статистики parsers stats_api.

parsers уже отдаёт /api/stats[/stores|/errors] и держит свой dashboard.
Мы просто пробрасываем — не дублируя логику. Если parsers недоступен,
не падаем 5xx, а возвращаем `_unavailable` маркер: фронт ожидает плашку
«parsers unreachable», а не пустой экран.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import get_parsers_client
from app.parsers_client import ParsersClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])


def _unavailable(detail: str) -> dict:
    return {"_unavailable": True, "_error": detail}


@router.get("/summary")
async def summary(
    client: Annotated[ParsersClient, Depends(get_parsers_client)],
    hours: int = Query(24, ge=1, le=24 * 30),
) -> dict:
    """Сводная статистика запросов к parsers за N часов."""
    try:
        return await client.get_summary_stats(hours=hours)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stats summary unavailable: %s", exc)
        return _unavailable(str(exc))


@router.get("/stores")
async def stores(
    client: Annotated[ParsersClient, Depends(get_parsers_client)],
) -> list[dict] | dict:
    """Здоровье каждого парсера за последние 24 часа."""
    try:
        return await client.get_store_stats()
    except Exception as exc:  # noqa: BLE001
        logger.warning("stats stores unavailable: %s", exc)
        return _unavailable(str(exc))


@router.get("/errors")
async def errors(
    client: Annotated[ParsersClient, Depends(get_parsers_client)],
    limit: int = Query(20, ge=1, le=200),
) -> list[dict] | dict:
    """Последние N ошибок парсеров."""
    try:
        return await client.get_recent_errors(limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stats errors unavailable: %s", exc)
        return _unavailable(str(exc))
