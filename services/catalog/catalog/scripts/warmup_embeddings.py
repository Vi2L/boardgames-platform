"""Прогрев game_embeddings: bge-m3 vectors для всех games + game_aliases.

Использование:
    # CLI:
    uv run --package boardgames-catalog python -m catalog.scripts.warmup_embeddings
    uv run --package boardgames-catalog python -m catalog.scripts.warmup_embeddings --limit 1000

    # Через UI: POST /matching/warmup-embeddings → ImportJob → polling

Алгоритм:
  1. SELECT всех (game_id, alias_id, text) которых ещё нет в game_embeddings.
  2. Чанками по N: embed_batch(N texts) → INSERT с ON CONFLICT DO NOTHING.
  3. Прогресс пишется в ImportJob (если запущен через UI) или в stdout (CLI).

Resume: при повторном запуске пропускает уже залитые (LEFT JOIN + WHERE NULL).

Размеры:
  ~162K games + ~360K aliases = ~522K векторов.
  bge-m3 на M-series ≈ 100-200 embed/sec в batch=32.
  Полный прогон: ~1.5-3 часа. Запускать под `nohup` для CLI.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from catalog.config import get_settings
from catalog.db import get_engine
from catalog.matching.v2.embedder import OllamaError, build_text, embed_batch
from catalog.models import GameEmbedding, ImportJob

logger = logging.getLogger(__name__)


async def warmup(
    *,
    batch_size: int = 32,
    limit: int | None = None,
    only_games: bool = False,
    only_aliases: bool = False,
    job_id: int | None = None,
) -> dict[str, Any]:
    """Прогон warmup'а.

    job_id — если задан, прогресс пишется в ImportJob.progress + log_lines.
    """
    settings = get_settings()
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    started_at = time.time()
    inserted = 0
    skipped = 0
    errors = 0

    # Собираем источник эмбеддингов: title + aliases. Один запрос, UNION.
    # text_used строим в Python (build_text для game'ов с группировкой
    # title/title_ru/aliases). Здесь упрощённо: один title или один alias.
    #
    # ORDER BY priority: rank ASC NULLS LAST — топ-BGG игры идут первыми.
    # Это важно при `--limit N`: покрываем популярные игры (Carcassonne, Catan
    # и т.п.), а не случайные 162K хвостовых. Без LEFT JOIN с game_bgg игры
    # без rank всё равно попадут в конец списка.
    queries = []
    if not only_aliases:
        queries.append(
            """
            SELECT g.id AS game_id, NULL::bigint AS alias_id,
                   COALESCE(g.title_ru, '') || ' ' || g.title AS text_used,
                   COALESCE(b.rank, 999999) AS priority_rank
            FROM games g
            LEFT JOIN game_bgg b ON b.game_id = g.id
            WHERE (g.status IS NULL OR g.status != 'merged')
              AND NOT EXISTS (
                SELECT 1 FROM game_embeddings ge
                WHERE ge.game_id = g.id AND ge.alias_id IS NULL
              )
            """
        )
    if not only_games:
        queries.append(
            """
            SELECT a.game_id, a.id AS alias_id, a.alias AS text_used,
                   COALESCE(b.rank, 999999) AS priority_rank
            FROM game_aliases a
            JOIN games g ON g.id = a.game_id
            LEFT JOIN game_bgg b ON b.game_id = g.id
            WHERE (g.status IS NULL OR g.status != 'merged')
              AND NOT EXISTS (
                SELECT 1 FROM game_embeddings ge
                WHERE ge.game_id = a.game_id AND ge.alias_id = a.id
              )
            """
        )

    union_sql = " UNION ALL ".join(queries)
    union_sql = f"SELECT * FROM ({union_sql}) sub ORDER BY priority_rank ASC"
    if limit is not None:
        union_sql = f"{union_sql} LIMIT {int(limit)}"

    async with SessionFactory() as session:
        rows = (await session.execute(text(union_sql))).mappings().all()
    total = len(rows)
    logger.info("warmup_embeddings: %d targets to embed", total)

    if total == 0:
        return {"inserted": 0, "skipped": 0, "errors": 0, "total": 0}

    if job_id:
        async with SessionFactory() as session:
            await _update_job_progress(session, job_id, "embedding", 0, total, None)
            await session.commit()

    # Обрабатываем чанками
    for i in range(0, total, batch_size):
        chunk = rows[i:i + batch_size]
        texts = [r["text_used"] or "" for r in chunk]

        try:
            vectors = await embed_batch(texts)
        except OllamaError as e:
            errors += len(chunk)
            logger.warning("warmup_embeddings: batch %d failed: %s", i // batch_size, e)
            if job_id:
                async with SessionFactory() as session:
                    await _append_log(session, job_id, f"batch {i // batch_size}: {e}")
                    await session.commit()
            # Пауза перед следующим batch (Ollama overloaded?)
            await asyncio.sleep(5.0)
            continue

        # Bulk INSERT
        async with SessionFactory() as session:
            for r, vec in zip(chunk, vectors):
                stmt = (
                    pg_insert(GameEmbedding.__table__)
                    .values(
                        game_id=r["game_id"],
                        alias_id=r["alias_id"],
                        text_used=r["text_used"][:2000],  # safety
                        embedding=vec,
                        model=settings.ml_embed_model,
                    )
                    .on_conflict_do_nothing(constraint="uq_game_embeddings_pair")
                )
                result = await session.execute(stmt)
                if result.rowcount and result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            await session.commit()

        if job_id and (i // batch_size) % 10 == 0:
            async with SessionFactory() as session:
                await _update_job_progress(
                    session, job_id, "embedding",
                    current=i + len(chunk), total=total,
                    current_title=chunk[0]["text_used"][:80] if chunk else None,
                )
                await session.commit()

    elapsed = time.time() - started_at
    rate = inserted / elapsed if elapsed > 0 else 0.0
    summary = {
        "total": total,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
        "rate_per_sec": round(rate, 1),
    }
    logger.info("warmup_embeddings: done %s", summary)

    if job_id:
        async with SessionFactory() as session:
            await _update_job_progress(session, job_id, "done", total, total, None)
            await _append_log(session, job_id, f"done: {summary}")
            await session.commit()

    return summary


async def _update_job_progress(
    session, job_id: int, phase: str, current: int, total: int,
    current_title: str | None,
) -> None:
    """Обновить ImportJob.progress (для UI polling'а)."""
    job = await session.get(ImportJob, job_id)
    if job is None:
        return
    job.progress = {
        "phase": phase,
        "current": current,
        "total": total,
        "current_title": current_title,
    }


async def _append_log(session, job_id: int, line: str) -> None:
    """Добавить строку в ImportJob.log_lines (ring-buffer 200 строк)."""
    job = await session.get(ImportJob, job_id)
    if job is None:
        return
    lines = list(job.log_lines or [])
    lines.append(line)
    if len(lines) > 200:
        lines = lines[-200:]
    job.log_lines = lines


def main() -> int:
    """CLI-точка входа."""
    parser = argparse.ArgumentParser(description="Прогрев game_embeddings (bge-m3)")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only-games", action="store_true")
    parser.add_argument("--only-aliases", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    summary = asyncio.run(warmup(
        batch_size=args.batch_size,
        limit=args.limit,
        only_games=args.only_games,
        only_aliases=args.only_aliases,
    ))
    print(f"warmup done: {summary}")
    return 0 if summary.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
