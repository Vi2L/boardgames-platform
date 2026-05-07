"""Парсер Crowd Games (crowdgames.ru).

Crowd Games — российский издатель настольных игр. Весь каталог находится
на одной коллекции /collection/igry-crowd-games (~60 игр, несколько страниц).

Поиск работает локально: качаем все страницы параллельно, фильтруем по запросу.
Это надёжнее, чем встроенный /search, который возвращает нерелевантные результаты.

Технология: HTTP + html.parser (stdlib). Кодировка UTF-8. Без геоблока.

Структура карточки товара (разделитель — data-product-id="..."):
    data-product-id="1571691625"         → external_id
    href="/collection/shop/product/..."   → url
    alt="Название игры"                   → title
    <span ... price-cur...>8 890</span>  → текущая цена в рублях
    data-src="https://images.crowdgames.ru/...png" → изображение
"""

from __future__ import annotations

import asyncio
import re
import time

import httpx

from ..base import ParserMetrics, StoreParser
from ..models import ParsedProduct, StoreInfo

STORE = StoreInfo(
    slug="crowdgames",
    name="Crowd Games",
    base_url="https://www.crowdgames.ru",
)

_CATALOG_URL = "https://www.crowdgames.ru/collection/igry-crowd-games"
_MAX_PAGES = 10  # защита от бесконечного цикла

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
}


class CrowdGamesParser(StoreParser):
    store = STORE

    def __init__(self, proxy: str | None = None) -> None:
        super().__init__()
        self._client_kwargs: dict = {
            "headers": _HEADERS,
            "follow_redirects": True,
            "timeout": 20,
        }
        if proxy:
            self._client_kwargs["proxy"] = proxy

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        # CrowdGames особый случай: нет enrich — поиск это и есть обход всех страниц
        # каталога. search_ms = время загрузки и парсинга всех страниц,
        # enrich_ms = None (этапа просто нет).
        self._http_counter = 0
        self.last_metrics = None

        recorder = self._make_recorder(query)
        client_kwargs = {
            **self._client_kwargs,
            "event_hooks": recorder.merged_hooks({"request": [self._count_request]}),
        }

        t0 = time.monotonic()
        async with httpx.AsyncClient(**client_kwargs) as client:
            pages_html: list[str] = []
            html = await self._fetch_page(client, _CATALOG_URL)
            pages_html.append(html)
            visited: set[str] = {_CATALOG_URL}

            for _ in range(_MAX_PAGES):
                next_path = _next_page(html)
                if not next_path:
                    break
                next_url = STORE.base_url + next_path
                if next_url in visited:
                    break
                visited.add(next_url)
                html = await self._fetch_page(client, next_url)
                pages_html.append(html)

        all_products: list[ParsedProduct] = []
        seen_ids: set[str] = set()
        for page_html in pages_html:
            for p in _parse_cards(page_html):
                if p.external_id not in seen_ids:
                    seen_ids.add(p.external_id)
                    all_products.append(p)

        q_lower = query.lower()
        matched = [p for p in all_products if q_lower in p.title.lower()][:limit]
        search_ms = int((time.monotonic() - t0) * 1000)

        self.last_metrics = ParserMetrics(
            search_ms=search_ms, enrich_ms=None,
            http_requests=self._http_counter,
            result_after_enrich=len(matched),  # без enrich = просто кол-во найденных
        )
        return matched

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> str:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


# ---------------------------------------------------------------------------
# Парсинг карточек
# ---------------------------------------------------------------------------

def _parse_cards(html: str) -> list[ParsedProduct]:
    """Разбивает HTML на карточки по data-product-id и извлекает поля."""
    # Делим HTML на блоки, каждый начинается с data-product-id="..."
    parts = re.split(r'(?=data-product-id=")', html)
    products: list[ParsedProduct] = []

    for part in parts:
        m_pid = re.match(r'data-product-id="(\d+)"', part)
        if not m_pid:
            continue
        pid = m_pid.group(1)

        # URL товара
        m_url = re.search(r'href="(/collection/shop/product/[^"]+)"', part)
        if not m_url:
            continue
        url = STORE.base_url + m_url.group(1)

        # Название из первого alt=""
        alts = re.findall(r'alt="([^"]+)"', part)
        title = alts[0].strip() if alts else None
        if not title:
            continue

        # Текущая цена: <span ... price-cur...>ЧИСЛО</span>
        # На странице бывает два блока price-cur:
        # первый пустой (из-за JS), второй содержит реальную цену
        prices_cur = re.findall(r'<span[^>]*price-cur[^>]*>\s*([^\s<][^<]*?)\s*</span>', part)
        price = None
        for pc in prices_cur:
            digits = re.sub(r'[^\d]', '', pc)
            if digits:
                price = int(digits) * 100  # рубли → копейки
                break

        if price is None:
            # Fallback: берём последнюю цену с ₽ в карточке
            all_prices = re.findall(r'(\d[\d\s]{1,5})\s*₽', part)
            if all_prices:
                digits = re.sub(r'[^\d]', '', all_prices[-1])
                if digits:
                    price = int(digits) * 100

        if not price:
            continue

        # Изображение (data-src с images.crowdgames.ru, предпочитаем .png)
        imgs = re.findall(r'data-src="(https://images\.crowdgames\.ru[^"]+)"', part)
        image_url = imgs[0] if imgs else None

        # Наличие
        in_stock = 'is-zero-count-preorder' not in part and 'is-zero-count' not in part

        products.append(ParsedProduct(
            store_slug=STORE.slug,
            external_id=pid,
            title=title,
            price=price,
            url=url,
            image_url=image_url,
            raw={"in_stock": in_stock},
        ))

    return products


def _next_page(html: str) -> str | None:
    """Извлекает путь следующей страницы из data-collection-infinity."""
    m = re.search(r'data-collection-infinity="([^"]+)"', html)
    return m.group(1) if m else None
