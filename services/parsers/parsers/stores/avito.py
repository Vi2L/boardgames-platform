"""Парсер Авито — C2C доска объявлений.

Стратегия обхода Qrator: **L0 — pure curl-cffi + JSON-endpoint**.

avito.ru — CSR-приложение: первая HTML-страница не содержит items, фронт
дёргает публичный JSON-endpoint `/web/1/js/items` для рендера. Мы дёргаем
тот же endpoint напрямую через curl-cffi с TLS-impersonation Chrome 124.

Всё низкоуровневое (cold-start `_avisc`, cookie-jar, headers) живёт в
`avito_qrator.AvitoQratorClient`. Этот файл — только маппинг JSON-ответа
в `ParsedProduct` и метрики.

**Фильтр по категории (2026-05-18).** Поиск `/web/1/js/items?q=...` —
глобальный по всему Авито: легко прилетает книга, велосипед, одежда,
если они содержат query-слова. Параметр `categoryId` в URL endpoint
игнорирует (probe 2026-05-18). Поэтому фильтруем **локально по
`microCategoryId`** — Авито в каждом item возвращает microcategory из
дерева Хобби/Спорт. Whitelist `_BOARDGAMES_MICRO_IDS` подтверждён
probe'ом (`bin/probe_avito_microcategory.py`):

  2301999 — основная микрокатегория «Настольные игры» (карkасон, монополия)
  2301997, 2301995 — родственные subset'ы (Игры для дома и др.)

Если ни один item не прошёл фильтр — возвращаем **пустой список**
(без fallback'а к общей выдаче): задача «лучше пусто, чем мусор».

Поля `ParsedProduct.raw`:
  location           — город/регион продавца (из `location.name`)
  posted_at          — нет в JSON, отсутствует
  in_stock           — True (факт наличия объявления)
  category           — `category.name` (родительская: «Спорт и отдых» и т.п.)
  micro_category_id  — микрокатегория для аудита/диагностики
"""
from __future__ import annotations

import logging
import re
import time

from ..base import ParserMetrics, StoreParser
from ..models import ParsedProduct, StoreInfo
from .avito_qrator import AvitoQratorClient, AvitoQratorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.avito.ru"

# Whitelist микрокатегорий «настольные игры» (подмножество category.id=39
# «Спорт и отдых»). Подтверждено probe'ом bin/probe_avito_microcategory.py.
# Если Avito введёт новые micro-id для настолок — добавить сюда.
_BOARDGAMES_MICRO_IDS: frozenset[int] = frozenset({2301995, 2301997, 2301999})

# Пытаемся вытащить число из строки цены вида "1 490 ₽".
#   (NBSP) и   (NNBSP) avito вставляет как разделитель тысяч.
_PRICE_RE = re.compile(r"[\d  \s]+")


class AvitoParser(StoreParser):
    """L0-парсер Авито: JSON-API через curl-cffi.

    Передавать `qrator_client=None` можно для тестов — `search()` тогда
    тихо возвращает `[]` (backward compat с прежним поведением, когда
    browser-service не был сконфигурирован).
    """

    store = StoreInfo(slug="avito", name="Авито", base_url=_BASE_URL)

    def __init__(self, qrator_client: AvitoQratorClient | None = None) -> None:
        super().__init__()
        self._qrator = qrator_client

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        if self._qrator is None:
            return []

        self._http_counter = 0
        self.last_metrics = None

        t0 = time.monotonic()
        try:
            payload = await self._qrator.search_items(query)
        except AvitoQratorError as exc:
            # Поднимаем как RuntimeError — PriceService логирует в parser_log
            # с success=False, аналитика подхватывает.
            raise RuntimeError(f"Авито: {exc}") from exc

        search_ms = int((time.monotonic() - t0) * 1000)
        # Один HTTP request (или 2 если был cold-start — для метрик считаем
        # как 1, потому что cold-start амортизируется на десятки последующих).
        self._http_counter = 1

        items = _extract_items(payload)
        products = _build_products(items, limit)

        self.last_metrics = ParserMetrics(
            search_ms=search_ms,
            enrich_ms=None,
            http_requests=self._http_counter,
            result_after_enrich=len(products),
        )
        return products


