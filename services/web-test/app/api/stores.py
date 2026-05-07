"""Список магазинов — проксируется из parsers API."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_parsers_client
from app.schemas import StoreOut

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("", response_model=list[StoreOut])
async def list_stores() -> list[StoreOut]:
    """Возвращает магазины из parsers API (/stores)."""
    client = get_parsers_client()
    return await client.get_stores()
