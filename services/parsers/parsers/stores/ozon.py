"""Парсер Ozon (ozon.ru) — через browser-service.

**Почему browser-as-a-service.** Ozon защищает фронт **Antibot Challenge Page**
(внутреннее имя ``fab_chlg_*``): обфусцированный JS собирает device fingerprint
(``window.crypto``, ``getComputedStyle``, измерения шрифтов) и решает proof-of-work
challenge, после чего выставляет cookies. **Без JS-runtime не пройти.**

Probe-эксперимент 2026-05-15 показал:
* ``curl`` / ``httpx`` → 307 с self-redirect ``__rr=N`` (бесконечный bounce).
* ``curl-cffi`` (TLS-impersonation Chrome 124) → 403 + 106KB challenge HTML.
* ``api.ozon.ru/composer-api.bx/*`` с cookies от Camoufox → **тоже 403** —
  Ozon antibot верифицирует TLS+behavioural+cookies в комплексе, одних
  cookies недостаточно для прохода.
* **Camoufox через browser-service → 200**, страница ``/category/nastolnye-i-kartochnye-igry-13506/``
  (Ozon сам угадывает категорию по query через ``category_was_predicted=true``).

Поэтому архитектура **C'** (compromise hybrid):

1. **Запросы идут через ``BrowserClient.fetch``** с ``profile_id="ozon"``
   (persistent profile). Camoufox сам решает challenge и накапливает cookies/
   localStorage в ``/data/profiles/ozon`` между запросами.
2. **Warmup loop** в ``lifespan`` каждые ``OZON_WARMUP_INTERVAL_MINUTES``
   делает «холостой» fetch на главную, чтобы профиль не остыл и первый
   юзерский запрос был warm. Cold ~10-12s, warm ~3-5s.
3. **Парсинг — SSR HTML** через regex по карточкам товара.
   ``window.__NUXT__.state`` содержит только метаданные страницы (requestID,
   layout, seo, location), сам список товаров встроен в HTML SSR-карточки.

**Стратегия search-only**, без enrich (как у WB). При желании добавить
``description``/``players`` — отдельный proxy через browser-service на
``/product/<slug>/``.

**Фильтр по категории (2026-05-18)**. Раньше использовался `/search/?text=`
с расчётом на Ozon category-prediction — но он срабатывает только для
«узких» query («Каркассон»). На общих query («книга», «подарок») Ozon
возвращает разнородный мусор (probe 2026-05-18 на «книга» отдал 5/5 книг).
Этот мусор шёл в `catalog`, LLM-арбитр иногда матчил по схожести с
названиями игр. Чтобы исключить это, поиск идёт **внутри категории
«Настольные и карточные игры» (id=13506)**:

    https://www.ozon.ru/category/nastolnye-i-kartochnye-igry-13506/?text=<q>

Если query не имеет настолок — Ozon вернёт пустую выдачу. Это корректно.
"""
from __future__ import annotations

import logging
import os
import re
import time
from urllib.parse import quote_plus

from ..base import ParserMetrics, StoreParser
from ..browser_client import BrowserClient, BrowserServiceError
from ..models import ParsedProduct, StoreInfo
from ..utils.breaker import get_breaker

logger = logging.getLogger(__name__)

_BASE = "https://www.ozon.ru"
_PROFILE_ID = "ozon"
# Slug+id категории «Настольные и карточные игры». Сам Ozon формирует URL вида
# `/category/<slug>-<id>/?text=...` — стабильный паттерн уже годы.
_BOARDGAMES_CATEGORY_PATH = "category/nastolnye-i-kartochnye-igry-13506"

# Селектор появления реального контента после прохождения challenge.
# `tileGridDesktop` — стандартный widget грид-карточек на /search и /category страницах.
_WAIT_SELECTOR = '[data-widget="searchResultsV2"], [data-widget="tileGridDesktop"]'
# Дефолтные таймауты с учётом cold-start через Camoufox.
_FETCH_TIMEOUT_MS = 60_000
_WAIT_FOR_SELECTOR_TIMEOUT_MS = 45_000


