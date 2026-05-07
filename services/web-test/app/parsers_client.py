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


class ParsersServiceError(RuntimeError):
    """Структурированная ошибка от parsers /search.

    parsers возвращает 503 с `{"detail": "..."}`, например при «всё пусто и
    кеша нет». Без этого исключения портал получал бы httpx.HTTPStatusError
    и в UI попадало бы технарское «Server error '503 …' for url '…'».

    Поле detail — то, что parsers положил в JSON-тело; status_code — код
    ответа, чтобы вызывающий мог различить 5xx vs 4xx, если потребуется.
    """

    def __init__(self, status_code: int, detail: str, *, query: str | None = None) -> None:
        self.status_code = status_code
        self.detail = detail
        self.query = query
        super().__init__(detail or f"parsers HTTP {status_code}")


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

        # Структурированная ошибка от parsers (503 «всё пусто и кеша нет»,
        # 422 от FastAPI на невалидные параметры и т. п.) приходит как
        # `{"detail": "..."}`. Распаковываем сами — иначе httpx бросит
        # HTTPStatusError со стандартным «Server error '503 ...' for url ...»,
        # которое неинформативно во фронте.
        if resp.is_error:
            detail = _extract_detail(resp) or f"HTTP {resp.status_code}"
            raise ParsersServiceError(resp.status_code, detail, query=q)

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

    # ── Debug (диагностические endpoint'ы parsers) ──────────────────────

    async def invalidate_cache(
        self,
        store: str | None = None,
        q: str | None = None,
        confirm: bool = False,
    ) -> dict:
        """DELETE /api/cache → удалить cached products + observations.

        Без store и q parsers требует confirm=true. Тут это поведение
        просто пробрасывается — UI должен явно спросить пользователя.
        """
        params: dict[str, Any] = {}
        if store:
            params["store"] = store
        if q:
            params["q"] = q
        if confirm:
            params["confirm"] = "true"
        resp = await self._client.request("DELETE", "/api/cache", params=params)
        if resp.is_error:
            detail = _extract_detail(resp) or f"HTTP {resp.status_code}"
            raise ParsersServiceError(resp.status_code, detail)
        return resp.json()

    async def debug_contract(self) -> dict:
        """GET /api/debug/contract → схема ParsedProduct."""
        resp = await self._client.get("/api/debug/contract")
        resp.raise_for_status()
        return resp.json()

    async def get_field_coverage(self) -> list[dict]:
        """GET /api/stats/field-coverage → coverage опц. полей per-store."""
        resp = await self._client.get("/api/stats/field-coverage")
        resp.raise_for_status()
        return resp.json()

    # ── Parsers DB explorer (F4.1) ──────────────────────────────────────

    async def get_db_metadata(self) -> dict:
        resp = await self._client.get("/api/db/meta")
        resp.raise_for_status()
        return resp.json()

    async def get_stores_inventory(self) -> list[dict]:
        resp = await self._client.get("/api/db/stores-inventory")
        resp.raise_for_status()
        return resp.json()

    async def get_parsers_db_products(
        self, store: str | None = None, q: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if store:
            params["store"] = store
        if q:
            params["q"] = q
        resp = await self._client.get("/api/db/products", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_parsers_db_product(self, product_id: int) -> dict:
        resp = await self._client.get(f"/api/db/product/{product_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_top_queries(self, hours: int = 168, limit: int = 20) -> list[dict]:
        resp = await self._client.get(
            "/api/stats/top-queries", params={"hours": hours, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_latency_percentiles(self, hours: int = 24) -> dict:
        resp = await self._client.get("/api/stats/latency", params={"hours": hours})
        resp.raise_for_status()
        return resp.json()

    async def get_empty_responses(self, hours: int = 24, limit: int = 50) -> list[dict]:
        resp = await self._client.get(
            "/api/stats/empty-responses", params={"hours": hours, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_price_distribution(self, store: str | None = None) -> dict:
        params: dict[str, Any] = {}
        if store:
            params["store"] = store
        resp = await self._client.get("/api/db/price-distribution", params=params)
        resp.raise_for_status()
        return resp.json()

    # ── DLQ (F5.1) ──────────────────────────────────────────────────────

    async def dlq_list(self, limit: int = 100, offset: int = 0) -> dict:
        resp = await self._client.get(
            "/api/dlq", params={"limit": limit, "offset": offset},
        )
        resp.raise_for_status()
        return resp.json()

    async def dlq_replay(self, dlq_id: int) -> dict:
        resp = await self._client.post(f"/api/dlq/{dlq_id}/replay")
        resp.raise_for_status()
        return resp.json()

    async def dlq_replay_all(self, limit: int = 50) -> dict:
        resp = await self._client.post("/api/dlq/replay-all", params={"limit": limit})
        resp.raise_for_status()
        return resp.json()

    async def dlq_delete(self, dlq_id: int) -> bool:
        resp = await self._client.request("DELETE", f"/api/dlq/{dlq_id}")
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    async def delete_parsers_observation(self, observation_id: int) -> bool:
        """DELETE /api/db/observations/{id} → удалить одну точку истории."""
        resp = await self._client.request(
            "DELETE", f"/api/db/observations/{observation_id}",
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    async def debug_fetch_url(
        self,
        url: str,
        encoding_hint: str | None = None,
    ) -> dict:
        """GET /api/debug/fetch-url → пробный GET через парсерский HTTP-стек."""
        params: dict[str, Any] = {"url": url}
        if encoding_hint:
            params["encoding_hint"] = encoding_hint
        resp = await self._client.get("/api/debug/fetch-url", params=params,
                                       timeout=30.0)
        if resp.is_error:
            detail = _extract_detail(resp) or f"HTTP {resp.status_code}"
            raise ParsersServiceError(resp.status_code, detail)
        return resp.json()

    async def debug_features(self) -> dict:
        """GET /api/debug/features → какие debug-возможности активны на parsers."""
        resp = await self._client.get("/api/debug/features")
        resp.raise_for_status()
        return resp.json()

    async def list_raw_snapshots(
        self,
        store: str | None = None,
        query: str | None = None,
        hours: int = 72,
        limit: int = 50,
    ) -> list[dict]:
        """GET /api/debug/snapshots → метаданные сохранённых HTTP-снепшотов."""
        params: dict[str, Any] = {"hours": hours, "limit": limit}
        if store:
            params["store"] = store
        if query:
            params["query"] = query
        resp = await self._client.get("/api/debug/snapshots", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_raw_snapshot(self, snapshot_id: int) -> dict | None:
        """GET /api/debug/snapshots/{id} → snapshot c body_text (decoded)."""
        resp = await self._client.get(f"/api/debug/snapshots/{snapshot_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def get_raw_snapshot_text(self, snapshot_id: int) -> tuple[str, str] | None:
        """GET /api/debug/snapshots/{id}/raw → сырое тело как text/plain.

        Возвращает (text, content_type) либо None если 404. Используется для
        выгрузки/просмотра в DOM (parsers сам декодирует cp1251 и пр.).
        """
        resp = await self._client.get(f"/api/debug/snapshots/{snapshot_id}/raw")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text, resp.headers.get("content-type", "text/plain")

    async def debug_parse(
        self,
        q: str,
        stores: list[str] | None = None,
        limit: int = 5,
    ) -> dict:
        """GET /api/debug/parse → парсеры мимо кеша, сырые ParsedProduct + метрики.

        В отличие от search() этот endpoint:
        - не читает кеш и не пишет в products / request_log;
        - в parser_log помечает is_test=1, не искажая production-метрики.

        Ответ — сырая структура от parsers, не маппится в ProductOut, потому
        что ParsedProduct не имеет id (товар не записан в БД) и хранит price в
        копейках. UI должен уметь рендерить такие карточки отдельно от ProductOut.
        """
        params: dict[str, Any] = {"q": q, "limit": limit}
        if stores:
            params["stores"] = ",".join(stores)
        resp = await self._client.get("/api/debug/parse", params=params)
        if resp.is_error:
            detail = _extract_detail(resp) or f"HTTP {resp.status_code}"
            raise ParsersServiceError(resp.status_code, detail, query=q)
        return resp.json()

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


def _extract_detail(resp: httpx.Response) -> str | None:
    """Достаёт `detail` из JSON-ошибки FastAPI; падает мягко при не-JSON."""
    try:
        body = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text[:500] if text else None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    return None


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
