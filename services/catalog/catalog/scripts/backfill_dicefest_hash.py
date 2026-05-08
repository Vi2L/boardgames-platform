"""Бэкафилл `dicefest_raw_games.content_hash` после миграции 0007.

После накатывания миграции у существующих staging-записей `content_hash IS NULL`.
Detection-runner умеет заполнять хеш на лету при следующем прогоне, но это
платит трафиком к dicefest.ru. Скрипт делает то же самое локально, не дёргая
сайт: собирает payload-snapshot из колонок (та же логика, что в `runner._load_existing_hashes`)
и пишет хеш через `compute_content_hash`.

Идемпотентен: WHERE content_hash IS NULL — повторный запуск ничего не делает.

Запуск:
    uv run --package boardgames-catalog python -m catalog.scripts.backfill_dicefest_hash

ENV:
    DATABASE_URL  (default: postgresql+asyncpg://catalog:catalog@localhost:5433/catalog)
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from catalog.sources.diff import compute_content_hash

DEFAULT_DSN = "postgresql+asyncpg://catalog:catalog@localhost:5433/catalog"

# Достаём только записи без хеша + поля, нужные для compute_content_hash.
# raw_html/source_listing/fetched_at сознательно НЕ включены — _canonicalize
# их фильтрует, но и здесь не тащим, чтобы экономить трафик.
SELECT_SQL = """
SELECT id,
       jsonb_build_object(
         'slug', slug,
         'page_url', page_url,
         'title_ru', title_ru,
         'title_en', title_en,
         'publisher', publisher,
         'release_status', release_status,
         'description', description,
         'cover_url', cover_url,
         'preorder_price', preorder_price,
         'external_links', external_links,
         'raw', raw
       ) AS payload
FROM dicefest_raw_games
WHERE content_hash IS NULL
ORDER BY id
LIMIT :batch
OFFSET :offset
"""

UPDATE_SQL = "UPDATE dicefest_raw_games SET content_hash = :h WHERE id = :id"

BATCH_SIZE = 500


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL", DEFAULT_DSN)
    engine = create_async_engine(dsn, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    total_updated = 0
    offset = 0

    from sqlalchemy import text  # локальный импорт, чтобы скрипт работал без catalog.db

    async with factory() as session:
        while True:
            rows = (
                await session.execute(
                    text(SELECT_SQL).bindparams(batch=BATCH_SIZE, offset=offset),
                )
            ).all()
            if not rows:
                break

            for row in rows:
                row_id, payload = row
                h = compute_content_hash(payload)
                await session.execute(
                    text(UPDATE_SQL).bindparams(h=h, id=row_id),
                )
                total_updated += 1

            await session.commit()
            print(f"backfilled batch: rows={len(rows)} total={total_updated}")
            # offset не двигаем: WHERE content_hash IS NULL уже выполнен,
            # а SELECT выше — новый запрос на свежем состоянии.
            offset = 0

    await engine.dispose()
    print(f"done: {total_updated} rows updated")


if __name__ == "__main__":
    asyncio.run(main())
