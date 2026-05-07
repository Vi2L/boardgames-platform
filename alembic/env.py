"""Alembic env: подключение к async-движку проекта.

Особенность: SQLAlchemy 2.0 async требует обёртки run_sync вокруг
context.run_migrations(), потому что сам Alembic — синхронный.
target_metadata указывает на Base.metadata — Alembic будет автогенерировать
миграции, сравнивая ORM-модели с реальной схемой БД.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from catalog.config import get_settings
from catalog.db import Base

# Импортируем модели, чтобы они зарегистрировались в Base.metadata
# до того, как Alembic будет автогенерировать миграции.
from catalog import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Подсовываем DSN из настроек проекта, игнорируя alembic.ini.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Генерация SQL-скрипта без подключения к БД (для review/CI)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
