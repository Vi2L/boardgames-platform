"""Общие фикстуры для тестов.

DB-зависимые тесты автоматически пропускаются, если Postgres не доступен —
это позволяет /health-тесту работать в CI без поднятия БД.

Стратегия: каждый тест получает соединение, оборачивает в SAVEPOINT и
откатывает в конце — чтобы не загрязнять БД и не зависеть от порядка.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)


def _db_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://catalog:catalog@localhost:5433/catalog",
    )


def _db_available() -> bool:
    """Быстрый probe: пытаемся подключиться. Кешируем, чтобы не дёргать на каждый тест."""
    if not hasattr(_db_available, "_cached"):
        async def _probe() -> bool:
            engine = create_async_engine(_db_url())
            try:
                async with engine.connect() as conn:
                    await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
                return True
            except Exception:
                return False
            finally:
                await engine.dispose()

        _db_available._cached = asyncio.run(_probe())  # type: ignore[attr-defined]
    return _db_available._cached  # type: ignore[attr-defined]


requires_db = pytest.mark.skipif(
    not _db_available(),
    reason="Postgres не доступен на DATABASE_URL — поднимите docker compose up postgres",
)


@pytest_asyncio.fixture(autouse=True)
async def _reset_app_engine() -> AsyncIterator[None]:
    """Singleton engine из catalog.db привязывается к текущему event loop.

    pytest-asyncio даёт каждому тесту свой loop → asyncpg-соединения старого
    loop'а становятся «event loop is closed». Сбрасываем engine до и после
    теста, чтобы catalog.api.app поднял свежий движок под новый loop.
    """
    from catalog import db as db_mod
    await db_mod.dispose_engine()
    yield
    await db_mod.dispose_engine()


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(_db_url())
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Соединение с откатом транзакции в конце теста."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
