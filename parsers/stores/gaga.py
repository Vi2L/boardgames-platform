"""Парсер GaGa.ru (gaga.ru).

Сайт на PHP, кодировка cp1251. Поиск: GET /search/?word=<cp1251-percent-encoded>.
httpx декодирует ответ автоматически по Content-Type: text/html; charset=cp1251.
Без геоблока.

Страница поиска (.preview-card):
    data-gid="4814"             → external_id
    data-price="1990"           → цена в рублях
    itemprop="price"            → цена (дублирует, надёжнее)
    <img src="/gaga/.../main/"> → image_url (thumbnail)
    <a href="/game/<slug>/">    → url, title

Страница товара (/game/<slug>/) добавляет:
    og:image                       → image_url_hd
    <ul class="card-features__list">
        <li>правила простые</li>   → raw["complexity"]
        <li>2-5 игроков</li>       → players
        <li>от 7 лет</li>          → age_min
        <li>0.5 - 1.5 ч.</li>      → playtime
    itemprop="ratingValue"         → raw["rating"]
    itemprop="reviewCount"         → raw["review_count"]
    <a href="/rating/#game...">    → raw["ranking"]
    /gaga/files/images/fullsize/   → raw["gallery"]
    /gaga/files/pdf/rules/ru/      → rules_url + raw["rules"]
    Размеры/Вес                    → raw["dimensions"], raw["weight"]
    Состав                         → raw["composition"]
    offline-price                  → raw["offline_price"]
    описание текст                 → description
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import replace
from html.parser import HTMLParser
from urllib.parse import quote

import httpx

from ..base import ParserMetrics, StoreParser
from ..models import ParsedProduct, StoreInfo

STORE = StoreInfo(
    slug="gaga",
    name="GaGa.ru",
    base_url="https://gaga.ru",
)

_SEARCH_URL = "https://gaga.ru/search/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


class GagaParser(StoreParser):
    store = STORE

    def __init__(self, proxy: str | None = None) -> None:
        super().__init__()
        self._client_kwargs: dict = {"headers": _HEADERS, "follow_redirects": True, "timeout": 20}
        if proxy:
            self._client_kwargs["proxy"] = proxy

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        self._http_counter = 0
        self.last_metrics = None

        encoded_query = quote(query.encode("cp1251"))
        url = f"{_SEARCH_URL}?word={encoded_query}"

        client_kwargs = {**self._client_kwargs, "event_hooks": {"request": [self._count_request]}}

        async with httpx.AsyncClient(**client_kwargs) as client:
            t0 = time.monotonic()
            resp = await client.get(url)
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
        try:
            resp = await client.get(product.url)
            if not resp.is_success:
                return {}
        except Exception:
            return {}

        html = resp.text
        extra: dict = {}
        raw: dict = dict(product.raw)

        # og:image → image_url_hd
        m = re.search(r'property="og:image"\s+content="([^"]+)"', html)
        if m:
            extra["image_url_hd"] = m.group(1)

        # Характеристики из <ul class="card-features__list">
        features_block = re.search(
            r'<ul class="card-features__list">(.*?)</ul>', html, re.DOTALL
        )
        if features_block:
            items = re.findall(r"<li>(.*?)</li>", features_block.group(1), re.DOTALL)
            for item in items:
                text = re.sub(r"<[^>]+>", "", item).replace("\xa0", " ").strip()
                if not text:
                    continue
                if "игрок" in text:
                    m = re.match(r"(\d+(?:-\d+)?)", text)
                    if m:
                        extra["players"] = m.group(1)
                elif "лет" in text:
                    m = re.search(r"\d+", text)
                    if m:
                        extra["age_min"] = int(m.group(0))
                elif "ч." in text or "час" in text:
                    extra["playtime"] = text
                elif "правила" in text.lower():
                    raw["complexity"] = text

        # Рейтинг и отзывы
        rv = re.search(r'itemprop="ratingValue">([^<]+)', html)
        rc = re.search(r'itemprop="reviewCount">([^<]+)', html)
        if rv:
            raw["rating"] = rv.group(1).strip()
        if rc:
            raw["review_count"] = rc.group(1).strip()

        # Место в рейтинге
        rank = re.search(r'href="/rating/#game\d+">([^<]+)</a>', html)
        if rank:
            raw["ranking"] = rank.group(1).strip()

        # Offline-цена (без регистрации)
        offline = re.search(r'<span class="offline-price__value">([^<]+)</span>', html)
        if offline:
            digits = re.sub(r"[^\d]", "", offline.group(1))
            if digits:
                raw["offline_price"] = int(digits) * 100  # в копейках

        # Fullsize галерея
        gallery = list(dict.fromkeys(
            re.findall(r"(/gaga/files/images/fullsize/\d+/\d+\.(?:jpg|png))", html)
        ))
        if gallery:
            raw["gallery"] = [STORE.base_url + img for img in gallery]

        # Правила PDF
        rules_paths = list(dict.fromkeys(
            re.findall(r"(/gaga/files/pdf/rules/ru/[^\"']+\.pdf)", html)
        ))
        if rules_paths:
            extra["rules_url"] = STORE.base_url + rules_paths[0]
            raw["rules"] = [STORE.base_url + p for p in rules_paths]

        # Размеры коробки
        dims = re.search(r"(?:Высота|Размер)[^:]*:\s*([^\n<]{5,60})", html)
        if dims:
            raw["dimensions"] = dims.group(1).strip()

        # Вес
        weight = re.search(r"Вес:\s*([^\n<]{3,30})", html)
        if weight:
            raw["weight"] = weight.group(1).strip()

        # Состав
        comp_idx = html.find("Состав:")
        if comp_idx > 0:
            comp_chunk = html[comp_idx: comp_idx + 600]
            comp_text = re.sub(r"<[^>]+>", "", comp_chunk)
            comp_text = re.sub(r"\s+", " ", comp_text).strip()
            if comp_text:
                raw["composition"] = comp_text[:400]

        # Описание — ищем блок «Описание» (вкладка)
        # Берём первый абзац содержательного текста перед разделом с характеристиками
        desc_block = re.search(
            r'<div[^>]+class="[^"]*game-description[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL
        )
        if desc_block:
            desc = re.sub(r"<[^>]+>", "", desc_block.group(1)).strip()
            if desc:
                extra["description"] = desc
        elif not extra.get("description"):
            # fallback: og:description
            m = re.search(r'property="og:description"\s+content="([^"]+)"', html)
            if m:
                extra["description"] = m.group(1)

        extra["raw"] = raw
        return extra


# ---------------------------------------------------------------------------
# HTML-парсер страницы результатов поиска
# ---------------------------------------------------------------------------

class _SearchPageParser(HTMLParser):
    """Извлекает карточки .preview-card из страницы /search/."""

    def __init__(self) -> None:
        super().__init__()
        self.products: list[ParsedProduct] = []

        self._in_card = False
        self._card_depth = 0
        self._current: dict | None = None
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        a = dict(attrs)
        cls = a.get("class", "")

        if tag == "div" and cls == "preview-card":
            self._in_card = True
            self._card_depth = 1
            self._current = {"external_id": "", "title": "", "price": 0,
                             "url": "", "image_url": None}
            return

        if not self._in_card or self._current is None:
            return

        if tag == "div":
            self._card_depth += 1

        if tag == "p" and "preview-card__title" in cls:
            self._current["_in_title"] = True

        if self._current.get("_in_title") and tag == "a":
            href = a.get("href", "")
            if href.startswith("/game/") and not self._current["url"]:
                self._current["url"] = href
            if a.get("title") and not self._current["title"]:
                self._current["title"] = a["title"]
            self._capture_title = True

        if tag == "img" and not self._current["image_url"]:
            src = a.get("src", "")
            if src and "/images/" in src:
                self._current["image_url"] = STORE.base_url + src if src.startswith("/") else src

        if tag == "button" and "add_to_cart" in cls:
            if a.get("data-gid"):
                self._current["external_id"] = a["data-gid"]
            if a.get("data-price") and self._current["price"] == 0:
                try:
                    self._current["price"] = int(a["data-price"]) * 100
                except ValueError:
                    pass

        if tag == "span" and a.get("itemprop") == "price":
            self._current["_capture_price"] = True

        if tag == "meta" and a.get("itemprop") == "price" and a.get("content"):
            try:
                self._current["price"] = int(float(a["content"])) * 100
            except ValueError:
                pass

    def handle_endtag(self, tag: str) -> None:
        if not self._in_card or self._current is None:
            return

        if tag == "a" and self._capture_title:
            self._capture_title = False

        if tag == "p":
            self._current.pop("_in_title", None)

        if tag == "span":
            self._current.pop("_capture_price", None)

        if tag == "div":
            self._card_depth -= 1
            if self._card_depth <= 0:
                self._flush()

    def handle_data(self, data: str) -> None:
        if not self._in_card or self._current is None:
            return
        text = data.strip()
        if not text:
            return
        if self._capture_title and not self._current["title"]:
            self._current["title"] = text
        if self._current.get("_capture_price") and self._current["price"] == 0:
            try:
                self._current["price"] = int(re.sub(r"[^\d]", "", text)) * 100
            except ValueError:
                pass

    def _flush(self) -> None:
        c = self._current
        if c and c["external_id"] and c["title"] and c["price"] > 0 and c["url"]:
            c.pop("_in_title", None)
            c.pop("_capture_price", None)
            self.products.append(ParsedProduct(
                store_slug=STORE.slug,
                external_id=c["external_id"],
                title=c["title"],
                price=c["price"],
                url=STORE.base_url + c["url"],
                image_url=c["image_url"],
            ))
        self._current = None
        self._in_card = False
        self._card_depth = 0
