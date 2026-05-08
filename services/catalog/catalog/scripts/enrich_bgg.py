"""CLI: обогащение catalog'а полным XML-API ответом BGG.

Заполняет поля, которых нет в CSV-выгрузке `import_bgg_ranks.py`:
описания, дизайнеры, механики, категории, обложки, alternate names.
Для каждой ranked-игры ходит в `/xmlapi2/thing?id=<id1,id2,...>` (batch до
20 ID за запрос — критично, иначе full seed занимает ~8 часов вместо ~25
минут).

Алгоритм (см. `~/.claude/plans/modular-knitting-sloth.md` этап 2-3):
1. SELECT кандидатов: game_bgg WHERE rank IS NOT NULL AND rank ≤ N
   AND (source <> 'xml-api' OR fetched_at < now() - skip_recent_days).
2. Разбиваем на пачки batch_size (≤20) ID.
3. Для каждой пачки — один HTTP-запрос с rate-limit между пачками
   (по best practice BGG ≈ 1 req/sec).
4. Парсим, upsert'им в games (COALESCE — не затираем ручные правки) и в
   game_bgg (полная перезапись XML-полей).
5. alternate names → game_aliases (source='bgg', language='en'), ON CONFLICT
   DO NOTHING.

Использование:
    # Топ-100 dry-run (не пишет в БД, только показывает счётчики).
    uv run --package boardgames-catalog python -m catalog.scripts.enrich_bgg \\
        --only-rank-le 100 --dry-run

    # Реальный прогон топ-1000.
    uv run --package boardgames-catalog python -m catalog.scripts.enrich_bgg \\
        --only-rank-le 1000

    # Полный seed по всем ranked играм (этап 3 — долго, ~25 минут).
    uv run --package boardgames-catalog python -m catalog.scripts.enrich_bgg \\
        --all-ranked

    # Форсировать перезапрос недавно обогащённых.
    uv run --package boardgames-catalog python -m catalog.scripts.enrich_bgg \\
        --only-rank-le 1000 --skip-recent-days 0
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from catalog.parsers.bgg.client import THING_BATCH_MAX, BggClient
from catalog.parsers.bgg.service import enrich_batch

DEFAULT_DSN = "postgresql+asyncpg://catalog:catalog@localhost:5433/catalog"

logger = logging.getLogger("enrich_bgg")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="enrich_bgg",
        description="Batch-обогащение catalog'а через BGG XML API.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--only-rank-le", type=int, metavar="N",
        help="обработать только игры с BGG rank ≤ N (топ-N).",
    )
    g.add_argument(
        "--all-ranked", action="store_true",
        help="обработать все ranked-игры (этап 3, ~25 минут).",
    )
    p.add_argument(
        "--batch-size", type=int, default=THING_BATCH_MAX, metavar="N",
        help=f"ID на запрос (1..{THING_BATCH_MAX}, default={THING_BATCH_MAX}).",
    )
    p.add_argument(
        "--skip-recent-days", type=int, default=30, metavar="N",
        help="не перезапрашивать игры с fetched_at < N дней (default=30, 0=форсировать).",
    )
    p.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="общий потолок (для пробного прогона).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="не писать в БД, только посчитать кандидатов.",
    )
    p.add_argument(
        "--rate-limit-sec", type=float, default=1.0, metavar="S",
        help="задержка между batch-запросами (default=1.0, BGG ~1 req/sec).",
    )
    return p


async def _run(args: argparse.Namespace) -> int:
    rank_le = None if args.all_ranked else args.only_rank_le

    engine = create_async_engine(os.getenv("DATABASE_URL", DEFAULT_DSN))
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    print(
        f"enrich_bgg: rank_le={rank_le} batch_size={args.batch_size} "
        f"skip_recent_days={args.skip_recent_days} limit={args.limit} dry_run={args.dry_run}",
        file=sys.stderr,
    )
    t0 = time.monotonic()
    last_logged = {"i": 0}

    async def _progress(i: int, total: int, _bgg) -> None:
        # Логируем не каждый шаг, а раз в ~50 — чтобы не засорять stderr.
        if i - last_logged["i"] >= 50 or i == total:
            elapsed = time.monotonic() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(
                f"  [{i:>5}/{total:<5}] {elapsed:5.1f}s  ({rate:.1f} games/sec)",
                file=sys.stderr,
            )
            last_logged["i"] = i

    async with BggClient() as client:
        stats = await enrich_batch(
            rank_le=rank_le,
            batch_size=args.batch_size,
            skip_recent_days=args.skip_recent_days,
            limit=args.limit,
            dry_run=args.dry_run,
            rate_limit_sec=args.rate_limit_sec,
            progress_cb=_progress,
            session_factory=SessionFactory,
            client=client,
        )

    elapsed = time.monotonic() - t0
    print(
        f"\nDone in {elapsed:.1f}s: enriched={stats.enriched} "
        f"skipped={stats.skipped} failed={stats.failed}",
        file=sys.stderr,
    )
    if stats.errors:
        print(f"\nFirst {min(5, len(stats.errors))} errors:", file=sys.stderr)
        for e in stats.errors[:5]:
            print(f"  - bgg_id={e['bgg_id']}: {e['error']}", file=sys.stderr)

    await engine.dispose()
    # Exit-code 1 если хоть один failed (для CI). dry_run всегда 0.
    return 1 if (not args.dry_run and stats.failed > 0) else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