class OzonParser(StoreParser):
    """L1-парсер Ozon: один запрос через browser-service → парсинг SSR-карточек.

    Зависит от ``BrowserClient``. Если ``browser_client is None`` (browser-service
    не запущен), ``search()`` падает с ``RuntimeError`` — graceful degradation
    через ``SearchResult.errors`` на стороне ``PriceService``.
    """

    store = StoreInfo(slug="ozon", name="Ozon", base_url=_BASE)

    def __init__(self, browser_client: BrowserClient | None) -> None:
        super().__init__()
        self._browser_client = browser_client

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        self._http_counter = 0
        self.last_metrics = None

        if self._browser_client is None:
            raise RuntimeError(
                "Ozon: browser-service не подключён (BROWSER_SERVICE_URL пуст). "
                "Запусти `docker compose --profile browser up -d browser`."
            )

        # PRS-7: per-store breaker. Ozon antibot challenge может зависнуть
        # на минуты — fail-fast вместо 12с timeout'а на каждый запрос.
        breaker = get_breaker("ozon")
        if not breaker.is_available():
            raise RuntimeError(
                f"Ozon: circuit breaker открыт до {breaker.opens_until_iso} "
                f"(antibot/timeout паттерн)"
            )

        # Поиск внутри категории «Настольные и карточные игры» (вместо
        # глобального /search/?text=) — отсекает книги/одежду/посуду
        # с похожими словами в названии. См. docstring модуля.
        url = f"{_BASE}/{_BOARDGAMES_CATEGORY_PATH}/?text={quote_plus(query)}&from_global=true"

        t0 = time.monotonic()
        try:
            result = await self._browser_client.fetch(
                url=url,
                wait_until="domcontentloaded",
                timeout_ms=_FETCH_TIMEOUT_MS,
                wait_for_selector=_WAIT_SELECTOR,
                wait_for_selector_timeout_ms=_WAIT_FOR_SELECTOR_TIMEOUT_MS,
                stealth=True,
                profile_id=_PROFILE_ID,
            )
        except BrowserServiceError as exc:
            breaker.record_failure(f"browser-service {exc.status_code}")
            raise RuntimeError(f"Ozon: browser-service {exc.status_code} — {exc.detail}") from exc
        except Exception as exc:
            breaker.record_failure(str(exc)[:200])
            raise RuntimeError(f"Ozon: {exc}") from exc
        search_ms = int((time.monotonic() - t0) * 1000)
        # Считаем один внешний HTTP-вызов: внутри browser-service ходит много,
        # но с точки зрения нашего сервиса это один запрос к downstream.
        self._http_counter = 1

        html = result.get("html") or ""
        if not html:
            breaker.record_failure("empty HTML")
            raise RuntimeError("Ozon: browser-service вернул пустой HTML")

        # Сигнал «challenge не пройден»: title всё ещё «Antibot Challenge Page».
        if "<title>Antibot Challenge Page</title>" in html:
            breaker.record_failure("antibot challenge")
            raise RuntimeError(
                "Ozon: antibot challenge не пройден (профиль остыл?). "
                "Проверь browser-service и BROWSER_BACKEND."
            )

        # Если дошли сюда — HTML валидный, считаем запрос успешным.
        breaker.record_success()
        products = _parse_cards(html, limit=limit)

        self.last_metrics = ParserMetrics(
            search_ms=search_ms,
            enrich_ms=None,
            http_requests=self._http_counter,
            result_after_enrich=len(products),
        )
        return products


# ---------------------------------------------------------------------------
# Парсинг SSR HTML (module-level, чтобы юнитами тестировать без сети)
# ---------------------------------------------------------------------------

# Якорь карточки товара: <a href="/product/<slug>-<numeric-id>/...">.
# Каждый товар повторяется в HTML 2-3 раза (фото-ссылка + title-ссылка),
# поэтому дедуплицируем по numeric-id (берём первое появление = область карточки).
_LINK_RE = re.compile(
    r'<a [^>]*?href="(/product/[a-z0-9\-]+-(\d+)/)[^"]*"', re.IGNORECASE
)
# Цена в рублях: «1 957», «2 388» (как раз с u00a0 nbsp), затем ' ₽'.
_PRICE_RE = re.compile(r'([\d\s\xa0]{1,10})\s*₽')
# Title — первый длинный кириллический text-node внутри сегмента карточки.
# Должен начинаться с заглавной буквы, длина 14-200 символов.
_TITLE_RE = re.compile(
    r'>([А-ЯЁ][А-ЯЁа-яёA-Za-z0-9\s\-:,.()/«»–—!]{14,200})<'
)
# Image: Ozon hosts on ir.ozone.ru CDN.
_IMG_RE = re.compile(r'<img[^>]+src="(https://ir\.ozone\.ru/[^"]+\.jpg)"')
# Brand: латиница, 2-30 символов, первая буква капс. Часто после цены идёт
# отдельный <span> с brand-name. Эвристика: первый text-node латиницей.
_BRAND_RE = re.compile(r'>([A-Z][A-Za-z\s&\-]{1,29})<')


def _parse_price_kopecks(price_text: str) -> int:
    """«1 957» (с nbsp/space разделителем тысяч) → 195700 копеек."""
    digits = re.sub(r'[\s\xa0]', '', price_text)
    if not digits.isdigit():
        return 0
    # Цены на сайте — в рублях, конвертируем в копейки.
    return int(digits) * 100


