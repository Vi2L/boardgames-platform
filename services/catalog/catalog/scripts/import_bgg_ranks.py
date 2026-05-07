"""Импорт BGG ranks-выгрузки CSV в games + game_bgg.

CSV-формат: id, name, yearpublished, rank, bayesaverage, average, usersrated,
is_expansion, abstracts_rank, cgs_rank, childrensgames_rank, familygames_rank,
partygames_rank, strategygames_rank, thematic_rank, wargames_rank.

Раскладка по таблицам:
- games: slug, title, year, bgg_id, source='bgg-ranks', status='published'
  (минимум для отображения; description/meta остаются пустыми — XML API даст их позже).
- game_bgg: rank, bayes_average, average, users_rated, is_expansion, subtype_ranks,
  raw (вся CSV-строка), source='csv-ranks', fetched_at.

Идемпотентность:
- ON CONFLICT (bgg_id) DO UPDATE на games — обновляет title/year (CSV меняется
  ежемесячно).
- ON CONFLICT (game_id) DO UPDATE на game_bgg — рестартует TLL.

Использование:
    .venv/bin/python -m catalog.scripts.import_bgg_ranks /path/to/boardgames_ranks.csv
"""
from __future__ import annotations

import asyncio
import csv
import os
import re
import sys
import time
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from catalog.models import Game, GameBgg

# Дефолт для запуска с хоста (через port mapping bg-postgres :5433 → :5432).
# Переопределяется ENV `DATABASE_URL`, что позволяет запускать скрипт и
# внутри docker-контейнера (где DATABASE_URL=postgresql+asyncpg://catalog:catalog@postgres:5432/catalog).
DEFAULT_DSN = "postgresql+asyncpg://catalog:catalog@localhost:5433/catalog"
BATCH = 1000


def slugify(name: str, bgg_id: int) -> str:
    """ASCII-slug с bgg_id-фоллбэком — гарантирует уникальность для русских названий."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not base or not base[0].isalnum():
        base = "game"
    return f"{base}-{bgg_id}"[:255]


def _opt_int(v: str) -> int | None:
    if v in ("", "0"):
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _opt_float(v: str) -> float | None:
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def split_row(row: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Делит CSV-строку на две части: для games и для game_bgg.

    Возвращает None, если запись не валидна (нет id или name).
    """
    bgg_id = _opt_int(row["id"])
    name = (row.get("name") or "").strip()
    if not bgg_id or not name:
        return None

    rank = _opt_int(row.get("rank", ""))
    is_expansion = row.get("is_expansion", "0") == "1"

    sub_ranks = {
        k.replace("_rank", ""): _opt_int(row.get(k, ""))
        for k in (
            "abstracts_rank", "cgs_rank", "childrensgames_rank",
            "familygames_rank", "partygames_rank", "strategygames_rank",
            "thematic_rank", "wargames_rank",
        )
    }
    sub_ranks = {k: v for k, v in sub_ranks.items() if v is not None}

    games_row = {
        "slug": slugify(name, bgg_id),
        "title": name,
        "year": _opt_int(row.get("yearpublished", "")),
        "bgg_id": bgg_id,
        "source": "bgg-ranks",
        "status": "published",
    }

    bgg_row = {
        "bgg_id": bgg_id,  # связка с games через bgg_id (resolve в game_id будет SELECT'ом)
        "rank": rank,
        "bayes_average": _opt_float(row.get("bayesaverage", "")),
        "average": _opt_float(row.get("average", "")),
        "users_rated": _opt_int(row.get("usersrated", "")),
        "is_expansion": is_expansion,
        "subtype_ranks": sub_ranks or None,
        "raw": {"csv": row},
        "source": "csv-ranks",
    }

    return games_row, bgg_row


async def main(csv_path: str) -> None:
    engine = create_async_engine(os.getenv("DATABASE_URL", DEFAULT_DSN))
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    total_seen = 0
    total_upserted = 0
    skipped = 0
    t0 = time.monotonic()

    with open(csv_path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        games_batch: list[dict[str, Any]] = []
        bgg_batch_by_id: dict[int, dict[str, Any]] = {}  # bgg_id → bgg-row

        async def flush() -> int:
            if not games_batch:
                return 0
            async with SessionFactory() as session:
                # 1. Upsert в games через ON CONFLICT (bgg_id) — возвращаем (id, bgg_id).
                games_stmt = pg_insert(Game.__table__).values(games_batch).on_conflict_do_update(
                    index_elements=["bgg_id"],
                    set_={
                        "title": pg_insert(Game.__table__).excluded.title,
                        "year": pg_insert(Game.__table__).excluded.year,
                        "source": pg_insert(Game.__table__).excluded.source,
                    },
                ).returning(Game.__table__.c.id, Game.__table__.c.bgg_id)
                rows = (await session.execute(games_stmt)).all()
                bgg_id_to_game_id = {r.bgg_id: r.id for r in rows}

                # 2. Upsert в game_bgg, подставляя resolved game_id.
                bgg_records = []
                for bgg_id, payload in bgg_batch_by_id.items():
                    game_id = bgg_id_to_game_id.get(bgg_id)
                    if game_id is None:
                        continue
                    bgg_records.append({"game_id": game_id, **payload})

                if bgg_records:
                    bgg_stmt = pg_insert(GameBgg.__table__).values(bgg_records).on_conflict_do_update(
                        index_elements=["game_id"],
                        set_={
                            "rank": pg_insert(GameBgg.__table__).excluded.rank,
                            "bayes_average": pg_insert(GameBgg.__table__).excluded.bayes_average,
                            "average": pg_insert(GameBgg.__table__).excluded.average,
                            "users_rated": pg_insert(GameBgg.__table__).excluded.users_rated,
                            "is_expansion": pg_insert(GameBgg.__table__).excluded.is_expansion,
                            "subtype_ranks": pg_insert(GameBgg.__table__).excluded.subtype_ranks,
                            "raw": pg_insert(GameBgg.__table__).excluded.raw,
                            "source": pg_insert(GameBgg.__table__).excluded.source,
                            "fetched_at": pg_insert(GameBgg.__table__).excluded.fetched_at,
                        },
                    )
                    await session.execute(bgg_stmt)

                await session.commit()
                return len(games_batch)

        for row in reader:
            total_seen += 1
            split = split_row(row)
            if split is None:
                skipped += 1
                continue
            games_row, bgg_row = split
            games_batch.append(games_row)
            bgg_batch_by_id[bgg_row["bgg_id"]] = bgg_row
            if len(games_batch) >= BATCH:
                total_upserted += await flush()
                games_batch.clear()
                bgg_batch_by_id.clear()
                if total_upserted % 10_000 == 0:
                    elapsed = time.monotonic() - t0
                    rate = total_upserted / elapsed
                    print(f"  {total_upserted:>7,} done in {elapsed:5.1f}s "
                          f"({rate:,.0f}/s)")

        total_upserted += await flush()

    elapsed = time.monotonic() - t0
    print(f"\nDone: seen={total_seen:,} upserted={total_upserted:,} "
          f"skipped={skipped:,} in {elapsed:.1f}s")
    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m catalog.scripts.import_bgg_ranks <path/to/csv>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
