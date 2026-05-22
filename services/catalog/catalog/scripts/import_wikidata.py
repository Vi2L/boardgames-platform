"""CLI: обогащение catalog'а данными Wikidata.

Алгоритм:
1. SELECT кандидатов: games с заполненным game_bgg.rank ≤ N, у которых либо
   нет game_wikidata, либо запись старше TTL.
2. Для каждой партии (default 50) — один SPARQL-запрос → mapping bgg_id → Q-id.
3. Для каждого Q-id — entity-API JSON → парсинг labels/aliases/descriptions.
4. Upsert game_wikidata; ON CONFLICT (game_id) DO UPDATE.
5. Для ru-labels и ru-aliases — INSERT в game_aliases (source='wikidata',
   language='ru', verified=false), ON CONFLICT DO NOTHING.
6. Если games.description IS NULL — заполняем descriptions['ru'] (или 'en'
   как fallback).

Use:
    .venv/bin/python -m catalog.scripts.import_wikidata --only-rank-le 100
    .venv/bin/python -m catalog.scripts.import_wikidata \\
        --only-rank-le 30000 --languages ru,en --batch-size 50 \\
        --rate-limit 1.0 --refresh-after-days 30
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from catalog.models import Game, GameAlias, GameWikidata
from catalog.wikidata import WikidataClient, WikidataEntity, WikidataError

DEFAULT_DSN = "postgresql+asyncpg://catalog:catalog@localhost:5433/catalog"
USER_AGENT = "boardgames-catalog/0.1 (https://github.com/Vi2L/boardgames-catalog)"

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _select_candidates(
    session, only_rank_le: int, refresh_after_days: int, limit: int | None
) -> list[tuple[int, int]]:
    """Возвращает [(game_id, bgg_id), ...] для импорта."""
    stmt = text(
        """
        SELECT g.id AS game_id, gb.bgg_id AS bgg_id
        FROM games g
        JOIN game_bgg gb ON gb.game_id = g.id
        LEFT JOIN game_wikidata gw ON gw.game_id = g.id
        WHERE gb.rank IS NOT NULL
          AND gb.rank <= :rank
          AND (gw IS NULL OR gw.fetched_at < :stale)
        ORDER BY gb.rank
        """
        + (" LIMIT :limit" if limit else "")
    ).bindparams(
        rank=only_rank_le,
        stale=_utcnow() - timedelta(days=refresh_after_days),
        **({"limit": limit} if limit else {}),
    )
    rows = (await session.execute(stmt)).all()
    return [(r.game_id, r.bgg_id) for r in rows]


async def _process_batch(
    session,
    client: WikidataClient,
    bgg_to_game: dict[int, int],
    languages: list[str],
    dry_run: bool,
) -> tuple[int, int]:
    """Обрабатывает партию bgg_id: SPARQL → entity → upsert.

    Возвращает (found, written) — сколько Q-id найдено и сколько записей upsert'ено.
    """
    bgg_ids = list(bgg_to_game.keys())
    sparql = await client.find_entities_by_bgg_ids(bgg_ids)

    # Игры без Q-id — записываем found=false, чтобы не запрашивать снова до TTL.
    not_found = [b for b in bgg_ids if b not in sparql]
    found = len(sparql)
    written = 0

    for bgg_id, qids in sparql.items():
        first_qid = qids[0]
        try:
            entity = await client.fetch_entity(first_qid, languages, qids)
        except WikidataError as exc:
            logger.warning("entity %s for bgg_id=%s failed: %s", first_qid, bgg_id, exc)
            continue
        await _upsert_one(session, bgg_to_game[bgg_id], bgg_id, entity, dry_run)
        written += 1

    for bgg_id in not_found:
        await _upsert_not_found(session, bgg_to_game[bgg_id], bgg_id, dry_run)

    if not dry_run:
        await session.commit()
    return found, written


async def _upsert_one(
    session, game_id: int, bgg_id: int, entity: WikidataEntity, dry_run: bool
) -> None:
    if dry_run:
        return

    await session.execute(
        pg_insert(GameWikidata.__table__)
        .values(
            game_id=game_id,
            bgg_id=bgg_id,
            entity_id=entity.entity_id,
            found=True,
            labels=entity.labels,
            aliases=entity.aliases,
            descriptions=entity.descriptions,
            matched_entities=entity.matched_entities,
            raw=entity.raw,
            fetched_at=_utcnow(),
        )
        .on_conflict_do_update(
            index_elements=["game_id"],
            set_={
                "entity_id": entity.entity_id,
                "found": True,
                "labels": entity.labels,
                "aliases": entity.aliases,
                "descriptions": entity.descriptions,
                "matched_entities": entity.matched_entities,
                "raw": entity.raw,
                "fetched_at": _utcnow(),
            },
        )
    )

    # Aliases: ru-label + ru-aliases → game_aliases. UNIQUE (game_id, alias_norm)
    # → DO NOTHING на дубликаты.
    ru_label = entity.labels.get("ru")
    ru_aliases = entity.aliases.get("ru", [])
    candidates: list[str] = []
    if ru_label:
        candidates.append(ru_label)
    candidates.extend(ru_aliases)
    for alias in candidates:
        await session.execute(
            pg_insert(GameAlias.__table__)
            .values(
                game_id=game_id,
                alias=alias,
                source="wikidata",
                language="ru",
                verified=False,
            )
            .on_conflict_do_nothing(constraint="uq_alias_per_game")
        )

    # Description: fallback ru → en. Не перезаписываем, если уже есть.
    desc = entity.descriptions.get("ru") or entity.descriptions.get("en")
    if desc:
        await session.execute(
            text(
                "UPDATE games SET description = :d, updated_at = NOW() "
                "WHERE id = :gid AND description IS NULL"
            ).bindparams(d=desc, gid=game_id)
        )


async def _upsert_not_found(
    session, game_id: int, bgg_id: int, dry_run: bool
) -> None:
    if dry_run:
        return
    # Один now на оба пути upsert'а — иначе INSERT-путь и UPDATE-путь получают
    # разные timestamp'ы (микросекундная разница) и идемпотентность нарушается.
    now = _utcnow()
    await session.execute(
        pg_insert(GameWikidata.__table__)
        .values(
            game_id=game_id,
            bgg_id=bgg_id,
            entity_id=None,
            found=False,
            labels={},
            aliases={},
            descriptions={},
            matched_entities=[],
            raw={},
            fetched_at=now,
        )
        .on_conflict_do_update(
            index_elements=["game_id"],
            set_={
                "found": False,
                "fetched_at": now,
            },
        )
    )


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="import_wikidata")
    parser.add_argument("--only-rank-le", type=int, default=1000)
    parser.add_argument("--languages", default="ru,en")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--refresh-after-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=None,
                        help="ограничить общее число обработанных игр")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    languages = [s.strip() for s in args.languages.split(",") if s.strip()]

    dsn = os.getenv("DATABASE_URL", DEFAULT_DSN)
    engine = create_async_engine(dsn)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    ) as http:
        client = WikidataClient(http, rate_limit_seconds=args.rate_limit)

        async with Session() as session:
            candidates = await _select_candidates(
                session, args.only_rank_le, args.refresh_after_days, args.limit
            )

        if not candidates:
            print("nothing to do")
            await engine.dispose()
            return

        print(
            f"candidates: {len(candidates)} games "
            f"(rank ≤ {args.only_rank_le}, stale > {args.refresh_after_days}d)"
        )
        if args.dry_run:
            print("dry-run: no writes")

        t0 = time.monotonic()
        total_found = 0
        total_written = 0
        for i in range(0, len(candidates), args.batch_size):
            batch = candidates[i : i + args.batch_size]
            bgg_to_game = {bgg_id: game_id for game_id, bgg_id in batch}
            async with Session() as session:
                try:
                    found, written = await _process_batch(
                        session, client, bgg_to_game, languages, args.dry_run
                    )
                except WikidataError as exc:
                    logger.error("batch failed (skipping): %s", exc)
                    continue
            total_found += found
            total_written += written

            done = i + len(batch)
            elapsed = time.monotonic() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(candidates) - done) / rate if rate > 0 else 0
            print(
                f"  {done:>5}/{len(candidates)} "
                f"found={total_found} written={total_written} "
                f"({rate:.1f} games/s, eta {eta/60:.1f}min)"
            )

    await engine.dispose()
    print(f"\nDone in {time.monotonic() - t0:.1f}s. found={total_found} written={total_written}")


if __name__ == "__main__":
    asyncio.run(main())