def _parse_cards(html: str, *, limit: int) -> list[ParsedProduct]:
    """Извлечь карточки товара из SSR HTML страницы поиска.

    Алгоритм: бьём HTML на сегменты по якорю ``<a href="/product/...-<id>/">``,
    каждому уникальному ``id`` — один сегмент (область карточки = от начала
    ссылки до начала следующей уникальной ссылки или +5KB как fallback).
    Внутри сегмента ищем цены/title/image/brand.

    Зачем такая структура: CSS-классы у Ozon обфусцированы (``c35_3_16-a1``)
    и меняются между релизами. Стабильны только: ссылка на товар, ``ir.ozone.ru``
    image-CDN, символ «₽», и `data-widget` атрибут. Парсим по ним.
    """
    # Шаг 1: найти offsets всех первых-появлений товаров
    seen: set[str] = set()
    card_starts: list[tuple[int, str, str]] = []
    for m in _LINK_RE.finditer(html):
        product_id = m.group(2)
        if product_id in seen:
            continue
        seen.add(product_id)
        card_starts.append((m.start(), m.group(1), product_id))
        if len(card_starts) >= limit * 3:
            # Соберём с запасом — некоторые карточки могут быть отбракованы
            # (без цены/title). Тройной buffer обычно достаточен.
            break

    products: list[ParsedProduct] = []
    for i, (offset, path, product_id) in enumerate(card_starts):
        # Сегмент карточки: от offset до следующего якоря или +5000 байт.
        end = card_starts[i + 1][0] if i + 1 < len(card_starts) else min(len(html), offset + 5000)
        chunk = html[offset:end]

        # Цены: первые два числа перед «₽». В Ozon-карточке:
        # [0] = выделенная цена с Ozon-картой (tsHeadline...)
        # [1] = обычная цена (tsBodyControl...) — выше первой
        # По ТЗ берём [0] как `price`, [1] как `original_price`.
        price_matches = _PRICE_RE.findall(chunk)
        prices = [_parse_price_kopecks(p) for p in price_matches]
        prices = [p for p in prices if p > 0]
        if not prices:
            continue
        price = prices[0]

        # original_price — следующая после price цена, если она больше.
        original_price: int | None = None
        for p in prices[1:]:
            if p > price:
                original_price = p
                break

        # Title: первый длинный кириллический text-node. Edge case: для slug-
        # like-«hobby-world-nastolnaya-igra-karkasson-...» первый long-text
        # может быть не там — fallback на restoring из slug.
        title_match = _TITLE_RE.search(chunk)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = _title_from_slug(path)
        if not title:
            continue

        img_match = _IMG_RE.search(chunk)
        image_url = img_match.group(1) if img_match else None

        brand_match = _BRAND_RE.search(chunk)
        brand = brand_match.group(1).strip() if brand_match else None

        products.append(
            ParsedProduct(
                store_slug="ozon",
                external_id=product_id,
                title=title,
                price=price,
                url=f"{_BASE}{path}",
                image_url=image_url,
                raw=_build_raw(brand=brand, original_price=original_price),
            )
        )
        if len(products) >= limit:
            break
    return products


def _title_from_slug(path: str) -> str | None:
    """Fallback: восстановить читаемый title из URL-slug.

    Используется когда в SSR-карточке первый text-node — это brand или другое
    короткое значение, а не название товара. ``/product/hobby-world-nastolnaya-
    igra-karkasson-192613104/`` → «Hobby World Nastolnaya Igra Karkasson».
    Не идеально для каталога, но лучше пропуска товара.
    """
    m = re.match(r'/product/([a-z0-9\-]+)-\d+/', path)
    if not m:
        return None
    slug = m.group(1)
    words = [w for w in slug.split("-") if w and not w.isdigit()]
    if not words:
        return None
    return " ".join(w.capitalize() for w in words)


def _build_raw(*, brand: str | None, original_price: int | None) -> dict:
    """Поля для ParsedProduct.raw → catalog ingest.

    Минимальный набор: in_stock (всегда True — Ozon не показывает out-of-stock
    в search-выдаче), brand, original_price. Остальное (SKU, rating, отзывы)
    добавится позже, когда станет понятно стабилен ли SSR-парсинг.
    """
    raw: dict = {"in_stock": True}
    if brand:
        raw["brand"] = brand
    if original_price is not None:
        raw["original_price"] = original_price
    return raw


# ---------------------------------------------------------------------------
# Warmup helper
# ---------------------------------------------------------------------------


def warmup_interval_seconds() -> int:
    """Интервал warmup loop (в секундах). Default — 60 минут."""
    raw = os.getenv("OZON_WARMUP_INTERVAL_MINUTES", "60").strip()
    try:
        minutes = int(raw)
    except ValueError:
        logger.warning("[Ozon] OZON_WARMUP_INTERVAL_MINUTES=%r не int, использую 60", raw)
        minutes = 60
    return max(5, minutes) * 60  # минимум 5 минут — защита от частых вызовов


async def warmup_once(browser_client: BrowserClient) -> bool:
    """Один цикл warmup: «зайти на ozon.ru с profile_id=ozon», подтянуть cookies.

    Не парсит контент — только держит persistent profile тёплым, чтобы первый
    user-запрос на /search/ был warm. Возвращает True при успехе, False иначе
    (для логирования; ошибка не выбрасывается — это background-loop).
    """
    try:
        await browser_client.fetch(
            url=f"{_BASE}/",
            wait_until="domcontentloaded",
            timeout_ms=_FETCH_TIMEOUT_MS,
            stealth=True,
            profile_id=_PROFILE_ID,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Ozon] warmup_once failed: %s", exc)
        return False
