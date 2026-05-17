"""Парсер Wildberries (wildberries.ru).

Использует публичный JSON API ``search.wb.ru/exactmatch/ru/common/v5/search`` —
тот же, который дёргает фронт WB после загрузки страницы. Endpoint возвращает
до 100 товаров за один запрос: pagination для нашей задачи (top-N товаров
по запросу) не нужна.

**Защита WB.** Запросы из DC-IP периодически ловят 429/403 от Angie (форк
nginx у WB). `curl-cffi` с TLS-impersonation Chrome 124 проходит rate-limit
заметно чаще, чем vanilla `httpx` — поэтому он default. Backend pluggable:

* ``WB_BACKEND`` env: ``httpx`` | ``curl-cffi`` (default).
* Override на лету для отладки: query-параметр ``wb_backend=...`` в
  ``/api/debug/parse``.

**Категория «Настольные игры».** Серверный фильтр ``xsubject=1144`` сам по
себе ловит 429 чаще запроса без него, поэтому мы делаем **soft twin-search**:
один HTTP-запрос → локальная фильтрация по ``subjectId=120`` («Настольные
игры»). Если после фильтра меньше ``limit`` — берём все, без фильтра. Это
экономит второй HTTP без жертв качества: для типичных board-game запросов
WB сам ранжирует настолки выше.

Стратегия минимальная: search-only, без обогащения со страницы товара
(Q2=a). Если позже понадобятся `description`/`players` — добавится
`_enrich()` через ``card.wb.ru/cards/v{N}/detail`` (см. roadmap [PRS-5]).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Literal
from urllib.parse import quote_plus, urlencode

from ..base import ParserMetrics, StoreParser
from ..models import ParsedProduct, StoreInfo

logger = logging.getLogger(__name__)

_BASE = "https://www.wildberries.ru"
_SEARCH_HOST = "https://search.wb.ru"

# subjectId «Настольные игры» в классификаторе WB.
# Подтверждён probe-скриптом — все игры серии Каркассон шли с subjectId=120.
_BOARDGAMES_SUBJECT_ID = 120

# WB поддерживает несколько версий API параллельно. v5 — стабильная legacy
# без preset-routing (v8+ редиректят через preset, что требует второго
# запроса к catalog.wb.ru — а тот блокирует DC-IP сильнее).
_DEFAULT_VERSION = "v5"

# Базовые параметры запроса (общие для всех вызовов).
# `dest=-1257786` — геокод доставки (МСК); это обязательный параметр, без
# него WB отвечает 400. Любой валидный регион подходит — нам важен только
# факт его наличия.
_BASE_PARAMS = {
    "ab_testing": "false",
    "appType": "1",
    "curr": "rub",
    "dest": "-1257786",
    "lang": "ru",
    "resultset": "catalog",
    "sort": "popular",
    "spp": "30",
    "suppressSpellcheck": "false",
}

# Заголовки, имитирующие фронт WB. Sec-Ch-* hints помогают пройти Angie на
# DC-IP — без них блокировка наступает быстрее.
_HEADERS_BASE = {
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Origin": _BASE,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

Backend = Literal["httpx", "curl-cffi"]


class WildberriesParser(StoreParser):
    """L0-парсер WB через публичный JSON. Один HTTP-запрос на поиск.

    Параметры:
      backend: ``"httpx"`` (vanilla) или ``"curl-cffi"`` (TLS-impersonation).
        Default берётся из env ``WB_BACKEND``, фолбэк — ``"curl-cffi"``.
      api_version: ``"v4"`` / ``"v5"``. Default — env ``WB_API_VERSION`` или ``"v5"``.

    Pluggable конструктор позволяет на лету тестировать обе ветки в
    ``/api/debug/parse?wb_backend=httpx`` — это нужно для регресса
    «когда WB ослабит rate-limit, можно вернуться на vanilla httpx».
    """

    store = StoreInfo(slug="wildberries", name="Wildberries", base_url=_BASE)

    def __init__(
        self,
        backend: Backend | None = None,
        api_version: str | None = None,
    ) -> None:
        super().__init__()
        self.backend: Backend = backend or _resolve_backend()
        self.api_version: str = api_version or os.getenv("WB_API_VERSION", _DEFAULT_VERSION)

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        self._http_counter = 0
        self.last_metrics = None

        url = self._build_url(query)
        headers = {
            **_HEADERS_BASE,
            # Referer должен совпадать с URL страницы поиска у юзера —
            # без него Angie помечает запрос как «голый XHR».
            "Referer": f"{_BASE}/catalog/0/search.aspx?search={quote_plus(query)}",
        }

        t0 = time.monotonic()
        try:
            payload = await self._fetch_json(url, headers)
        except Exception as exc:
            raise RuntimeError(f"Wildberries: {exc}") from exc
        search_ms = int((time.monotonic() - t0) * 1000)
        self._http_counter = 1

        items = _extract_products(payload)
        products = _build_products(items, limit=limit)

        self.last_metrics = ParserMetrics(
            search_ms=search_ms,
            enrich_ms=None,
            http_requests=self._http_counter,
            result_after_enrich=len(products),
        )
        return products

    def _build_url(self, query: str) -> str:
        params = {**_BASE_PARAMS, "query": query}
        return f"{_SEARCH_HOST}/exactmatch/ru/common/{self.api_version}/search?" + urlencode(params)

    async def _fetch_json(self, url: str, headers: dict) -> dict:
        """Дёргает search-API. При 429 один раз ретраит через 2 сек.

        Angie у WB периодически возвращает 429 на холодные TLS-handshake'и
        из DC-IP. Один retry обычно достаточен — WB не банит permanent'но,
        только дросселирует burst. Если и retry не помог — поднимаем выше
        как RuntimeError, его поймает PriceService и запишет в parser_log.
        """
        for attempt in range(2):
            try:
                return await self._fetch_once(url, headers)
            except _RateLimited:
                if attempt == 1:
                    raise RuntimeError("HTTP 429 (rate-limited даже после retry)")
                logger.info("[WB] HTTP 429 — retry через 2 сек")
                await asyncio.sleep(2)
        raise RuntimeError("unreachable")  # для mypy

    async def _fetch_once(self, url: str, headers: dict) -> dict:
        if self.backend == "httpx":
            import httpx

            async with httpx.AsyncClient(timeout=20) as c:
                resp = await c.get(url, headers=headers)
                if resp.status_code == 429:
                    raise _RateLimited()
                if resp.is_error:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                return resp.json()

        # curl-cffi: AsyncSession с TLS-impersonation Chrome 124.
        from curl_cffi.requests import AsyncSession

        async with AsyncSession(impersonate="chrome124") as s:
            resp = await s.get(url, headers=headers, timeout=20)
            if resp.status_code == 429:
                raise _RateLimited()
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            return resp.json()


class _RateLimited(Exception):
    """Внутренний сигнал «HTTP 429» — отдельный тип, чтобы retry-логика не
    путала его с другими ошибками сети."""


def _resolve_backend() -> Backend:
    """`WB_BACKEND` env: default curl-cffi (TLS-imp проходит rate-limit чаще)."""
    raw = (os.getenv("WB_BACKEND") or "curl-cffi").strip().lower()
    if raw in ("httpx", "curl-cffi"):
        return raw  # type: ignore[return-value]
    logger.warning("[WB] WB_BACKEND=%r не распознан, использую curl-cffi", raw)
    return "curl-cffi"


def _extract_products(payload: dict) -> list[dict]:
    """v4/v5 кладут products на root; v8+ иногда в data.products."""
    items = payload.get("products") or (payload.get("data") or {}).get("products") or []
    return items if isinstance(items, list) else []


def _parse_price_kopecks(item: dict) -> int:
    """Цена в копейках. WB уже хранит в копейках (rub × 100), конвертация не нужна.

    Современная схема — ``sizes[0].price.{product, total, basic}``.
    Legacy fields — ``salePriceU`` / ``priceU``.
    """
    sizes = item.get("sizes")
    if isinstance(sizes, list) and sizes and isinstance(sizes[0], dict):
        price = sizes[0].get("price")
        if isinstance(price, dict):
            for key in ("product", "total", "basic"):
                val = price.get(key)
                if isinstance(val, (int, float)) and val > 0:
                    return int(val)
    for key in ("salePriceU", "priceU"):
        val = item.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    return 0


def _build_products(items: list[dict], *, limit: int) -> list[ParsedProduct]:
    """Strict-фильтр: оставляем ТОЛЬКО товары с `subjectId=120` (Настольные игры).

    Раньше работал «soft twin-search»: при недоборе по subjectId=120 добивали
    общей выдачей. Но это запускало мусор (детскую одежду, посуду) в матчинг
    catalog'а — LLM проставлял auto-match на похожие заголовки. Согласно
    задаче от 2026-05-18 фильтр сделан строгим: лучше вернуть пусто, чем
    запутать matching.

    WB сам ранжирует релевантное выше, поэтому top-100 общей выдачи на
    запрос «Каркассон» = почти всё subjectId=120. На общих запросах
    («дочка играет», «подарок мужу») вернётся 0 — это корректно для
    источника настолок.
    """
    products: list[ParsedProduct] = []
    seen: set[str] = set()

    for raw in items:
        if not isinstance(raw, dict):
            continue
        if raw.get("subjectId") != _BOARDGAMES_SUBJECT_ID:
            continue
        item_id = str(raw.get("id") or "")
        if not item_id or item_id in seen:
            continue
        title = (raw.get("name") or "").strip()
        if not title:
            continue
        price = _parse_price_kopecks(raw)
        if price <= 0:
            continue

        seen.add(item_id)
        products.append(ParsedProduct(
            store_slug="wildberries",
            external_id=item_id,
            title=title,
            price=price,
            url=f"{_BASE}/catalog/{item_id}/detail.aspx",
            image_url=None,  # умышленно — пользователь не запросил, экономим bandwidth
            raw=_build_raw(raw),
        ))
        if len(products) >= limit:
            break

    return products


def _build_raw(item: dict) -> dict:
    """Поля, которые имеет смысл сохранять в ParsedProduct.raw."""
    raw: dict = {"in_stock": True}
    if item.get("brand"):
        raw["brand"] = item["brand"]
    subject_id = item.get("subjectId")
    if isinstance(subject_id, int):
        raw["subject_id"] = subject_id
    rating = item.get("reviewRating") or item.get("rating")
    if isinstance(rating, (int, float)) and rating > 0:
        raw["rating"] = rating
    feedbacks = item.get("feedbacks")
    if isinstance(feedbacks, int) and feedbacks > 0:
        raw["feedbacks"] = feedbacks
    return raw
