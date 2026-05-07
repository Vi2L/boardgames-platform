"""HTTP-клиент для boardgames-catalog REST API.

Симметричен ParsersClient: тонкая обёртка над httpx.AsyncClient. Создаётся
синглтоном в deps.py при старте, закрывается на shutdown.

Каталог отдаёт игру с массивом aliases в детальной карточке и offers, но в
этом клиенте мы покрываем только то, что нужно UI ручного матчинга:
- list/get games (поиск через pg_trgm fuzzy)
- очередь unmatched-оффер'ов
- link / reject из очереди
"""
from __future__ import annotations

from typing import Any

import httpx


class CatalogServiceError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail or f"catalog HTTP {status_code}")


class CatalogClient:
    def __init__(
        self, base_url: str, api_key: str | None = None, timeout: float = 30.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=headers
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def list_games(
        self,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /games — листинг с pg_trgm fuzzy-search по q."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q:
            params["q"] = q
        resp = await self._client.get("/games", params=params)
        return _ok_or_raise(resp)

    async def get_game(self, game_id: int) -> dict[str, Any]:
        resp = await self._client.get(f"/games/{game_id}")
        return _ok_or_raise(resp)

    async def matching_queue(
        self, store: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if store:
            params["store"] = store
        resp = await self._client.get("/matching/queue", params=params)
        return _ok_or_raise(resp)

    async def link_offer(self, offer_id: int, game_id: int) -> dict[str, Any]:
        resp = await self._client.post(
            f"/matching/{offer_id}/link", json={"game_id": game_id}
        )
        return _ok_or_raise(resp)

    async def reject_offer(self, offer_id: int) -> dict[str, Any]:
        resp = await self._client.post(f"/matching/{offer_id}/reject")
        return _ok_or_raise(resp)

    # ── Aliases CRUD ────────────────────────────────────────────────────

    async def add_alias(self, game_id: int, payload: dict) -> dict[str, Any]:
        """POST /games/{id}/aliases — добавить альтернативное название."""
        resp = await self._client.post(f"/games/{game_id}/aliases", json=payload)
        return _ok_or_raise(resp)

    async def patch_alias(
        self, game_id: int, alias_id: int, payload: dict,
    ) -> dict[str, Any]:
        """PATCH /games/{id}/aliases/{alias_id} — редактирование."""
        resp = await self._client.patch(
            f"/games/{game_id}/aliases/{alias_id}", json=payload,
        )
        return _ok_or_raise(resp)

    async def delete_alias(self, game_id: int, alias_id: int) -> None:
        """DELETE /games/{id}/aliases/{alias_id} → 204."""
        resp = await self._client.delete(f"/games/{game_id}/aliases/{alias_id}")
        if resp.is_error:
            try:
                detail = resp.json().get("detail", "")
            except ValueError:
                detail = resp.text[:500]
            raise CatalogServiceError(resp.status_code, detail or f"HTTP {resp.status_code}")


def _ok_or_raise(resp: httpx.Response) -> dict[str, Any]:
    if resp.is_error:
        try:
            detail = resp.json().get("detail", "")
        except ValueError:
            detail = resp.text[:500]
        raise CatalogServiceError(resp.status_code, detail or f"HTTP {resp.status_code}")
    return resp.json()
