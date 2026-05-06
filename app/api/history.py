"""История цен — проксируется из parsers API."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from app.deps import get_parsers_client
from app.schemas import PriceDeltaOut, PricePointOut

router = APIRouter(prefix="/products", tags=["history"])


@router.get("/{product_id}/history", response_model=list[PricePointOut])
async def get_history(product_id: int) -> list[PricePointOut]:
    """Возвращает хронологическую историю цен из parsers API (/history/{id}).

    Цена в ответе parsers — копейки. Конвертация в рубли выполняется в клиенте.
    """
    client = get_parsers_client()
    return await client.get_history(product_id)


def _parse_iso(ts: str) -> datetime | None:
    """Парсит ISO-timestamp от parsers (поддержка `Z` суффикса)."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


@router.get("/recent-deltas", response_model=list[PriceDeltaOut])
async def get_recent_deltas(
    ids: str = Query(..., description="ID товаров через запятую"),
) -> list[PriceDeltaOut]:
    """Δ между двумя последними точками истории для пакета товаров.

    Используется в ResultsTable для колонки «Δ цена». Один запрос вместо
    N от фронта — экономит round-trip-ы при отображении 10–50 строк.

    Если у товара < 2 точек истории — возвращаем PriceDeltaOut со всеми
    None-полями (фронт показывает «—»).
    """
    raw_ids: list[int] = []
    for part in ids.split(","):
        part = part.strip()
        if part.isdigit():
            raw_ids.append(int(part))
    if not raw_ids:
        return []

    client = get_parsers_client()
    histories = await client.get_history_batch(raw_ids)

    out: list[PriceDeltaOut] = []
    for pid in raw_ids:
        history = histories.get(pid, [])
        # parsers /history возвращает в порядке fetched_at DESC (см. SQL `ORDER BY fetched_at DESC`),
        # но мы не доверяем неявному порядку — сортируем явно по убыванию.
        sorted_h = sorted(history, key=lambda p: p.fetched_at, reverse=True)

        if len(sorted_h) < 2:
            out.append(PriceDeltaOut(product_id=pid))
            continue

        curr, prev = sorted_h[0], sorted_h[1]
        delta_pct: float | None = None
        if prev.price_rub > 0:
            delta_pct = round((curr.price_rub - prev.price_rub) / prev.price_rub * 100, 2)

        days_between: float | None = None
        ts_curr = _parse_iso(curr.fetched_at)
        ts_prev = _parse_iso(prev.fetched_at)
        if ts_curr and ts_prev:
            days_between = round(abs((ts_curr - ts_prev).total_seconds()) / 86400, 2)

        out.append(PriceDeltaOut(
            product_id=pid,
            prev_price_rub=prev.price_rub,
            curr_price_rub=curr.price_rub,
            delta_pct=delta_pct,
            days_between=days_between,
        ))

    return out
