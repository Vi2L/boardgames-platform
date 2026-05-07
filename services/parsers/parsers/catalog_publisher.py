"""Опциональный publisher оффер'ов в boardgames-catalog.

После успешного парсинга магазина PriceService вызывает publisher.publish(...) —
он fire-and-forget отправляет батч на webhook каталога. Если URL не задан в env,
publisher — no-op (zero overhead).

Контракт webhook'а — стабильный (см. boardgames-catalog/CLAUDE.md):
  POST {CATALOG_INGEST_URL}
  X-API-Key: {CATALOG_API_KEY}      # опционально, добавится на этапе 7
  {
    "store_slug": "...",
    "fetched_at": "ISO-8601",
    "products": [{"external_id","title","url","price","image_url","extra"}]
  }

Дизайн:
- Errors не должны влиять на ответ /search — ловим всё, логируем warning'ом.
- Один shared httpx.AsyncClient на процесс — переиспользует TCP/TLS-соединения.
- Тайм-аут 10s — каталог недоступен → парсер не страдает.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from .models import ParsedProduct

logger = logging.getLogger(__name__)


class CatalogPublisher:
    """No-op, если url=None. Иначе — POST'ит батч на webhook каталога."""

    def __init__(self, url: str | None, api_key: str | None = None) -> None:
        self.url = url
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self.url:
            self._client = httpx.AsyncClient(timeout=10.0)
            logger.info("CatalogPublisher started: %s", self.url)
        else:
            logger.info("CatalogPublisher disabled (CATALOG_INGEST_URL not set)")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None and self.url is not None

    async def publish(self, store_slug: str, products: list[ParsedProduct]) -> None:
        """Отправить батч в каталог. Глотает любые исключения — это side-channel."""
        if not self.enabled or not products:
            return
        assert self._client is not None and self.url is not None

        payload = {
            "store_slug": store_slug,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "products": [
                {
                    "external_id": p.external_id,
                    "title": p.title,
                    "url": p.url,
                    "price": p.price,  # копейки — формат каталога такой же
                    "image_url": p.image_url_hd or p.image_url,
                    "extra": p.raw or {},
                }
                for p in products
            ],
        }
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        try:
            response = await self._client.post(self.url, json=payload, headers=headers)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CatalogPublisher: не удалось отправить %d offers для %s: %s",
                len(products), store_slug, exc,
            )
