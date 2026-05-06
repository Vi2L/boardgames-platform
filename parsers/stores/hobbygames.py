"""Парсер HobbyGames (hobbygames.ru).

Сайт — собственная CMS + SSR. Без геоблока, работает с любого IP.

URL поиска: GET /catalog/search?keyword=<текст>

Страница поиска содержит JSON-LD ItemList со всеми найденными товарами —
парсинг HTML не нужен. Числовой product_id берётся из атрибута
data-product_id на карточках .product-card.

Страница товара (/<slug>/) содержит JSON-LD Product с описанием,
SKU и категорией. Правила — ссылки /download/rules/*.pdf.
Характеристики (players, age, playtime) в структурированном виде
не предоставляются.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from urllib.parse import urljoin

import httpx

from ..base import StoreParser
from ..models import ParsedProduct, StoreInfo

STORE = StoreInfo(
    slug="hobbygames",
    name="HobbyGames",
    base_url="https://hobbygames.ru",
)

_SEARCH_URL = "https://hobbygames.ru/catalog/search"
# Базовый URL для изображений (относительные пути из JSON-LD → абсолютные)
_IMG_BASE = "https://hobbygames.ru/image/cache/hobbygames_beta/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
}


class HobbyGamesParser(StoreParser):
    store = STORE

    def __init__(self, proxy: str | None = None) -> None:
        self._client_kwargs: dict = {"headers": _HEADERS, "follow_redirects": True, "timeout": 20}
        if proxy:
            self._client_kwargs["proxy"] = proxy

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        params = {"keyword": query}
        async with httpx.AsyncClient(**self._client_kwargs) as client:
            resp = await client.get(_SEARCH_URL, params=params)
            resp.raise_for_status()

            basic = _parse_search_page(resp.text, limit)
            if not basic:
                return []

            enriched = await asyncio.gather(
                *[self._enrich(client, p) for p in basic],
                return_exceptions=True,
            )

        results = []
        for product, extra in zip(basic, enriched):
            if isinstance(extra, Exception):
                extra = {}
            results.append(replace(product, **extra))
        return results

    # ------------------------------------------------------------------
    # Обогащение данными со страницы товара
    # ------------------------------------------------------------------

    async def _enrich(self, client: httpx.AsyncClient, product: ParsedProduct) -> dict:
        try:
            resp = await client.get(product.url)
            if not resp.is_success:
                return {}
        except Exception:
            return {}

        page = resp.text
        extra: dict = {}
        raw: dict = dict(product.raw)

        # JSON-LD Product на странице товара
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.DOTALL):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "Product":
                        continue
                    if item.get("description") and not extra.get("description"):
                        extra["description"] = item["description"]
                    if item.get("category"):
                        raw["category"] = item["category"]
                    if item.get("sku"):
                        raw["sku"] = item["sku"]
            except (json.JSONDecodeError, AttributeError):
                continue

        # HD-изображение из og:image (полный абсолютный URL)
        m = re.search(r'property="og:image"\s+content="([^"]+)"', page)
        if m:
            extra["image_url_hd"] = m.group(1)

        # Правила PDF — несколько файлов могут присутствовать (основные + соло и т.д.)
        # Предпочитаем файл без "solo" в имени как основной
        rules = list(dict.fromkeys(
            re.findall(r'href="(/download/rules/[^"]+\.pdf)"', page, re.I)
        ))
        if rules:
            primary = next((r for r in rules if "solo" not in r.lower()), rules[0])
            extra["rules_url"] = STORE.base_url + primary
            raw["rules"] = [STORE.base_url + r for r in rules]

        # Галерея — только изображения самого товара.
        # Путь продуктовых картинок всегда содержит /data/<Производитель>/<Название>/
        # и НЕ содержит -new/, /manufacturer/, /common_avatars/, /video/, /menu/, /footer/
        _SKIP = ("-new/", "/manufacturer/", "/common_avatars/", "/video/", "/menu/", "/footer/")
        gallery = list(dict.fromkeys(
            url for url in re.findall(r'"(https://hobbygames\.ru/image/[^"]+\.(?:jpg|jpeg|png|webp))"', page)
            if not any(s in url for s in _SKIP)
        ))
        if gallery:
            raw["gallery"] = gallery

        extra["raw"] = raw
        return extra


# ---------------------------------------------------------------------------
# Парсинг страницы поиска
# ---------------------------------------------------------------------------

def _parse_search_page(html: str, limit: int) -> list[ParsedProduct]:
    """Извлекает товары из JSON-LD ItemList и data-product_id из HTML."""

    # 1. JSON-LD ItemList → основные данные
    ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    item_list: list[dict] = []
    for block in ld_blocks:
        try:
            data = json.loads(block.strip())
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                item_list = data.get("itemListElement", [])
                break
        except (json.JSONDecodeError, AttributeError):
            continue

    if not item_list:
        return []

    # 2. data-product_id из HTML-карточек → сопоставляем по slug URL
    # Формат: <div class="product-card ..." data-product_id="72557" ...>
    #   <a href="/karkasson" ...>
    # Строим словарь slug → product_id
    slug_to_id: dict[str, str] = {}
    for m in re.finditer(
        r'<div[^>]+class="product-card[^"]*"[^>]+data-product_id="(\d+)"[^>]*>.*?href="(/[^"?#]+)"',
        html, re.DOTALL
    ):
        product_id, href = m.group(1), m.group(2)
        slug = href.strip("/").split("/")[-1]
        slug_to_id[slug] = product_id

    # 3. Собираем ParsedProduct
    products: list[ParsedProduct] = []
    for item in item_list[:limit]:
        if item.get("@type") != "Product":
            continue

        url = item.get("url", "")
        if not url:
            continue

        offers = item.get("offers", {})
        price_rub = offers.get("price", 0)
        try:
            price = int(float(price_rub)) * 100  # рубли → копейки
        except (ValueError, TypeError):
            continue

        slug = url.rstrip("/").split("/")[-1]
        external_id = slug_to_id.get(slug, slug)  # числовой ID или slug как fallback

        # Изображение: относительный путь → абсолютный кеш-URL
        image_rel = item.get("image", "")
        image_url = (_IMG_BASE + image_rel) if image_rel and not image_rel.startswith("http") else image_rel or None

        availability = offers.get("availability", "")
        in_stock = "InStock" in availability

        products.append(ParsedProduct(
            store_slug=STORE.slug,
            external_id=external_id,
            title=item.get("name", ""),
            price=price,
            url=url if url.startswith("http") else STORE.base_url + url,
            image_url=image_url,
            description=item.get("description"),
            raw={"availability": in_stock},
        ))

    return products
