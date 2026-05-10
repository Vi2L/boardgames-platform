"""Backfill games.title_ru из лучшего ru-alias.

Приоритет источников (от высшего к низшему):
  1. verified=True ru-alias (любой source)
  2. source='manual', language='ru'
  3. source='dicefest', language='ru'
  4. source='wikidata', language='ru'

Использование:
    uv run --package boardgames-catalog python -m catalog.scripts.backfill_title_ru
    uv run --package boardgames-catalog python -m catalog.scripts.backfill_title_ru --force

--force: перезаписать уже заполненные title_ru. Default — только пустые.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from catalog.db import get_engine

logger = logging.getLogger(__name__)


# Приоритет: verified manually > manual > dicefest > wikidata
# Реализуем через CASE-выражение в ORDER BY.
_BACKFILL_SQL = """
WITH best_alias AS (
    SELECT DISTINCT ON (game_id)
        game_id, alias,
        CASE
            WHEN verified AND language = 'ru' THEN 1
            WHEN source = 'manual' AND language = 'ru' THEN 2
            WHEN source = 'dicefest' AND language = 'ru' THEN 3
            WHEN source = 'wikidata' AND language = 'ru' THEN 4
            ELSE 99
        END AS prio
    FROM game_aliases
    WHERE language = 'ru'
    ORDER BY game_id, prio ASC, id ASC
)
UPDATE games g
SET title_ru = ba.alias
FROM best_alias ba
WHERE g.id = ba.game_id
  AND ba.prio < 99
  { force_clause }
RETURNING g.id
"""


async def backfill(force: bool = False) -> int:
    """Возвращает количество обновлённых строк."""
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    sql = _BACKFILL_SQL.replace(
        "{ force_clause }",
        "" if force else "AND g.title_ru IS NULL",
    )

    async with SessionFactory() as session:
        result = await session.execute(text(sql))
        ids = [row[0] for row in result.fetchall()]
        await session.commit()

    logger.info("backfill_title_ru: updated %d games", len(ids))
    return len(ids)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill games.title_ru из лучшего ru-alias",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="перезаписать уже заполненные title_ru",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    count = asyncio.run(backfill(force=args.force))
    print(f"updated {count} games")
    return 0


if __name__ == "__main__":
    sys.exit(main())
