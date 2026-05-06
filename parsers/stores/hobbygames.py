"""Парсер HobbyGames (hobbygames.ru).

Сайт — OpenCart + Vue.js SPA (кабинет/корзина). Страница поиска рендерится
server-side и содержит карточки товаров в HTML. Работает с российского IP;
с зарубежных адресов возвращает заглушку из-за геоблока.

Технология: HTTP + html.parser (stdlib).

Страница поиска (/search?query=<текст>):
    <div class="product-card">     → карточка
    <a href="/<slug>/" title="..."> → url, title
    <span class="price">           → price
    <img data-src="...">           → image_url (thumbnail)

Страница товара (/<slug>/) добавляет JSON-LD (Product + Offer):
    "image"         → image_url_hd
    "description"   → description
    "offers.price"  → подтверждение цены
    og:image        → image_url_hd (fallback если нет JSON-LD)

Характеристики (если присутствуют в теме OpenCart):
    itemprop="numberOfPlayers"  → players
    itemprop="suggestedAge"     → age_min
    Время партии                → playtime
    Ссылка *.pdf                → rules_url
    Дополнительные картинки     → raw["gallery"]
"""

from __future__ import annotations

import asyncio
import html as html_module
import json
import re
from dataclasses import replace
from html.parser import HTMLParser

import httpx

from ..base import StoreParser
from ..models import ParsedProduct, StoreInfo

STORE = StoreInfo(
    slug="hobbygames",
    name="HobbyGames",
    base_url="https://hobbygames.ru",
)

_SEARCH_URL = "https://hobbygames.ru/search"

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
        params = {"query": query, "limit": limit}
        async with httpx.AsyncClient(**self._client_kwargs) as client:
            resp = await client.get(_SEARCH_URL, params=params)
            resp.raise_for_status()

            parser = _SearchPageParser()
            parser.feed(resp.text)
            basic = parser.products[:limit]

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

        # JSON-LD — основной источник данных (Product + Offer schema)
        ld_blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', page, re.DOTALL
        )
        for block in ld_blocks:
            try:
                data = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            if data.get("@type") == "Product":
                if not extra.get("description") and data.get("description"):
                    extra["description"] = data["description"]
                if not extra.get("image_url_hd") and data.get("image"):
                    img = data["image"]
                    extra["image_url_hd"] = img[0] if isinstance(img, list) else img
                # Характеристики из additionalProperty
                for prop in data.get("additionalProperty", []):
                    name = prop.get("name", "")
                    val = str(prop.get("value", "")).strip()
                    if "игрок" in name.lower() or "players" in name.lower():
                        extra["players"] = val
                    elif "возраст" in name.lower() or "age" in name.lower():
                        m = re.search(r"\d+", val)
                        if m:
                            extra["age_min"] = int(m.group(0))
                    elif "время" in name.lower() or "playtime" in name.lower():
                        extra["playtime"] = val

        # Fallback: og:image если JSON-LD не дал картинку
        if not extra.get("image_url_hd"):
            m = re.search(r'property="og:image"\s+content="([^"]+)"', page)
            if m:
                extra["image_url_hd"] = m.group(1)

        # Fallback: og:description
        if not extra.get("description"):
            m = re.search(r'property="og:description"\s+content="([^"]+)"', page)
            if m:
                extra["description"] = html_module.unescape(m.group(1))

        # itemprop как дополнительный источник характеристик
        if not extra.get("players"):
            m = re.search(r'itemprop="numberOfPlayers"[^>]*content="([^"]+)"', page)
            if m:
                extra["players"] = m.group(1)
        if not extra.get("age_min"):
            m = re.search(r'itemprop="suggestedAge"[^>]*content="([^"]+)"', page)
            if m:
                digits = re.search(r"\d+", m.group(1))
                if digits:
                    extra["age_min"] = int(digits.group(0))

        # Правила PDF
        rules = re.findall(r'href="([^"]*\.pdf[^"]*)"', page, re.I)
        rules = [r for r in rules if "hobbygames" in r or r.startswith("/")]
        if rules:
            extra["rules_url"] = rules[0] if rules[0].startswith("http") else STORE.base_url + rules[0]
            raw["rules"] = rules

        # Галерея (дополнительные изображения)
        gallery = list(dict.fromkeys(
            re.findall(r'"(https://hobbygames\.ru/image/[^"]+)"', page)
        ))
        if gallery:
            raw["gallery"] = gallery

        extra["raw"] = raw
        return extra


# ---------------------------------------------------------------------------
# HTML-парсер страницы результатов поиска
# ---------------------------------------------------------------------------

class _SearchPageParser(HTMLParser):
    """Извлекает карточки товаров из поисковой выдачи HobbyGames."""

    def __init__(self) -> None:
        super().__init__()
        self.products: list[ParsedProduct] = []
        self._in_card = 0
        self._current: dict | None = None
        self._capture_title = False
        self._capture_price = False

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        a = dict(attrs)
        cls = a.get("class", "")

        if tag == "div" and _match_class(cls, ("product-card", "item-card", "goods-card")):
            self._current = {"url": "", "title": "", "price": 0, "image_url": None}
            self._in_card = 1
            return

        if self._current is None:
            return

        if tag == "div":
            self._in_card += 1

        if tag == "a" and a.get("href") and not self._current["url"]:
            href = a["href"]
            if _is_product_link(href):
                self._current["url"] = href
                if a.get("title"):
                    self._current["title"] = html_module.unescape(a["title"])

        if tag == "img" and not self._current["image_url"]:
            src = a.get("data-src") or a.get("src", "")
            if src and ("hobbygames" in src or src.startswith("/image")):
                self._current["image_url"] = src

        if tag in ("h2", "h3", "h4") and _match_class(cls, ("product-name", "item-name", "title", "name")):
            self._capture_title = True

        if tag == "span" and _match_class(cls, ("price", "product-price", "item-price", "cost")):
            self._capture_price = True

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return

        if tag in ("h2", "h3", "h4"):
            self._capture_title = False
        if tag == "span":
            self._capture_price = False

        if tag == "div":
            self._in_card -= 1
            if self._in_card <= 0:
                c = self._current
                if c and c["url"] and c["price"] > 0:
                    product_id = _extract_id(c["url"])
                    self.products.append(ParsedProduct(
                        store_slug=STORE.slug,
                        external_id=product_id,
                        title=c["title"] or product_id,
                        price=c["price"],
                        url=_abs(c["url"]),
                        image_url=_abs(c["image_url"]),
                    ))
                self._current = None
                self._in_card = 0

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = data.strip()
        if not text:
            return
        if self._capture_title and not self._current["title"]:
            self._current["title"] = text
        if self._capture_price:
            price = _parse_price(text)
            if price > 0:
                self._current["price"] = price


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _match_class(cls: str, keywords: tuple[str, ...]) -> bool:
    cls_lower = cls.lower()
    return any(kw in cls_lower for kw in keywords)


def _is_product_link(href: str) -> bool:
    skip = ("/search", "/catalog", "/page", "#", "javascript", "mailto")
    return href.startswith("/") and not any(href.startswith(s) for s in skip)


def _parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) * 100 if digits else 0


def _extract_id(url: str) -> str:
    return url.strip("/").split("/")[-1] or url


def _abs(url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else STORE.base_url + url
