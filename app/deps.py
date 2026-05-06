"""Синглтоны и зависимости приложения.

- ParsersClient — единственная точка общения с внешним parsers API;
- PortalDB — локальная SQLite, см. app/db_local.py.

Оба создаются в lifespan-startup (init_services) и закрываются в shutdown.
"""

from __future__ import annotations

import os

from app.db_local import close_portal_db, init_portal_db
from app.parsers_client import ParsersClient

_client: ParsersClient | None = None


async def init_services() -> None:
    """Вызывается при старте приложения (lifespan).

    Создаёт ParsersClient и инициализирует PortalDB. Недоступность parsers
    API при старте — не фатальная ошибка: клиент вернёт ошибку при первом
    запросе. Падение PortalDB-инициализации — фатально (повреждённый
    диск/permissions), пусть приложение не стартует.
    """
    global _client

    parsers_url = os.getenv("PARSERS_API_URL", "http://localhost:8001")
    _client = ParsersClient(base_url=parsers_url)

    await init_portal_db()


async def close_services() -> None:
    """Корректно закрывает httpx-клиент и SQLite при остановке приложения."""
    if _client is not None:
        await _client.close()
    await close_portal_db()


def get_parsers_client() -> ParsersClient:
    if _client is None:
        raise RuntimeError("Services not initialized. Call init_services() first.")
    return _client
