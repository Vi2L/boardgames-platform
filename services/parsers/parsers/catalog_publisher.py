"""Опциональный publisher оффер'ов в boardgames-catalog.

После успешного парсинга магазина PriceService вызывает publisher.publish(...) —
он fire-and-forget отправляет батч на webhook каталога. Если URL не задан в env,
publisher — no-op (zero overhead).

Контракт webhook'а — стабильный (см. boardgames-catalog/CLAUDE.md):
  POST {CATALOG_INGEST_URL}
  X-API-Key: {CATALOG_API_KEY}
  {
    "store_slug": "...",
    "fetched_at": "ISO-8601",
    "products": [{"external_id","title","url","price","image_url","extra"}]
  }

Дизайн:
- Один shared httpx.AsyncClient на процесс — переиспользует TCP/TLS-соединения.
- Тайм-аут 10s — каталог недоступен → парсер не страдает.
- F5.1: при сетевой ошибке/5xx payload сохраняется в catalog_dlq SQLite,
  можно через web-test UI или прямой POST /api/dlq/.../replay'нуть позже.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from .models import ParsedProduct

logger = logging.getLogger(__name__)


class CatalogPublisher:
    """No-op, если url=None. Иначе — POST'ит батч на webhook каталога.

    Если передан `db: PriceDatabase`, при ошибке payload сохраняется в DLQ
    (catalog_dlq table) для последующего replay'я.
    """

    def __init__(
        self,
        url: str | None,
        api_key: str | None = None,
        db: object | None = None,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None
        # `db: PriceDatabase | None`, но избегаем циклического импорта
        # (publisher импортируется из service.py, db.py импортирует publisher).
        self._db = db

    def attach_db(self, db: object) -> None:
        """Lifespan-инжекция DB после init (избегаем циклического импорта)."""
        self._db = db

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
        """Отправить батч в каталог. При сбое — fall back в DLQ."""
        if not self.enabled or not products:
            return
        assert self._client is not None and self.url is not None

        payload = {
            "store_slug": store_slug,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "products": [self._product_payload(p) for p in products],
        }
        await self._send(payload, len(products), store_slug)

    @staticmethod
    def _product_payload(p: ParsedProduct) -> dict:
        """Формирует один product-элемент для /ingest/offers.

        Поднимаем нормализованные поля (sku/in_stock/original_price/is_preorder)
        из ParsedProduct.raw на верхний уровень payload, чтобы catalog мог
        писать их в типизированные колонки `offers.*`. Каждый магазин кладёт
        в `raw` свой набор ключей — приводим к единому виду:

        - sku           → HobbyGames кладёт `raw["sku"]` (из JSON-LD Product).
        - in_stock      → HobbyGames `raw["availability"]`, Crowd Games `raw["in_stock"]`.
        - original_price → HobbyGames `raw["original_price"]` (цена до скидки).
        - is_preorder   → пока не вытаскиваем (Crowd Games косвенно через
                           CSS-классы, требует доработки парсера).

        `raw` всё равно отправляется целиком в `extra` для аудита и поиска
        по нетипизированным полям.
        """
        raw = p.raw or {}

        sku = raw.get("sku") if isinstance(raw.get("sku"), str) else None

        in_stock: bool | None = None
        for key in ("availability", "in_stock"):
            v = raw.get(key)
            if isinstance(v, bool):
                in_stock = v
                break

        original_price: int | None = None
        v = raw.get("original_price")
        if isinstance(v, int) and v > 0:
            original_price = v

        return {
            "external_id": p.external_id,
            "title": p.title,
            "url": p.url,
            "price": p.price,  # копейки — формат каталога такой же
            "image_url": p.image_url_hd or p.image_url,
            "sku": sku,
            "in_stock": in_stock,
            "original_price": original_price,
            "is_preorder": None,
            "extra": raw,
        }

    async def _send(
        self, payload: dict, items_count: int, store_slug: str,
    ) -> bool:
        """Отправить payload в catalog. True если успех, иначе сохранение в DLQ.

        Используется и для свежих publish, и для replay'ев из DLQ.
        """
        assert self._client is not None and self.url is not None
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            response = await self._client.post(self.url, json=payload, headers=headers)
            response.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CatalogPublisher: не удалось отправить %d offers для %s: %s",
                items_count, store_slug, exc,
            )
            if self._db is not None:
                try:
                    # type: ignore[attr-defined]
                    await self._db.dlq_save(
                        json.dumps(payload, ensure_ascii=False),
                        f"{type(exc).__name__}: {exc}",
                    )
                    logger.info("CatalogPublisher: payload сохранён в DLQ")
                except Exception as save_exc:  # noqa: BLE001
                    logger.error("CatalogPublisher: ошибка записи в DLQ: %s", save_exc)
            return False

    async def replay(self, payload_json: str) -> tuple[bool, str | None]:
        """Replay сохранённого payload. Не пишет в DLQ при повторной ошибке —
        вызывающий обновит attempt_count через dlq_mark_attempt()."""
        if not self.enabled:
            return False, "CatalogPublisher disabled"
        assert self._client is not None and self.url is not None
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as e:
            return False, f"bad payload_json: {e}"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            response = await self._client.post(self.url, json=payload, headers=headers)
            response.raise_for_status()
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
