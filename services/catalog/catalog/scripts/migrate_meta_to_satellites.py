"""Phase 2: переезд BGG-полей из games.meta.bgg_ranks → game_bgg.

Запускается один раз после применения миграции 0002_satellite_schema.
Идемпотентен: ON CONFLICT (game_id) DO NOTHING — повторный запуск
ничего не ломает (только пропускает уже мигрированные).

games.meta при этом не трогается — план специально предусматривает
обратную совместимость на время перехода. Когда Phase 4 (API) переедет
на чтение из game_bgg, старый meta.bgg_ranks можно будет вычистить
отдельной задачей.

Использование:
    .venv/bin/python -m catalog.scripts.migrate_meta_to_satellites

ENV:
    DATABASE_URL  (default: postgresql+asyncpg://catalog:catalog@localhost:5433/catalog)
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


DEFAULT_DSN = "postgresql+asyncpg://catalog:catalog@localhost:5433/catalog"

# Один INSERT INTO ... SELECT — в Postgres это самое быстрое и атомарное.
# JSON-кастинги аккуратные: ::int / ::float / ::boolean. Если в meta что-то
# сломано — падаем явно, не молча.
MIGRATION_SQL = """
INSERT INTO game_bgg (
    game_id, bgg_id, rank, bayes_average, average, users_rated,
    is_expansion, subtype_ranks, raw, source, fetched_at
)
SELECT
    g.id,
    g.bgg_id,
    NULLIF(g.meta->'bgg_ranks'->>'rank', '')::int,
    NULLIF(g.meta->'bgg_ranks'->>'bayes_average', '')::float,
    NULLIF(g.meta->'bgg_ranks'->>'average', '')::float,
    NULLIF(g.meta->'bgg_ranks'->>'users_rated', '')::int,
    COALESCE((g.meta->'bgg_ranks'->>'is_expansion')::boolean, false),
    g.meta->'bgg_ranks'->'subtype_ranks',
    COALESCE(g.meta - 'bgg_ranks', '{}'::jsonb),  -- остаток meta (без bgg_ranks) в raw
    'csv-ranks',
    g.updated_at
FROM games g
WHERE g.bgg_id IS NOT NULL
  AND g.meta ? 'bgg_ranks'
ON CONFLICT (game_id) DO NOTHING
"""

COUNTS_SQL = """
SELECT
    (SELECT count(*) FROM games WHERE bgg_id IS NOT NULL AND meta ? 'bgg_ranks') AS source_rows,
    (SELECT count(*) FROM game_bgg) AS satellite_rows,
    (SELECT count(*) FROM game_bgg WHERE rank IS NOT NULL) AS ranked
"""


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", DEFAULT_DSN)
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            before = (await conn.execute(text(COUNTS_SQL))).one()
            print(
                f"before: source(meta)={before.source_rows:,} "
                f"satellite={before.satellite_rows:,} ranked={before.ranked:,}"
            )

            result = await conn.execute(text(MIGRATION_SQL))
            inserted = result.rowcount

            after = (await conn.execute(text(COUNTS_SQL))).one()
            print(f"inserted: {inserted:,}")
            print(
                f"after:  source(meta)={after.source_rows:,} "
                f"satellite={after.satellite_rows:,} ranked={after.ranked:,}"
            )
            if after.satellite_rows < before.source_rows:
                missing = before.source_rows - after.satellite_rows
                print(
                    f"⚠ {missing:,} games из meta не попали в game_bgg "
                    "(возможно, ON CONFLICT — они уже там; запустите дважды для проверки)"
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
