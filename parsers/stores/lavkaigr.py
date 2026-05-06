"""Парсер Лавки Игр (lavkaigr.ru).

Сайт — Django SSR, поиск работает по URL /shop/search/?query=<текст>.
Результаты возвращаются в HTML без JS. Доступен без геоблока.

Технология: HTTP + html.parser (stdlib).

Структура карточки на странице поиска (.block):
    data-id="5965"                  → external_id
    data-price="1990"               → цена в рублях
    <a class="game-name" href="..."> → url, title
    <img class="unveil" data-src="..."> → image_url (thumbnail)

Страница товара (/shop/<категория>/<slug>/) добавляет:
    og:image                        → image_url_hd (HD)
    og:description                  → description
    <i class="fa-..."></i>LABEL ... <strong>VALUE</strong>
        → players, playtime, age_min (+ complexity и язык → raw)
    <a href="...tag/...">           → raw["tags"]
    href="...pdf"                   → rules_url + raw["rules"]
    data-src="...lavkaigr..."       → raw["gallery"]
    <li>состав</li>                 → raw["composition"]
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import replace
from html.parser import HTMLParser

import httpx

from ..base import ParserMetrics, StoreParser
from ..models import ParsedProduct, StoreInfo

STORE = StoreInfo(
    slug="lavkaigr",
    name="Лавка Игр",
    base_url="https://www.lavkaigr.ru",
)

_SEARCH_URL = "https://www.lavkaigr.ru/shop/search/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
}


class LavkaIgrParser(StoreParser):
    store = STORE

    def __init__(self, proxy: str | None = None) -> None:
        super().__init__()
        self._client_kwargs: dict = {"headers": _HEADERS, "follow_redirects": True, "timeout": 20}
        if proxy:
            self._client_kwargs["proxy"] = proxy

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        self._http_counter = 0
        self.last_metrics = None

        params = {"query": query}
        client_kwargs = {**self._client_kwargs, "event_hooks": {"request": [self._count_request]}}

        async with httpx.AsyncClient(**client_kwargs) as client:
            t0 = time.monotonic()
            resp = await client.get(_SEARCH_URL, params=params)
            resp.raise_for_status()
            parser = _SearchPageParser()
            parser.feed(resp.text)
            basic = parser.products[:limit]
            search_ms = int((time.monotonic() - t0) * 1000)

            if not basic:
                self.last_metrics = ParserMetrics(
                    search_ms=search_ms, enrich_ms=0,
                    http_requests=self._http_counter, result_after_enrich=0,
                )
                return []

            t1 = time.monotonic()
            enriched = await asyncio.gather(
                *[self._enrich(client, p) for p in basic],
                return_exceptions=True,
            )
            enrich_ms = int((time.monotonic() - t1) * 1000)

        results = []
        successful_enrich = 0
        for product, extra in zip(basic, enriched):
            if isinstance(extra, Exception):
                extra = {}
            else:
                successful_enrich += 1
            results.append(replace(product, **extra))

        self.last_metrics = ParserMetrics(
            search_ms=search_ms, enrich_ms=enrich_ms,
            http_requests=self._http_counter,
            result_after_enrich=successful_enrich,
        )
        return results

    # ------------------------------------------------------------------
    # Обогащение данными со страницы товара
    # ------------------------------------------------------------------

    async def _enrich(self, client: httpx.AsyncClient, product: ParsedProduct) -> dict:
        """Получает страницу товара и возвращает dict для dataclasses.replace()."""
        try:
            resp = await client.get(product.url)
            if not resp.is_success:
                return {}
        except Exception:
            return {}

        html = resp.text
        extra: dict = {}
        raw: dict = dict(product.raw)

        # Главное изображение (HD) из og:image
        m = re.search(r'property="og:image"\s+content="([^"]+)"', html)
        if m:
            extra["image_url_hd"] = m.group(1)

        # Описание из og:description
        m = re.search(r'property="og:description"\s+content="([^"]+)"', html)
        if m:
            extra["description"] = m.group(1)

        # Категория из URL (e.g. /shop/family/ → "family")
        m = re.search(r'/shop/([^/]+)/', product.url)
        if m:
            raw["category"] = m.group(1)

        # Характеристики: иконка → label → значение в <strong>
        pairs = re.findall(
            r'<i class="fa fa-[^"]+"></i>([^<]{2,50})</div>\s*<div[^>]*>\s*<strong[^>]*>\s*(.*?)\s*</strong>',
            html, re.DOTALL,
        )
        for label_raw, val_raw in pairs:
            label = label_raw.strip().rstrip(":")
            val = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", val_raw)).strip()
            if not val:
                continue
            if "игрок" in label:
                m = re.match(r"(\d+(?:-\d+)?)", val)
                if m:
                    extra["players"] = m.group(1)
            elif "Время партии" in label:
                extra["playtime"] = val
            elif "Возраст" in label:
                m = re.search(r"\d+", val)
                if m:
                    extra["age_min"] = int(m.group(0))
            elif "освоение" in label:
                raw["complexity"] = val
            elif "Язык" in label:
                raw["language"] = val

        # Механики / теги
        tags = re.findall(r'href="/shop/tag/[^"]+/">([^<]+)</a>', html)
        if tags:
            raw["tags"] = tags

        # Правила PDF
        rules = re.findall(r'href="([^"]*\.pdf[^"]*)"[^>]*>\s*([^<]{3,60})\s*</a>', html, re.I)
        if rules:
            extra["rules_url"] = rules[0][0]
            raw["rules"] = [{"url": u, "name": n.strip()} for u, n in rules]

        # Галерея (все data-src с доменом lavkaigr)
        gallery = list(dict.fromkeys(
            re.findall(r'data-src="(https://media\.lavkaigr\.ru/[^"]+)"', html)
        ))
        if gallery:
            raw["gallery"] = gallery

        # Состав из <li> внутри секции состава
        li_items = re.findall(r"<li[^>]*>([^<]{5,100})</li>", html)
        composition = [li.strip() for li in li_items
                       if li.strip() and not any(s in li for s in ("<", "js-", "Лавка"))]
        if composition:
            raw["composition"] = composition

        extra["raw"] = raw
        return extra


# ---------------------------------------------------------------------------
# HTML-парсер страницы результатов поиска
# ---------------------------------------------------------------------------

class _SearchPageParser(HTMLParser):
    """Извлекает карточки .product-list.row > .block."""

    def __init__(self) -> None:
        super().__init__()
        self.products: list[ParsedProduct] = []

        self._in_product_list = False
        self._product_list_depth = 0

        self._in_block = False
        self._block_depth = 0
        self._current: dict | None = None
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        a = dict(attrs)
        cls = a.get("class", "")

        if tag == "div" and "product-list" in cls and "row" in cls:
            self._in_product_list = True
            self._product_list_depth = 1
            return

        if self._in_product_list and tag == "div":
            self._product_list_depth += 1

        if not self._in_product_list:
            return

        if tag == "div" and cls == "block":
            self._in_block = True
            self._block_depth = 1
            self._current = {"external_id": "", "title": "", "price": 0,
                             "url": "", "image_url": None}
            return

        if not self._in_block or self._current is None:
            return

        if tag == "div":
            self._block_depth += 1

        if tag == "div" and "photo-block" in cls and a.get("data-id"):
            self._current["external_id"] = a["data-id"]

        if tag == "a":
            href = a.get("href", "")
            if href.startswith("/shop/") and href not in ("/shop/cart/",) and not self._current["url"]:
                self._current["url"] = href
            if "game-name" in cls:
                self._capture_title = True
                if not self._current["url"]:
                    self._current["url"] = href
            if "buy-mini" in cls and a.get("data-price"):
                try:
                    self._current["price"] = int(a["data-price"]) * 100
                except ValueError:
                    pass

        if tag == "img" and not self._current["image_url"]:
            src = a.get("data-src") or a.get("src", "")
            if src.startswith("http"):
                self._current["image_url"] = src

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture_title = False

        if not self._in_product_list:
            return

        if tag == "div":
            if self._in_block:
                self._block_depth -= 1
                if self._block_depth <= 0:
                    self._flush()
                    return
            self._product_list_depth -= 1
            if self._product_list_depth <= 0:
                self._in_product_list = False

    def handle_data(self, data: str) -> None:
        if self._capture_title and self._current and not self._current["title"]:
            text = data.strip()
            if text:
                self._current["title"] = text

    def _flush(self) -> None:
        c = self._current
        if c and c["external_id"] and c["title"] and c["price"] > 0 and c["url"]:
            self.products.append(ParsedProduct(
                store_slug=STORE.slug,
                external_id=c["external_id"],
                title=c["title"],
                price=c["price"],
                url=STORE.base_url + c["url"],
                image_url=c["image_url"],
            ))
        self._current = None
        self._in_block = False
        self._block_depth = 0
