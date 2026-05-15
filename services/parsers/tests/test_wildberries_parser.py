"""Smoke-тесты WildberriesParser.

Сеть не трогаем — патчим `_fetch_json` чтобы он возвращал preset-payload.
Цель — поймать регрессии в:
  - _extract_products (root.products vs data.products)
  - _parse_price_kopecks (sizes[].price vs salePriceU)
  - soft twin-search (subjectId=120 → fallback)
  - resolve backend через env
"""
from __future__ import annotations

import pytest

from parsers.stores.wildberries import (
    WildberriesParser,
    _build_products,
    _extract_products,
    _parse_price_kopecks,
    _resolve_backend,
)


# ---------------------------------------------------------------------------
# Payload fixture (упрощённый ответ search.wb.ru v5)
# ---------------------------------------------------------------------------

# 4 настолки + 2 «мусора» (кроссовки, постеры) — чтобы проверить twin-search.
_PAYLOAD = {
    "products": [
        # boardgame #1 — современная схема sizes[].price.product
        {
            "id": 152304970, "name": "Настольная игра Каркассон",
            "brand": "Hobby World", "subjectId": 120, "rating": 5, "feedbacks": 412,
            "sizes": [{"price": {"basic": 250000, "product": 205200, "total": 205200}}],
        },
        # boardgame #2 — legacy salePriceU
        {
            "id": 152304969, "name": "Каркассон. Королевский подарок",
            "brand": "Hobby World", "subjectId": 120, "rating": 4,
            "salePriceU": 411400,
        },
        # boardgame #3
        {
            "id": 158083432, "name": "Каркассон Таверны и соборы",
            "brand": "Hobby World", "subjectId": 120,
            "sizes": [{"price": {"product": 153700}}],
        },
        # мусор: кроссовки
        {
            "id": 999111, "name": "Кроссовки Каркассон",
            "brand": "Nike", "subjectId": 105,
            "sizes": [{"price": {"product": 700000}}],
        },
        # boardgame #4
        {
            "id": 158083426, "name": "Каркассон Мосты и базары",
            "subjectId": 120, "salePriceU": 153700,
        },
        # мусор: постер
        {
            "id": 888222, "name": "Постер Каркассон HD",
            "subjectId": 4234,
            "sizes": [{"price": {"product": 50000}}],
        },
    ],
}


class _FakeWildberriesParser(WildberriesParser):
    """Подменяет `_fetch_json` на ин-мемори payload — без сети."""

    def __init__(self, payload: dict, **kw) -> None:
        super().__init__(**kw)
        self._payload = payload
        self.calls: list[str] = []

    async def _fetch_json(self, url: str, headers: dict) -> dict:
        self.calls.append(url)
        return self._payload


# ---------------------------------------------------------------------------
# Тесты пайплайна search → ParsedProduct
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_only_boardgames_when_enough():
    """4 настолки в выдаче, limit=3 → возвращаем только настолки (без мусора)."""
    parser = _FakeWildberriesParser(_PAYLOAD)
    products = await parser.search("Каркассон", limit=3)

    assert len(products) == 3
    assert all(p.raw["subject_id"] == 120 for p in products)
    assert {p.title for p in products} == {
        "Настольная игра Каркассон",
        "Каркассон. Королевский подарок",
        "Каркассон Таверны и соборы",
    }


@pytest.mark.asyncio
async def test_soft_twin_search_falls_back_to_all_when_not_enough_boardgames():
    """Только 4 настолки + 2 мусора, limit=5 → добираем мусором, но настолки первыми."""
    parser = _FakeWildberriesParser(_PAYLOAD)
    products = await parser.search("Каркассон", limit=5)

    assert len(products) == 5
    # 4 настолки — в начале (в исходном порядке выдачи)
    assert [p.raw["subject_id"] for p in products[:4]] == [120, 120, 120, 120]
    # пятый — fallback (subj != 120)
    assert products[4].raw["subject_id"] != 120


