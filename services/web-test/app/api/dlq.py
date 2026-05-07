"""DLQ proxy для catalog-ingest неудач.

Просто проксирует /api/dlq/* parsers (HTTP 502 при недоступности).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_parsers_client
from app.parsers_client import ParsersClient

router = APIRouter(prefix="/dlq", tags=["dlq"])


@router.get("")
async def list_dlq(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    try:
        return await client.dlq_list(limit=limit, offset=offset)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.post("/{dlq_id}/replay")
async def replay_one(
    dlq_id: int, client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    try:
        return await client.dlq_replay(dlq_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.post("/replay-all")
async def replay_all(
    limit: int = Query(50, ge=1, le=200),
    client: ParsersClient = Depends(get_parsers_client),
) -> dict:
    try:
        return await client.dlq_replay_all(limit=limit)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e


@router.delete("/{dlq_id}", status_code=204)
async def delete_one(
    dlq_id: int, client: ParsersClient = Depends(get_parsers_client),
) -> None:
    try:
        ok = await client.dlq_delete(dlq_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"parsers unreachable: {e}") from e
    if not ok:
        raise HTTPException(status_code=404, detail="DLQ item not found")
