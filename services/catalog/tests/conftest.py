"""Общие фикстуры для тестов.

DB-зависимые тесты автоматически пропускаются, если Postgres не доступен —
это позволяет /health-тесту работать в CI без поднятия БД.

Стратегия: каждый тест получает соединение, оборачивает в SAVEPOINT и
откатывает в конце — чтобы не загрязнять БД и не зависеть от порядка.

⚠ ЗАЩИТА ОТ TRUNCATE prod БД ⚠
Фикстура `clean_db` в test_games_api.py делает TRUNCATE с CASCADE — на
prod БД это разрушительно. Поэтому модуль на старте проверяет, что URL
указывает на тестовую БД (имя содержит 'test'). Иначе pytest падает
сразу, не запустив ни одного теста. Прецедент: 2026-05-07.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)

# Дефолт — отдельная тестовая БД. Если её ещё нет, создать командой:
#   docker exec bg-postgres createdb -U catalog catalog_test
#   cd services/catalog && DATABASE_URL='postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test' \
#     uv run --package boardgames-catalog alembic upgrade head
_DEFAULT_TEST_URL = "postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test"


def _resolve_test_url() -> str:
    """Выбирает URL тестовой БД с приоритетом: TEST_DATABASE_URL → DATABASE_URL → дефолт.

    TEST_DATABASE_URL — явное указание тестовой БД. Используется в первую
    очередь, чтобы можно было держать DATABASE_URL=...prod в .env (для
    docker-compose / alembic), а тесты направить на отдельную БД.
    """
    return (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or _DEFAULT_TEST_URL
    )


def _assert_test_db(url: str) -> None:
    """Падает, если URL не похож на тестовую БД.

    Why: фикстура clean_db делает TRUNCATE TABLE games, ... CASCADE.
    На prod БД (~162K игр) это уничтожит данные за миллисекунды.
    Простое правило 'имя БД содержит test' — дешёвый и эффективный guard.
    """
    db_name = make_url(url).database or ""
    if "test" not in db_name.lower():
        raise RuntimeError(
            "\n"
            "╔══════════════════════════════════════════════════════════════════╗\n"
            "║  ОТКАЗ ЗАПУСТИТЬ ТЕСТЫ: БД '{name}' не похожа на тестовую\n"
            "╠══════════════════════════════════════════════════════════════════╣\n"
            "║  Conftest использует TRUNCATE с CASCADE — на prod БД это\n"
            "║  уничтожит данные. Имя БД должно содержать 'test'.\n"
            "║\n"
            "║  Решение: создать отдельную тестовую БД (один раз):\n"
            "║    docker exec bg-postgres createdb -U catalog catalog_test\n"
            "║    cd services/catalog && \\\n"
            "║      DATABASE_URL='postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test' \\\n"
            "║      uv run --package boardgames-catalog alembic upgrade head\n"
            "║\n"
            "║  И запускать pytest с переменной TEST_DATABASE_URL:\n"
            "║    export TEST_DATABASE_URL='postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test'\n"
            "║    uv run pytest\n"
            "╚══════════════════════════════════════════════════════════════════╝\n"
            .format(name=db_name)
        )


# Выполняется один раз при загрузке conftest — до любых импортов из catalog.api,
# которые читают DATABASE_URL через pydantic-settings.
_TEST_URL = _resolve_test_url()
_assert_test_db(_TEST_URL)
# Прокидываем в env, чтобы catalog.api.app (импортируется в test_games_api.py)
# создавал свой engine на тестовой БД, а не на той, что в .env.
os.environ["DATABASE_URL"] = _TEST_URL


def _db_url() -> str:
    return _TEST_URL


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
