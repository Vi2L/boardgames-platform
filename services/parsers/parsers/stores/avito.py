"""Парсер Авито — C2C доска объявлений, раздел «Настольные игры».

Зависит от services/browser/ (INFRA-5): использует BrowserClient для обхода
антибот-защиты Cloudflare + JS-рендеринга. При отсутствии browser_client —
молча возвращает пустой список (graceful degradation без ломки стека).

Поля ParsedProduct.raw:
  condition   — "new" | "used" | None
  location    — город/регион продавца ("Москва", "СПб и ЛО" и т.д.)
  seller_type — "private" | "shop" | None
  in_stock    — True (объявление на Авито = товар у продавца)

Enrich (загрузка страницы каждого объявления) — не в первой итерации.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup

from ..base import ParserMetrics, StoreParser
from ..models import ParsedProduct, StoreInfo

_BASE_URL = "https://www.avito.ru"
# Раздел «Настольные игры» — даёт точнее, чем общий /rossiya?q=...
_SEARCH_URL = f"{_BASE_URL}/rossiya/nastolnye_igry"

# s=104 = сортировка «по дате» (свежее вверху)
_SORT_PARAM = "s=104"

# ID в конце URL: /moskva/nastolnye_igry/karandash_3456789123 → 3456789123
_ID_RE = re.compile(r"_(\d{5,})(?:[?#&]|$)")

# Авито URI-кодирует JSON в window.__initialData__ = "..."
_INIT_DATA_RE = re.compile(r'window\.__initialData__\s*=\s*"([^"]{100,})"')


class AvitoParser(StoreParser):
    """Парсер Авито. Требует browser-as-a-service (services/browser/).

    Без browser_client тихо возвращает [] — остальные парсеры работают штатно.
    """

    store = StoreInfo(slug="avito", name="Авито", base_url=_BASE_URL)

    def __init__(self, browser_client=None) -> None:
        super().__init__()
        self._browser_client = browser_client

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        if not self._browser_client:
            return []

        self._http_counter = 0
        self.last_metrics = None

        url = f"{_SEARCH_URL}?q={quote(query)}&{_SORT_PARAM}"

        t0 = time.monotonic()
        result = await self._browser_client.fetch(
            url,
            wait_until="networkidle",
            timeout_ms=35_000,
            stealth=True,
        )
        # Один вызов к browser-сервису = одна «транзакция» в метриках,
        # даже если Chromium внутри делает десятки sub-request'ов.
        self._http_counter = 1
        search_ms = int((time.monotonic() - t0) * 1000)

        products = _parse_page(result["html"], limit)

        self.last_metrics = ParserMetrics(
            search_ms=search_ms,
            enrich_ms=None,   # enrich не в первой итерации
            http_requests=self._http_counter,
            result_after_enrich=len(products),
        )
        return products


# ---------------------------------------------------------------------------
# Парсинг страницы
# ---------------------------------------------------------------------------

def _parse_page(html: str, limit: int) -> list[ParsedProduct]:
    """Два подхода: embedded JSON (надёжнее) → HTML-фолбэк."""
    products = _try_json(html, limit)
    if products:
        return products
    return _from_html(html, limit)


# ── JSON-стратегия ────────────────────────────────────────────────────────

def _try_json(html: str, limit: int) -> list[ParsedProduct]:
    """Авито хранит данные листингов в URI-encoded window.__initialData__."""
    m = _INIT_DATA_RE.search(html)
    if m:
        try:
            data = json.loads(unquote(m.group(1)))
            products = _items_from_data(data, limit)
            if products:
                return products
        except (json.JSONDecodeError, ValueError):
            pass

    # Фолбэк: <script type="application/json"> блоки
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/json"):
        try:
            data = json.loads(script.string or "")
            products = _items_from_data(data, limit)
            if products:
                return products
        except (json.JSONDecodeError, TypeError):
            continue

    return []


def _items_from_data(data: object, limit: int) -> list[ParsedProduct]:
    """Обходим JSON в поиске массива листингов по типичным путям Авито."""
    if not isinstance(data, dict):
        return []

    items = (
        _deep_get(data, "catalog", "items")
        or _deep_get(data, "data", "catalog", "items")
        or data.get("items")
        or []
    )

    if not isinstance(items, list) or not items:
        return []

    products = []
    for item in items[:limit]:
        if isinstance(item, dict):
            p = _product_from_json(item)
            if p:
                products.append(p)
    return products


def _product_from_json(item: dict) -> ParsedProduct | None:
    try:
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            return None

        title = (item.get("title") or "").strip()
        if not title:
            return None

        # Цена в рублях — несколько вариантов вложенности
        price_val = (
            _deep_get(item, "priceDetailed", "value")
            or _deep_get(item, "price", "value")
            or item.get("price")
        )
        if price_val is None:
            return None
        price_kopecks = _to_kopecks(price_val)
        if price_kopecks is None:
            return None

        url_path = item.get("urlPath") or item.get("url") or ""
        url = f"{_BASE_URL}{url_path}" if url_path.startswith("/") else url_path
        if not url:
            return None

        # Картинка: images[0] может быть строкой или dict с размерами
        image_url = _first_image(item.get("images") or item.get("image"))

        # Состояние: ищем в params [{title: "Состояние", value: "Б/у"}]
        condition = _extract_condition(item.get("params") or [])

        # Тип продавца
        seller = item.get("seller") or {}
        seller_type = _seller_type(seller.get("type") or seller.get("accountType") or "")

        # Локация
        geo = item.get("geo") or item.get("location") or {}
        location: str | None = None
        if isinstance(geo, dict):
            location = geo.get("name") or geo.get("city") or geo.get("region")

        return ParsedProduct(
            store_slug="avito",
            external_id=item_id,
            title=title,
            price=price_kopecks,
            url=url,
            image_url=image_url,
            raw={
                "condition": condition,
                "location": location,
                "seller_type": seller_type,
                "in_stock": True,
            },
        )
    except (TypeError, AttributeError, ValueError):
        return None


# ── HTML-фолбэк ───────────────────────────────────────────────────────────

def _from_html(html: str, limit: int) -> list[ParsedProduct]:
    """Парсинг через data-marker и itemprop атрибуты."""
    soup = BeautifulSoup(html, "html.parser")
    els = soup.select("[data-marker='item']")[:limit]
    products = []
    for el in els:
        p = _product_from_html(el)
        if p:
            products.append(p)
    return products


def _product_from_html(el) -> ParsedProduct | None:
    try:
        link = (
            el.select_one("a[data-marker='item-title']")
            or el.select_one("a[itemprop='url']")
            or el.select_one("h3 a")
        )
        if not link:
            return None
        href = link.get("href", "")
        m = _ID_RE.search(href)
        if not m:
            return None
        item_id = m.group(1)
        url = f"{_BASE_URL}{href}" if href.startswith("/") else href

        # Заголовок
        title_el = el.select_one("[itemprop='name']") or link
        title = (title_el.get("content") or title_el.get_text(strip=True)).strip()
        if not title:
            return None

        # Цена: предпочитаем meta[itemprop="price"] (машиночитаемо)
        price_meta = el.select_one("meta[itemprop='price']")
        raw_price = price_meta.get("content") if price_meta else None
        if not raw_price:
            price_el = (
                el.select_one("[data-marker='item-price']")
                or el.select_one("[itemprop='price']")
            )
            raw_price = price_el.get_text(strip=True) if price_el else None
        price_kopecks = _to_kopecks(raw_price)
        if price_kopecks is None:
            return None

        # Картинка
        img_el = el.select_one("img[itemprop='image']") or el.select_one("img")
        image_url = None
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src")
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url

        # Адрес
        location_el = (
            el.select_one("[data-marker='item-address']")
            or el.select_one("[class*='geo']")
        )
        location = location_el.get_text(strip=True) if location_el else None

        return ParsedProduct(
            store_slug="avito",
            external_id=item_id,
            title=title,
            price=price_kopecks,
            url=url,
            image_url=image_url,
            raw={
                "condition": None,    # недоступно в HTML без enrich
                "location": location,
                "seller_type": None,
                "in_stock": True,
            },
        )
    except (AttributeError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _deep_get(d: dict, *keys) -> object:
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _to_kopecks(value: object) -> int | None:
    """Конвертирует цену (рубли, строка или число) в копейки."""
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    if not digits:
        return None
    return int(digits) * 100


def _first_image(images: object) -> str | None:
    """Извлекает URL первой картинки из разных форматов avito."""
    if not images:
        return None
    if isinstance(images, str):
        return images
    if isinstance(images, list) and images:
        img = images[0]
        if isinstance(img, str):
            return img
        if isinstance(img, dict):
            return (
                img.get("864x648") or img.get("432x324")
                or img.get("640x480") or next(iter(img.values()), None)
            )
    if isinstance(images, dict):
        return (
            images.get("864x648") or images.get("432x324")
            or next(iter(images.values()), None)
        )
    return None


def _extract_condition(params: list) -> str | None:
    for p in params:
        if not isinstance(p, dict):
            continue
        if p.get("title", "").lower() in ("состояние", "condition"):
            val = p.get("value", "").lower()
            if "б/у" in val or "used" in val or "бу" in val:
                return "used"
            if "нов" in val or "new" in val:
                return "new"
    return None


def _seller_type(raw: str) -> str | None:
    low = raw.lower()
    if not low:
        return None
    if any(w in low for w in ("shop", "company", "магазин", "компания", "организация")):
        return "shop"
    return "private"
