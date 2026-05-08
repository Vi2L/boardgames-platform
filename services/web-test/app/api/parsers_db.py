"""Прокси БД-explorer'а parsers через web-test.

Цель — единый shell внутри web-test вместо отдельного /dashboard на :8001.
Все эндпоинты — тонкие прокси к parsers /api/db/* и /api/stats/*.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_parsers_client
from app.parsers_client import ParsersClient

router = APIRouter(prefix="/parsers-db", tags=["parsers-db"])


@router.get("/meta")
async def db_meta(client: ParsersClient = Depends(get_parsers_client)) -> dict:
    try:
        return await client.get_db_metadata()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/stores-inventory")
async def stores_inventory(
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    try:
        return await client.get_stores_inventory()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/products")
async def db_products(
    store: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    try:
        return await client.get_parsers_db_products(
            store=store, q=q, limit=limit, offset=offset,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/products/{product_id}")
async def db_product(
    product_id: int, client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    try:
        return await client.get_parsers_db_product(product_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/top-queries")
async def top_queries(
    hours: int = Query(168, ge=1, le=24 * 30),
    limit: int = Query(20, ge=1, le=100),
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    try:
        return await client.get_top_queries(hours=hours, limit=limit)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/latency")
async def latency_percentiles(
    hours: int = Query(24, ge=1, le=24 * 30),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    try:
        return await client.get_latency_percentiles(hours=hours)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/empty-responses")
async def empty_responses(
    hours: int = Query(24, ge=1, le=24 * 30),
    limit: int = Query(50, ge=1, le=200),
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    try:
        return await client.get_empty_responses(hours=hours, limit=limit)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/price-distribution")
async def price_distribution(
    store: str | None = Query(None),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    try:
        return await client.get_price_distribution(store=store)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/timeline")
async def timeline(
    bucket: str = Query("hour", pattern="^(hour|day)$"),
    hours: int = Query(24, ge=1, le=24 * 30),
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    try:
        return await client.get_timeline(bucket=bucket, hours=hours)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/latency-histogram")
async def latency_histogram(
    hours: int = Query(24, ge=1, le=24 * 30),
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    try:
        return await client.get_latency_histogram(hours=hours)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/store-distribution")
async def store_distribution(
    hours: int = Query(24, ge=1, le=24 * 30),
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    try:
        return await client.get_store_distribution(hours=hours)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/parser-breakdown")
async def parser_breakdown(
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    try:
        return await client.get_parser_breakdown()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.get("/raw-keys")
async def raw_keys(
    top_n: int = Query(10, ge=1, le=50),
    client: ParsersClient = Depends(get_parsers_client),
) -> list[dict]:
    try:
        return await client.get_raw_keys(top_n=top_n)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.delete("/observations/{observation_id}", status_code=204)
async def delete_observation(
    observation_id: int, client: ParsersClient = Depends(get_parsers_client),
) -> None:
    """Удалить одну price-observation — точечная чистка кривых записей."""
    try:
        ok = await client.delete_parsers_observation(observation_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e
    if not ok:
        raise HTTPException(status_code=404, detail="observation not found")
