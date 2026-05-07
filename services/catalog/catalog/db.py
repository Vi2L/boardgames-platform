"""Асинхронный SQLAlchemy-движок и сессия.

Используем SQLAlchemy 2.0 async API поверх asyncpg. На этапе skeleton'а
здесь только базовый Base + engine factory; модели появятся на следующем
этапе вместе с Alembic-миграциями.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from catalog.config import get_settings


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей. Все таблицы наследуются от него."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazy singleton: движок создаётся при первом вызове, потом переиспользуется."""
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,  # отбрасывает мёртвые соединения, важно для pgbouncer/долгоживущих процессов
        )
        _session_factory = async_sessionmaker(
            _engine,
            expire_on_commit=False,  # после commit'а объекты не «протухают» — удобнее в FastAPI
        )
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: даёт сессию на запрос, гарантирует close()."""
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    async with _session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Закрывает пул соединений. Вызывается при остановке приложения."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
