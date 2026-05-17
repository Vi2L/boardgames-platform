"""Тесты publisher'а оффер'ов в boardgames-catalog.

Проверяем:
- url=None → publisher disabled, publish() — no-op.
- url задан → батч уходит на webhook в правильном формате.
- HTTP-ошибка не пробрасывается (fire-and-forget семантика).
"""
from __future__ import annotations

import json

import httpx
import pytest

from parsers.catalog_publisher import CatalogPublisher
from parsers.models import ParsedProduct


def _sample_product(ext_id: str = "1", title: str = "Каркассон") -> ParsedProduct:
    return ParsedProduct(
        store_slug="hobbygames",
        external_id=ext_id,
        title=title,
        price=169500,
        url=f"https://hobbygames.ru/{ext_id}",
        image_url="https://h/img.jpg",
        raw={"foo": "bar"},
    )


@pytest.mark.asyncio
async def test_disabled_when_no_url():
    pub = CatalogPublisher(url=None)
    await pub.start()
    assert pub.enabled is False
    # publish — no-op, не падает.
    await pub.publish("hobbygames", [_sample_product()])
    await pub.close()


@pytest.mark.asyncio
async def test_publishes_batch_in_correct_format():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"accepted": 1})

    pub = CatalogPublisher(url="http://catalog:8002/ingest/offers", api_key="secret")
    await pub.start()
    pub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await pub.publish("hobbygames", [_sample_product("1", "Каркассон")])

    assert captured["url"] == "http://catalog:8002/ingest/offers"
    assert captured["headers"].get("x-api-key") == "secret"
    body = captured["body"]
    assert body["store_slug"] == "hobbygames"
    assert "fetched_at" in body
    assert len(body["products"]) == 1
    p = body["products"][0]
    assert p["external_id"] == "1"
    assert p["title"] == "Каркассон"
    assert p["price"] == 169500
    assert p["extra"] == {"foo": "bar"}
    # category="boardgames" — все парсеры теперь возвращают только настолки,
    # publisher маркирует это для catalog ingest whitelist'а.
    assert p["category"] == "boardgames"

    await pub.close()


@pytest.mark.asyncio
async def test_publish_swallows_http_errors():
    """Catalog недоступен — не должны падать."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="catalog down")

    pub = CatalogPublisher(url="http://catalog:8002/ingest/offers")
    await pub.start()
    pub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    # Не должно ни упасть, ни залогировать ошибку выше WARN.
    await pub.publish("hobbygames", [_sample_product()])

    await pub.close()


@pytest.mark.asyncio
async def test_publish_empty_list_is_noop():
    captured = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["called"] = True
        return httpx.Response(200)

    pub = CatalogPublisher(url="http://catalog:8002/ingest/offers")
    await pub.start()
    pub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await pub.publish("hobbygames", [])
    assert captured["called"] is False
    await pub.close()
