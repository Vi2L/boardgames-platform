"""История цен — проксируется из parsers API."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_parsers_client
from app.schemas import PricePointOut

router = APIRouter(prefix="/products", tags=["history"])


@router.get("/{product_id}/history", response_model=list[PricePointOut])
async def get_history(product_id: int) -> list[PricePointOut]:
    """Возвращает хронологическую историю цен из parsers API (/history/{id}).

    Цена в ответе parsers — копейки. Конвертация в рубли выполняется в клиенте.
    """
    client = get_parsers_client()
    return await client.get_history(product_id)