@pytest.mark.asyncio
async def test_price_mapped_correctly_for_both_schemas():
    """sizes[].price.product и salePriceU оба парсятся в копейки без конвертации."""
    parser = _FakeWildberriesParser(_PAYLOAD)
    products = await parser.search("Каркассон", limit=10)

    by_id = {p.external_id: p for p in products}
    assert by_id["152304970"].price == 205200  # sizes[].price.product
    assert by_id["152304969"].price == 411400  # salePriceU


@pytest.mark.asyncio
async def test_url_built_from_id():
    parser = _FakeWildberriesParser(_PAYLOAD)
    products = await parser.search("Каркассон", limit=1)
    assert products[0].url == "https://www.wildberries.ru/catalog/152304970/detail.aspx"


@pytest.mark.asyncio
async def test_metrics_recorded():
    parser = _FakeWildberriesParser(_PAYLOAD)
    await parser.search("Каркассон", limit=3)
    m = parser.last_metrics
    assert m is not None
    assert m.http_requests == 1
    assert m.enrich_ms is None  # WB — search-only, без enrich
    assert m.result_after_enrich == 3


@pytest.mark.asyncio
async def test_empty_payload_returns_empty():
    parser = _FakeWildberriesParser({"products": []})
    products = await parser.search("Каркассон", limit=5)
    assert products == []


@pytest.mark.asyncio
async def test_skips_items_with_no_price_or_title():
    """Парсер не должен генерировать ParsedProduct без цены или title."""
    payload = {
        "products": [
            {"id": 1, "name": "", "subjectId": 120, "salePriceU": 10000},  # no name
            {"id": 2, "name": "OK", "subjectId": 120},                     # no price
            {"id": 3, "name": "OK2", "subjectId": 120, "salePriceU": 0},   # zero price
            {"id": 4, "name": "Real", "subjectId": 120, "salePriceU": 5000},
        ]
    }
    parser = _FakeWildberriesParser(payload)
    products = await parser.search("any", limit=10)
    assert len(products) == 1
    assert products[0].external_id == "4"


# ---------------------------------------------------------------------------
# Юниты на helpers
# ---------------------------------------------------------------------------

def test_extract_products_supports_both_schemas():
    # v4/v5: на root
    assert _extract_products({"products": [{"id": 1}]}) == [{"id": 1}]
    # legacy / новые: в data.products
    assert _extract_products({"data": {"products": [{"id": 2}]}}) == [{"id": 2}]
    # ничего
    assert _extract_products({}) == []


def test_parse_price_prefers_sizes_over_legacy():
    """Если есть и sizes[].price, и salePriceU — берём sizes (современный)."""
    item = {
        "salePriceU": 999900,
        "sizes": [{"price": {"product": 200000, "basic": 300000}}],
    }
    assert _parse_price_kopecks(item) == 200000


def test_parse_price_falls_back_to_legacy():
    """sizes отсутствует → salePriceU."""
    assert _parse_price_kopecks({"salePriceU": 50000}) == 50000


def test_parse_price_returns_zero_when_no_signal():
    assert _parse_price_kopecks({}) == 0
    assert _parse_price_kopecks({"sizes": []}) == 0
    assert _parse_price_kopecks({"sizes": [{"price": {}}]}) == 0


def test_build_products_dedupes_by_id():
    items = [
        {"id": 1, "name": "A", "subjectId": 120, "salePriceU": 100},
        {"id": 1, "name": "A duplicate", "subjectId": 120, "salePriceU": 100},
    ]
    products = _build_products(items, limit=10)
    assert len(products) == 1


def test_resolve_backend_default_is_curl_cffi(monkeypatch):
    monkeypatch.delenv("WB_BACKEND", raising=False)
    assert _resolve_backend() == "curl-cffi"


def test_resolve_backend_env_override(monkeypatch):
    monkeypatch.setenv("WB_BACKEND", "httpx")
    assert _resolve_backend() == "httpx"
    monkeypatch.setenv("WB_BACKEND", "garbage")
    assert _resolve_backend() == "curl-cffi"  # garbage → fallback
