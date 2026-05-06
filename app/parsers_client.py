"""HTTP-клиент для parsers REST API.

Синглтон создаётся в deps.py при старте приложения.
Все методы — async, используют единый httpx.AsyncClient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.schemas import ProductOut, PricePointOut, StoreOut


@dataclass
class ParsersSearchResponse:
    source: str                   # "cache" | "network" | "partial-cache"
    errors: dict[str, str]        # slug → описание ошибки
    products: list[ProductOut]


class ParsersClient:
    """Тонкий клиент для parsers FastAPI-сервиса."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    async def get_stores(self) -> list[StoreOut]:
        """GET /stores → список магазинов."""
        resp = await self._client.get("/stores")
        resp.raise_for_status()
        return [StoreOut(**s) for s in resp.json()]

    async def search(
        self,
        q: str,
        stores: list[str] | None = None,
        limit: int = 10,
        refresh: bool = False,
    ) -> ParsersSearchResponse:
        """GET /search → результаты поиска с кешированием.

        price_rub в ответе уже в рублях (float), не в копейках.
        """
        params: dict[str, Any] = {"q": q, "limit": limit}
        if stores:
            params["stores"] = ",".join(stores)
        if refresh:
            params["refresh"] = "true"

        resp = await self._client.get("/search", params=params)
        resp.raise_for_status()

        data = resp.json()
        products = [_product_from_api(p) for p in data.get("products", [])]
        return ParsersSearchResponse(
            source=data.get("source", "unknown"),
            errors=data.get("errors", {}),
            products=products,
        )

    async def get_history(self, product_id: int) -> list[PricePointOut]:
        """GET /history/{product_id} → история цен в копейках."""
        resp = await self._client.get(f"/history/{product_id}")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return [
            PricePointOut(
                price=p["price"],
                price_rub=round(p["price"] / 100, 2),
                fetched_at=p["fetched_at"],
            )
            for p in resp.json()
        ]

    # ── Stats (проксируется как есть из parsers stats_api) ──────────────

    async def get_summary_stats(self, hours: int = 24) -> dict:
        """GET /api/stats?hours=N → сводка."""
        resp = await self._client.get("/api/stats", params={"hours": hours})
        resp.raise_for_status()
        return resp.json()

    async def get_store_stats(self) -> list[dict]:
        """GET /api/stats/stores → список словарей здоровья парсеров."""
        resp = await self._client.get("/api/stats/stores")
        resp.raise_for_status()
        return resp.json()

    async def get_recent_errors(self, limit: int = 20) -> list[dict]:
        """GET /api/stats/errors?limit=N → последние ошибки."""
        resp = await self._client.get("/api/stats/errors", params={"limit": limit})
        resp.raise_for_status()
        return resp.json()

    # ── Batch history ────────────────────────────────────────────────────

    async def get_history_batch(
        self, product_ids: list[int],
    ) -> dict[int, list[PricePointOut]]:
        """Параллельно тянет историю для нескольких товаров.

        parsers API не имеет batch-эндпоинта (см. parsers-wishlist.md п. 3),
        поэтому делаем N запросов через `asyncio.gather`. Это всё равно
        быстрее, чем N последовательных запросов с фронта, и держит fan-out
        на бекенде, где есть HTTP/2 keep-alive к parsers.

        Падение одного запроса не валит остальные — просто пустая история
        для упавшего id.
        """
        import asyncio

        async def _safe(pid: int) -> tuple[int, list[PricePointOut]]:
            try:
                return pid, await self.get_history(pid)
            except Exception:
                return pid, []

        results = await asyncio.gather(*(_safe(pid) for pid in product_ids))
        return dict(results)


def _product_from_api(data: dict[str, Any]) -> ProductOut:
    """Маппинг ответа parsers API → ProductOut.

    parsers API возвращает price_rub (float, рубли).
    Поля nullable: image_url, image_url_hd, description, players, age_min,
                   playtime, rules_url.
    """
    return ProductOut(
        id=data["id"],
        store_slug=data["store_slug"],
        title=data["title"],
        price_rub=float(data["price_rub"]),
        url=data["url"],
        image_url=data.get("image_url"),
        image_url_hd=data.get("image_url_hd"),
        description=data.get("description"),
        players=data.get("players"),
        age_min=data.get("age_min"),
        playtime=data.get("playtime"),
        rules_url=data.get("rules_url"),
        fetched_at=data.get("fetched_at", ""),
        extra=data.get("extra") or {},
    )
