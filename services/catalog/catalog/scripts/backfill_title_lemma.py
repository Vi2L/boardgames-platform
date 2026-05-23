"""CLI-скрипт: backfill `games.title_lemma` через pymorphy3 (CAT-17.3).

Один раз после миграции 0021 — для существующих ~162K игр. Идемпотентный
(WHERE title_lemma IS NULL), можно прерывать и перезапускать.

Использование:

    # Локально (хост, postgres :5433):
    uv run --package boardgames-catalog python -m catalog.scripts.backfill_title_lemma

    # В Docker (postgres :5432 через docker network):
    docker compose exec catalog python -m catalog.scripts.backfill_title_lemma

    # Опционально: --limit 1000 для пробного прогона
    uv run --package boardgames-catalog python -m catalog.scripts.backfill_title_lemma --limit 1000

Логика:
  - Batch'ами по 500 (`--batch-size`) читаем `id, title, title_ru WHERE title_lemma IS NULL`.
  - Для каждого: lemmatize_ru(title_ru if title_ru else title).
  - UPDATE games SET title_lemma = :lemma WHERE id = :id (один UPDATE per batch).
  - Прогресс печатается через tqdm.

Производительность: pymorphy3 ~5000 токенов/сек на современном CPU. 162K игр
× ~3 токена в title = ~500K токенов = ~100 секунд лемматизации + I/O. На
практике ~10-15 минут с учётом транзакций и фиксации.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from catalog.db import get_engine
from catalog.matching.morphology import lemmatize_ru
from catalog.models import Game


async def _backfill(
    *, batch_size: int = 500, limit: int | None = None, dry_run: bool = False,
) -> int:
    """Возвращает число обновлённых строк."""
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    updated_total = 0
    processed_total = 0
    started = time.monotonic()

    async with SessionFactory() as session:
        # Сколько всего unprocessed?
        total = (await session.execute(
            text("SELECT COUNT(*) FROM games WHERE title_lemma IS NULL")
        )).scalar_one()
        print(f"[backfill] всего записей без title_lemma: {total}", flush=True)
        if limit is not None:
            total = min(total, limit)
            print(f"[backfill] лимит --limit {limit}, обработаем не больше", flush=True)

        # Идём батчами, чтобы не держать в памяти 162K объектов.
        # При обычном прогоне offset не нужен — UPDATE сразу убирает строки
        # из выборки `WHERE title_lemma IS NULL`. При `--dry-run` UPDATE не
        # делается, выборка не «сжимается» → нужно явно сдвигать offset,
        # иначе бесконечный цикл (фикс CR-C).
        offset = 0
        while True:
            remaining = total - processed_total
            if remaining <= 0:
                break
            batch_n = min(batch_size, remaining)

            stmt = (
                select(Game.id, Game.title, Game.title_ru)
                .where(Game.title_lemma.is_(None))
                .order_by(Game.id)
                .limit(batch_n)
            )
            if dry_run:
                # В dry-run строки не пропадают из выборки → нужен offset,
                # иначе читаем одну и ту же пачку бесконечно.
                stmt = stmt.offset(offset)
            rows = (await session.execute(stmt)).all()
            if not rows:
                break

            # Лемматизация — синхронная, но дешёвая (~5000 токенов/сек).
            # Используем title_ru если есть (русские игры), иначе title (EN).
            updates = []
            for game_id, title_en, title_ru in rows:
                source_text = title_ru if title_ru else title_en
                lemma = lemmatize_ru(source_text or "")
                # Защита от пустых строк — пустой lemma == "" нам не нужен в
                # индексе (он триггернёт false-positive на любой пустой query).
                if not lemma:
                    lemma = (source_text or "").lower()
                updates.append({"id": game_id, "lemma": lemma})

            if not dry_run:
                # Bulk UPDATE одной транзакцией. UPDATE ... FROM VALUES ... в Postgres
                # был бы оптимальнее, но executemany для 500 строк тоже норм.
                await session.execute(
                    text("UPDATE games SET title_lemma = :lemma WHERE id = :id"),
                    updates,
                )
                await session.commit()
                updated_total += len(updates)
            else:
                # dry-run: продвигаем offset вручную, чтобы следующий запрос
                # вернул другую пачку.
                offset += len(rows)

            processed_total += len(rows)
            elapsed = time.monotonic() - started
            rate = processed_total / elapsed if elapsed > 0 else 0.0
            print(
                f"[backfill] обработано {processed_total}/{total} "
                f"({100*processed_total/total:.1f}%), "
                f"скорость {rate:.0f} строк/сек, "
                f"осталось ~{(total - processed_total)/rate:.0f} сек"
                if rate > 0 else f"[backfill] обработано {processed_total}/{total}",
                flush=True,
            )

    elapsed_final = time.monotonic() - started
    print(
        f"[backfill] готово: {'(DRY RUN) ' if dry_run else ''}"
        f"обработано {processed_total}, обновлено {updated_total} "
        f"за {elapsed_final:.1f} сек",
        flush=True,
    )
    return updated_total


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill games.title_lemma через pymorphy3")
    ap.add_argument(
        "--batch-size", type=int, default=500,
        help="размер UPDATE-батча (default 500)",
    )
    ap.add_argument(
        "--limit", type=int, default=None,
        help="обработать не больше N игр (для тестового прогона)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="не делать UPDATE, только посчитать и показать оценку времени",
    )
    args = ap.parse_args()

    updated = asyncio.run(_backfill(
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
    ))
    return 0 if updated >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
