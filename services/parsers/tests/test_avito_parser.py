"""Smoke-тесты для AvitoParser (L0: curl-cffi + /web/1/js/items).

Сеть не трогаем — мокаем `AvitoQratorClient.search_items()` и проверяем,
что JSON-payload корректно мапится в `ParsedProduct`. Цель — поймать
регрессии в `_extract_items`, `_parse_price_kopecks`, `_pick_image`,
`_build_products` после рефакторинга.

Реальный TLS-impersonation тестируется через `bin/probe_avito_l0_xhr.py` —
этот скрипт умышленно вне pytest, потому что требует сети к avito.ru.
"""
from __future__ import annotations

import pytest

from parsers.stores.avito import (
    AvitoParser,
    _parse_price_kopecks,
    _pick_image,
    _extract_items,
)


class _FakeQratorClient:
    """Подменяет `AvitoQratorClient` — отдаёт preset-payload без сети."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[str] = []

    async def search_items(self, query: str, *, sort: int = 104) -> dict:
        self.calls.append(query)
        return self._payload


# Минимальный JSON, имитирующий ответ `/web/1/js/items` — взято из probe.
_PAYLOAD = {
    "count": 2,
    "catalog": {
        "items": [
            {
                "id": 7494112424,
                "title": "Настольные игры серии Каркассон",
                "description": "Каркассон база — 1.490р. ...",
                "urlPath": "/moskva/sport_i_otdyh/nastolnye_igry_serii_karkasson_7494112424?context=abc",
                "priceDetailed": {"string": "1 490 ₽", "value": 1490, "valueOld": ""},
                "images": [{
                    "140x140": "https://50.img.avito.st/image/1/140.jpg",
                    "678x678": "https://50.img.avito.st/image/1/678.jpg",
                }],
                "location": {"id": 637640, "name": "Москва, Площадь революции"},
                "category": {"id": 39, "name": "Спорт и отдых", "slug": "sport_i_otdyh"},
            },
            {
                "id": 8049321629,
                "title": "Каркассон",
                "description": "",
                "urlPath": "/velikiy_novgorod/sport_i_otdyh/karkasson_8049321629",
                # Особый случай: value=0, цену тащим из string.
                "priceDetailed": {"string": "500 ₽", "value": 0},
                "images": [],
                "location": {"name": "Великий Новгород"},
            },
        ],
    },
}


@pytest.mark.asyncio
async def test_avito_parser_maps_json_to_products():
    parser = AvitoParser(qrator_client=_FakeQratorClient(_PAYLOAD))
    products = await parser.search("Каркассон", limit=10)

    assert len(products) == 2
    p1, p2 = products

    assert p1.external_id == "7494112424"
    assert p1.title == "Настольные игры серии Каркассон"
    assert p1.price == 149_000          # копейки
    assert p1.url == "https://www.avito.ru/moskva/sport_i_otdyh/nastolnye_igry_serii_karkasson_7494112424"
    assert "?" not in p1.url            # query-параметры (context) должны быть отрезаны
    assert p1.image_url and "678" in p1.image_url  # выбрана картинка с макс. шириной
    assert p1.raw["location"] == "Москва, Площадь революции"
    assert p1.raw["category"] == "Спорт и отдых"
    assert p1.raw["in_stock"] is True

    # Второй item: value=0 → цена парсится из string «500 ₽».
    assert p2.price == 50_000
    assert p2.image_url is None         # пустой images → None


@pytest.mark.asyncio
async def test_avito_parser_respects_limit():
    parser = AvitoParser(qrator_client=_FakeQratorClient(_PAYLOAD))
    products = await parser.search("Каркассон", limit=1)
    assert len(products) == 1


@pytest.mark.asyncio
async def test_avito_parser_no_client_returns_empty():
    # backward-compat: если клиент не сконфигурирован — тихо []
    parser = AvitoParser(qrator_client=None)
    assert await parser.search("anything") == []


@pytest.mark.asyncio
async def test_avito_parser_writes_metrics():
    parser = AvitoParser(qrator_client=_FakeQratorClient(_PAYLOAD))
    await parser.search("Каркассон", limit=10)
    m = parser.last_metrics
    assert m is not None
    assert m.http_requests == 1
    assert m.result_after_enrich == 2
    assert m.enrich_ms is None          # у avito нет enrich-этапа


def test_parse_price_kopecks_handles_edge_cases():
    # value > 0 — основной путь
    assert _parse_price_kopecks({"priceDetailed": {"value": 1490, "string": ""}}) == 149_000
    # value = 0 → парсим из string с NBSP-разделителями
    assert _parse_price_kopecks({"priceDetailed": {"value": 0, "string": "1 490 ₽"}}) == 149_000
    # «Цена не указана» — оба пустые
    assert _parse_price_kopecks({"priceDetailed": {"value": 0, "string": ""}}) == 0
    # priceDetailed вообще нет
    assert _parse_price_kopecks({}) == 0


def test_pick_image_chooses_largest():
    item = {"images": [{
        "140x140": "https://x/140.jpg",
        "278x278": "https://x/278.jpg",
        "678x678": "https://x/678.jpg",
    }]}
    assert _pick_image(item) == "https://x/678.jpg"


def test_pick_image_empty():
    assert _pick_image({"images": []}) is None
    assert _pick_image({}) is None


def test_extract_items_supports_both_schemas():
    # Новая схема (/web/1/js/items): catalog.items
    assert _extract_items({"catalog": {"items": [{"id": 1}]}}) == [{"id": 1}]
    # Старая схема (/web/1/main/items): items на root
    assert _extract_items({"items": [{"id": 2}]}) == [{"id": 2}]
    # Ничего знакомого
    assert _extract_items({}) == []