def _extract_items(payload: dict) -> list[dict]:
    """В ответе `/web/1/js/items` items лежат в `catalog.items`. На случай,
    если avito поменяет схему, проверяем ещё пару очевидных мест."""
    catalog = payload.get("catalog")
    if isinstance(catalog, dict):
        items = catalog.get("items")
        if isinstance(items, list):
            return items
    # Fallback на root-level items (старый `/web/1/main/items` формат).
    root_items = payload.get("items")
    if isinstance(root_items, list):
        return root_items
    return []


def _parse_price_kopecks(item: dict) -> int:
    """Достаём цену в копейках из `priceDetailed`.

    Avito ставит `value: 0` для объявлений «Цена не указана» или с особой
    разметкой — тогда падаем на парсинг `string` («1 490 ₽»).
    """
    pd = item.get("priceDetailed") or {}
    value = pd.get("value")
    if isinstance(value, (int, float)) and value > 0:
        return int(value * 100)
    s = pd.get("string") or ""
    if not s:
        return 0
    digits = "".join(c for c in s if c.isdigit())
    if not digits:
        return 0
    try:
        return int(digits) * 100
    except ValueError:
        return 0


def _pick_image(item: dict) -> str | None:
    """Берём картинку с самым большим разрешением — она годится и под HD,
    и под thumbnail (фронт сам уменьшит)."""
    images = item.get("images") or []
    if not images:
        return None
    first = images[0]
    if not isinstance(first, dict):
        return None
    # Ключи вида "678x678", "558x558" — берём с максимальным width.
    best_url = None
    best_w = 0
    for key, url in first.items():
        if "x" not in key or not isinstance(url, str):
            continue
        try:
            w = int(key.split("x", 1)[0])
        except ValueError:
            continue
        if w > best_w:
            best_w = w
            best_url = url
    return best_url


def _build_products(items: list[dict], limit: int) -> list[ParsedProduct]:
    """Сборка списка ParsedProduct из items JSON-ответа.

    Strict-фильтр по `microCategoryId`: оставляем только те объявления,
    которые лежат в whitelist'е настольных игр. Книги, велосипеды, посуда —
    отсекаются на этапе сборки, чтобы не попали ни в /search, ни в catalog
    через publisher.
    """
    products: list[ParsedProduct] = []
    seen: set[str] = set()
    for it in items:
        if len(products) >= limit:
            break
        if not isinstance(it, dict):
            continue
        # Категорийный фильтр — самый дешёвый, делаем его первым.
        micro_id = it.get("microCategoryId")
        if not isinstance(micro_id, int) or micro_id not in _BOARDGAMES_MICRO_IDS:
            continue

        item_id = str(it.get("id") or "")
        if not item_id or item_id in seen:
            continue
        title = (it.get("title") or "").strip()
        url_path = it.get("urlPath") or ""
        if not title or not url_path:
            continue
        # url_path вида "/moskva/sport_i_otdyh/...?context=..." — для
        # стабильности external_id и БД режем query-параметры.
        url_clean = url_path.split("?", 1)[0]
        if not url_clean.startswith("/"):
            continue
        full_url = _BASE_URL + url_clean

        price_kopecks = _parse_price_kopecks(it)
        image_url = _pick_image(it)
        description = (it.get("description") or "").strip() or None

        raw: dict = {"in_stock": True, "micro_category_id": micro_id}
        loc = it.get("location")
        if isinstance(loc, dict) and loc.get("name"):
            raw["location"] = loc["name"]
        cat = it.get("category")
        if isinstance(cat, dict) and cat.get("name"):
            raw["category"] = cat["name"]

        seen.add(item_id)
        products.append(ParsedProduct(
            store_slug="avito",
            external_id=item_id,
            title=title,
            price=price_kopecks,
            url=full_url,
            image_url=image_url,
            description=description,
            raw=raw,
        ))
    return products
