"""Парсер OnlineTrade (onlinetrade.ru) — через browser-service.

**Почему browser-as-a-service.** Сайт защищён через **ServicePipe**
(`servicepipe.ru`), российский WAF уровня DataDome/Akamai. Прямой
HTTP-запрос (curl, httpx, curl-cffi) возвращает ~2KB заглушку — спиннер с
JS-скриптами fingerprint'инга и Proof-of-Work challenge'а, который **обязан**
быть исполнен браузером для получения валидных cookies (`spcheck`, `sp_*`).
Только после успеха появляется реальная SSR-выдача.

Probe-эксперимент 2026-05-16 показал:
* ``curl`` → 200 OK, но body = JS spinner page с ``servicepipe.ru/static/fp.min.js``,
  ``jsrsasign-all-min.js``, ``checkjs/<hash>.js`` — challenge JS,
  без выполнения которого следующего запроса не будет.
* HTML challenge содержит ``get_cookie_spsn()`` / ``get_cookie_spid()``
  hardcoded в JS — серверный «вызов», на который браузер должен
  «ответить» POST'ом на ``/xpvnsulc/?back_location=...``.
* Браузер пользователя (с пройденным challenge) → реальная страница поиска.

Архитектура — клон Ozon-паттерна (см. ``ozon.py``):

1. **Запросы через ``BrowserClient.fetch``** с ``profile_id="onlinetrade"``.
   Camoufox в persistent-context'е накапливает cookies в
   ``/data/profiles/onlinetrade`` между запросами — после первого challenge
   следующие проходят моментально.
2. **Warmup loop** в ``lifespan`` каждые ``ONLINETRADE_WARMUP_INTERVAL_MINUTES``
   делает «холостой» fetch на главную, чтобы профиль не остыл и первый
   user-запрос был warm. Cold ~10-15s (challenge), warm ~2-4s.
3. **Парсинг — SSR HTML** через regex по карточкам товара. Якорь —
   URL вида ``/<category>/.../<numeric-id>.html``, цена в рублях
   (``₽`` или «руб.»), title — длинный кириллический text-node.

**Стратегия search-only**, без enrich. URL поиска:
``https://www.onlinetrade.ru/search.html?search=<query>`` — сквозной
поиск по сайту, без категорийной фильтрации (как WB).

**Важно для будущей сессии:** на момент написания (2026-05-16) browser-service
был временно сломан (Camoufox ``new_context()`` в ARM64 docker —
см. memory ``project_browser_service_camoufox_issue.md``). Парсер написан
по образцу Ozon и юнитов-тестируется на mock'ах; реальные HTML-селекторы
(_LINK_RE, _PRICE_RE, _TITLE_RE) подобраны по эвристикам и могут потребовать
корректировки после первого реального запроса через починенный browser-service.
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

logger = logging.getLogger(__name__)

_BASE = "https://www.onlinetrade.ru"
_PROFILE_ID = "onlinetrade"

# Селектор появления реального контента после прохождения challenge.
# onlinetrade использует традиционный SSR с классом `.indexGoods__item`
# для карточек поисковой выдачи. Покрываем и альтернативные классы для
# страховки на случай изменения вёрстки.
_WAIT_SELECTOR = (
    '.indexGoods__item, .productLine, '
    '[itemprop="itemListElement"], .b-product__list-item'
)
# Дефолтные таймауты с учётом cold-start через Camoufox и ServicePipe challenge.
_FETCH_TIMEOUT_MS = 60_000
_WAIT_FOR_SELECTOR_TIMEOUT_MS = 45_000


class OnlineTradeParser(StoreParser):
    """L2-парсер OnlineTrade: один запрос через browser-service → парсинг SSR.

    Зависит от ``BrowserClient``. Если ``browser_client is None`` (browser-service
    не запущен), ``search()`` падает с ``RuntimeError`` — graceful degradation
    через ``SearchResult.errors`` на стороне ``PriceService``.
    """

    store = StoreInfo(slug="onlinetrade", name="OnlineTrade", base_url=_BASE)

    def __init__(self, browser_client: BrowserClient | None) -> None:
        super().__init__()
        self._browser_client = browser_client

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        self._http_counter = 0
        self.last_metrics = None

        if self._browser_client is None:
            raise RuntimeError(
                "OnlineTrade: browser-service не подключён (BROWSER_SERVICE_URL пуст). "
                "Запусти `docker compose --profile browser up -d browser`."
            )

        url = f"{_BASE}/search.html?search={quote_plus(query)}"

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
            raise RuntimeError(
                f"OnlineTrade: browser-service {exc.status_code} — {exc.detail}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"OnlineTrade: {exc}") from exc
        search_ms = int((time.monotonic() - t0) * 1000)
        self._http_counter = 1

        html = result.get("html") or ""
        if not html:
            raise RuntimeError("OnlineTrade: browser-service вернул пустой HTML")

        # Сигнал «ServicePipe challenge не пройден»: страница содержит загрузочный
        # JS-bundle вместо реальной выдачи. `servicepipe.ru/static/fp.min.js`
        # — стабильный маркер, присутствует только в challenge-page'е.
        if "servicepipe.ru/static/fp" in html or "id_captcha_frame_div" in html:
            raise RuntimeError(
                "OnlineTrade: ServicePipe challenge не пройден (профиль остыл?). "
                "Проверь browser-service и BROWSER_BACKEND."
            )

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

# Якорь карточки товара. У onlinetrade URL'ы товаров заканчиваются на
# `.html` и содержат числовой ID перед расширением (исторически
# product-id). Допускаем как абсолютные `https://www.onlinetrade.ru/...`,
# так и относительные `/...` пути.
#
# Примеры:
#   /igry/.../nastolnaya_igra_karkasson-1234567.html
#   /category/subcategory/.../slug_with_id-987654.html
#
# Группа 1 — относительный путь, группа 2 — численный id.
_LINK_RE = re.compile(
    r'<a [^>]*?href="(?:https?://(?:www\.)?onlinetrade\.ru)?'
    r'(/[a-z0-9_\-/]+?-(\d{4,10})\.html)[^"]*"',
    re.IGNORECASE,
)
# Цена в рублях. onlinetrade использует два варианта: «1 990 руб.» (SSR) и
# «1 990 ₽» (некоторые виджеты). Группа 1 — число с разделителями.
# Внутри числа допускаем ТОЛЬКО обычный пробел и nbsp (`\xa0`) как
# разделители тысяч — без `\s`, иначе regex прыгает через `\n`/`\t`
# и склеивает числа из соседних HTML-строк (например, «1234» из одного
# тега + «5 руб.» из другого = матч «12345 руб.», ложная цена).
_PRICE_RE = re.compile(
    r"([\d\xa0 ]{1,10})\s*(?:руб\.?|₽)",
    re.IGNORECASE,
)
# Title: длинный кириллический text-node, как у Ozon. Должен начинаться с
# заглавной буквы (А-Я/Ё), длина 14-200 символов.
_TITLE_RE = re.compile(
    r'>([А-ЯЁ][А-ЯЁа-яёA-Za-z0-9\s\-:,.()/«»–—!]{14,200})<'
)
# Image — onlinetrade использует свой CDN (preview.onlinetrade.ru, static),
# покрываем универсально по расширению.
_IMG_RE = re.compile(
    r'<img[^>]+src="(https?://[^"]*onlinetrade[^"]+\.(?:jpg|jpeg|png|webp))"',
    re.IGNORECASE,
)
# Brand: латинский text-node 2-30 символов, первая буква капс.
_BRAND_RE = re.compile(r'>([A-Z][A-Za-z\s&\-]{1,29})<')


def _parse_price_kopecks(price_text: str) -> int:
    """«1 990» (с nbsp/space разделителем тысяч) → 199000 копеек.

    Поддерживает форматы «1 990», «1\xa0990» (nbsp), «1990». Если входная
    строка содержит не только цифры/пробелы — возвращает 0 (защита от
    ложных регексп-срабатываний на тексте вроде «999 знаков»).
    """
    digits = re.sub(r"[\s\xa0]", "", price_text)
    if not digits.isdigit():
        return 0
    return int(digits) * 100


def _parse_cards(html: str, *, limit: int) -> list[ParsedProduct]:
    """Извлечь карточки товара из SSR HTML страницы поиска.

    Алгоритм идентичен Ozon-парсеру: делим HTML на сегменты по якорю
    ``<a href="/.../<numeric-id>.html">``, каждому уникальному id —
    один сегмент (область карточки), внутри ищем цены/title/image/brand.

    Зачем regex, а не BeautifulSoup: CSS-классы у onlinetrade могут
    меняться между релизами (``.indexGoods__item`` сегодня → ``.product-card``
    завтра), но стабильны: ссылка на товар с числовым id и `.html`, символ
    цены (``руб.``/``₽``), и CDN-домены изображений. Парсим по ним.
    """
    # Шаг 1: найти offsets всех первых появлений товаров
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
            # (без цены или без title). Тройной buffer обычно достаточен.
            break

    products: list[ParsedProduct] = []
    for i, (offset, path, product_id) in enumerate(card_starts):
        # Сегмент карточки: от offset до начала следующей уникальной
        # ссылки или +5KB как fallback (последняя карточка на странице).
        end = card_starts[i + 1][0] if i + 1 < len(card_starts) else min(
            len(html), offset + 5000
        )
        chunk = html[offset:end]

        # Цены: первая = текущая, вторая (если больше) = до скидки.
        price_matches = _PRICE_RE.findall(chunk)
        prices = [_parse_price_kopecks(p) for p in price_matches]
        prices = [p for p in prices if p > 0]
        if not prices:
            continue
        price = prices[0]

        original_price: int | None = None
        for p in prices[1:]:
            if p > price:
                original_price = p
                break

        # Title: первый длинный кириллический text-node. Fallback на slug,
        # если карточка идёт «без видимого названия» (например, hot-deal
        # блок только с ценой + brand-логотипом).
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

        # У onlinetrade URL может быть относительным — нормализуем к абсолютному.
        full_url = path if path.startswith("http") else f"{_BASE}{path}"

        products.append(
            ParsedProduct(
                store_slug="onlinetrade",
                external_id=product_id,
                title=title,
                price=price,
                url=full_url,
                image_url=image_url,
                raw=_build_raw(brand=brand, original_price=original_price),
            )
        )
        if len(products) >= limit:
            break
    return products


def _title_from_slug(path: str) -> str | None:
    """Fallback: восстановить читаемый title из URL-slug.

    Используется когда в SSR-карточке первый text-node — это brand или
    другое короткое значение, а не название товара.
    ``/igry/.../nastolnaya_igra_karkasson-1234567.html`` →
    «Nastolnaya Igra Karkasson». Не идеально, но лучше пропуска товара.
    """
    m = re.match(r"/.*?/([a-z0-9_\-]+)-\d+\.html$", path)
    if not m:
        return None
    slug = m.group(1)
    # onlinetrade использует «_» как разделитель слов в slug (исторически),
    # но допускаются и «-» — разделяем по обоим.
    words = [w for w in re.split(r"[_\-]", slug) if w and not w.isdigit()]
    if not words:
        return None
    return " ".join(w.capitalize() for w in words)


def _build_raw(*, brand: str | None, original_price: int | None) -> dict:
    """Поля для ParsedProduct.raw → catalog ingest.

    Минимальный набор: ``in_stock`` (True по умолчанию — search-выдача
    onlinetrade обычно не включает out-of-stock; при необходимости позже
    можно подтянуть из карточки), ``brand``, ``original_price``.
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
    """Интервал warmup loop (в секундах). Default — 30 минут.

    Чуть короче, чем у Ozon (60 мин) — ServicePipe ротирует токены
    агрессивнее, чем Ozon-antibot. 30 мин — компромисс между нагрузкой
    на сайт и шансом cold-start'а при первом user-запросе.
    """
    raw = os.getenv("ONLINETRADE_WARMUP_INTERVAL_MINUTES", "30").strip()
    try:
        minutes = int(raw)
    except ValueError:
        logger.warning(
            "[OnlineTrade] ONLINETRADE_WARMUP_INTERVAL_MINUTES=%r не int, "
            "использую 30",
            raw,
        )
        minutes = 30
    return max(5, minutes) * 60  # минимум 5 минут — защита от частых вызовов


async def warmup_once(browser_client: BrowserClient) -> bool:
    """Один цикл warmup: «зайти на onlinetrade.ru с profile_id=onlinetrade».

    Не парсит контент — только держит persistent profile тёплым, чтобы
    первый user-запрос на /search.html?... был warm. Возвращает True при
    успехе, False иначе (для логирования; ошибка не выбрасывается —
    это background-loop).
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
        logger.warning("[OnlineTrade] warmup_once failed: %s", exc)
        return False
