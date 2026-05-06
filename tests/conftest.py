"""Общие фикстуры для тестов дебаг-портала.

Ключевая особенность: внешний parsers сервис мы НЕ поднимаем — это бы
привязало тесты к сети и реальной БД. Вместо этого подменяем модульный
синглтон `app.deps._client` на FakeParsersClient с детерминированными
ответами. Все эндпоинты портала проходят через `get_parsers_client()`,
поэтому одна точка подмены покрывает весь код.

Запуск через ASGITransport без lifespan-менеджера тоже не случайность:
lifespan создал бы реальный httpx.AsyncClient к несуществующему хосту;
нам это не нужно — мы патчим _client напрямую.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import app.deps as deps_module
from app.main import app
from app.parsers_client import ParsersSearchResponse
from app.schemas import PricePointOut, ProductOut, StoreOut


# ── Фейковый клиент parsers ────────────────────────────────────────────────

class FakeParsersClient:
    """Минимальный двойник `ParsersClient` для тестов.

    Поведение настраивается через атрибуты `stores`, `search_response` и
    `should_fail`. Не наследует ParsersClient намеренно — duck typing
    достаточно, плюс не нужно создавать реальный httpx.AsyncClient.
    """

    base_url = "http://fake-parsers"

    def __init__(self) -> None:
        self.stores: list[StoreOut] = [
            StoreOut(slug="hobbygames", name="HobbyGames", base_url="https://hobbygames.ru"),
            StoreOut(slug="lavkaigr",   name="Лавка игр",   base_url="https://www.lavkaigr.ru"),
        ]
        self.search_response: ParsersSearchResponse = ParsersSearchResponse(
            source="cache",
            errors={},
            products=[
                ProductOut(
                    id=1, store_slug="hobbygames", title="Каркассон",
                    price_rub=1990.0, url="https://hobbygames.ru/karkasson",
                    image_url=None, image_url_hd=None,
                    description=None, players=None, age_min=None,
                    playtime=None, rules_url=None,
                    fetched_at="2026-05-01T10:00:00Z",
                    extra={},
                ),
            ],
        )
        self.should_fail_stores: bool = False
        self.should_fail_search: bool = False
        # История цен per-product. Тесты могут пополнять напрямую.
        self.histories: dict[int, list[PricePointOut]] = {}

    async def get_stores(self) -> list[StoreOut]:
        if self.should_fail_stores:
            raise RuntimeError("parsers unreachable")
        return self.stores

    async def search(self, q: str, stores: list[str] | None = None,
                     limit: int = 10, refresh: bool = False) -> ParsersSearchResponse:
        if self.should_fail_search:
            raise RuntimeError("parsers search failed")
        return self.search_response

    async def get_history(self, product_id: int) -> list[PricePointOut]:
        return self.histories.get(product_id, [])

    async def get_history_batch(
        self, product_ids: list[int],
    ) -> dict[int, list[PricePointOut]]:
        return {pid: await self.get_history(pid) for pid in product_ids}

    async def close(self) -> None:
        pass


# ── Pytest fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def fake_client() -> FakeParsersClient:
    return FakeParsersClient()


@pytest.fixture
def patched_app(fake_client: FakeParsersClient, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Патчит модульный синглтон `app.deps._client` на fake_client.

    Возвращает само ASGI-приложение — клиент создаётся в тесте, чтобы
    можно было использовать stream() и обычный get() в одном тесте.
    """
    monkeypatch.setattr(deps_module, "_client", fake_client)
    return app


@pytest.fixture
async def http_client(patched_app: Any) -> AsyncIterator[AsyncClient]:
    """httpx-клиент к тестируемому FastAPI без lifespan-startup."""
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Хелперы ────────────────────────────────────────────────────────────────

def parse_sse_chunk(chunk: str) -> tuple[str, str] | None:
    """Превращает блок SSE (две строки `event:`/`data:`) в кортеж (event, data)."""
    event = None
    data = None
    for line in chunk.splitlines():
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data = line[len("data:"):].strip()
    if event is None:
        return None
    return event, data or ""


async def collect_sse_events(client: AsyncClient, url: str,
                             timeout: float = 5.0) -> list[tuple[str, str]]:
    """Дочитывает SSE до конца стрима, возвращает список (event, data_json).

    Завершение определяется по закрытию соединения сервером (после `None`
    в очереди _run_search). Жёсткий потолок по времени защищает от зависания
    в случае ошибки в коде backend.
    """
    events: list[tuple[str, str]] = []
    buf = ""

    async def _read() -> None:
        nonlocal buf
        async with client.stream("GET", url) as resp:
            assert resp.status_code == 200, f"unexpected status {resp.status_code}"
            async for chunk in resp.aiter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    parsed = parse_sse_chunk(block)
                    if parsed is not None:
                        events.append(parsed)

    try:
        await asyncio.wait_for(_read(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return events
