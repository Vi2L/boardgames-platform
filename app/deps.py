"""Синглтоны и зависимости приложения.

После перехода на parsers REST API:
- PriceDatabase больше не нужна (кеш управляет parsers-сервис)
- Вместо parser configs — один ParsersClient
"""

from __future__ import annotations

import os

from app.parsers_client import ParsersClient

_client: ParsersClient | None = None


async def init_services() -> None:
    """Вызывается при старте приложения (lifespan).

    Создаёт ParsersClient. Недоступность parsers API при старте —
    не фатальная ошибка: клиент вернёт ошибку при первом запросе.
    """
    global _client

    parsers_url = os.getenv("PARSERS_API_URL", "http://localhost:8001")
    _client = ParsersClient(base_url=parsers_url)


async def close_services() -> None:
    """Корректно закрывает httpx-клиент при остановке приложения."""
    if _client is not None:
        await _client.close()


def get_parsers_client() -> ParsersClient:
    if _client is None:
        raise RuntimeError("Services not initialized. Call init_services() first.")
    return _client
