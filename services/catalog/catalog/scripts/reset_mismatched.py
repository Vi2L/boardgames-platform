"""Ревизия офферов с маркетплейсов: сброс «подозрительных» auto-матчей в unmatched.

Контекст. До 2026-05-18 парсеры маркетплейсов (avito, ozon, частично wb,
onlinetrade) фильтра по категории «настольные игры» не имели. В catalog
прилетали книги, велосипеды, посуда — и pg_trgm-матчер (T1) или
LLM-арбитр (T3) иногда выставляли им auto-match по схожести заголовков.
Например, книга «Гарри Поттер. Каркассон. Жан-Жак Руссо» получала
auto-match к игре «Каркассон».

После внедрения категорийных фильтров новые офферы такого мусора больше
не приносят, но **старые auto-матчи остались**. Этот скрипт находит их
по конъюнкции эвристик:

  1. Оффер из «шумного» маркетплейса (`store_slug ∈ {avito, ozon,
     onlinetrade, wildberries}`).
  2. Связан с игрой (`game_id IS NOT NULL`), `match_status = 'auto'`.
  3. Match-score ниже порога (`match_score < THRESHOLD`).

Для каждого найденного оффера:
  - `match_status` → `unmatched`
  - `game_id` → NULL
  - `match_score`/`match_tier` обнуляются
  - В `match_log` пишется action='unlink' с reason='cleanup_low_score_review'
  - Из `game_aliases` удаляются записи с `source='auto-match'` и `alias =
    offer.title_raw` — они появились как побочный эффект auto-T1 и теперь
    тоже под подозрением.

Скрипт **идемпотентен** — повторный запуск ничего не найдёт.

Запуск:

    # Dry-run (по умолчанию: только статистика, без UPDATE).
    docker compose exec catalog python -m catalog.scripts.reset_mismatched

    # Реальный сброс с порогом 0.75 (рекомендуется для T1 auto-match):
    docker compose exec catalog python -m catalog.scripts.reset_mismatched \\
        --apply --threshold 0.75

    # Только конкретный магазин:
    docker compose exec catalog python -m catalog.scripts.reset_mismatched \\
        --apply --store avito --threshold 0.8
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

logger = logging.getLogger("reset_mismatched")

DEFAULT_DSN = "postgresql+asyncpg://catalog:catalog@localhost:5433/catalog"
# Маркетплейсы, у которых до фильтра могли проскальзывать «не настолки».
# Для специализированных магазинов (hobbygames/gaga/lavkaigr/crowdgames)
# проблема не актуальна — они продают только настолки по определению.
NOISY_STORES: tuple[str, ...] = ("avito", "ozon", "onlinetrade", "wildberries")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сбросить подозрительные auto-матчи маркетплейсов в unmatched.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Действительно выполнить UPDATE (без флага — dry-run).")
    parser.add_argument("--threshold", type=float, default=0.75,
                        help="Сбрасывать офферы с match_score ниже порога "
                             "(default: 0.75 — порог T1 auto-match).")
    parser.add_argument("--store", type=str, default=None,
                        help="Ограничиться одним store_slug (по умолчанию — "
                             f"все из {NOISY_STORES}).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Ограничить число обрабатываемых офферов (для теста).")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stores = (args.store,) if args.store else NOISY_STORES
    logger.info(
        "params: apply=%s threshold=%.2f stores=%s limit=%s",
        args.apply, args.threshold, stores, args.limit,
    )

    dsn = os.environ.get("DATABASE_URL", DEFAULT_DSN)
    engine = create_async_engine(dsn)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    # Импортируем модели после init engine (избегаем циклов).
    from catalog.models import GameAlias, Offer

    async with SessionFactory() as session:
        # 1) Поиск кандидатов: auto-match с низким score из шумного магазина.
        stmt = (
            select(Offer.id, Offer.store_slug, Offer.title_raw,
                   Offer.game_id, Offer.match_score, Offer.match_tier)
            .where(
                Offer.match_status == "auto",
                Offer.store_slug.in_(stores),
                Offer.match_score < args.threshold,
            )
            .order_by(Offer.match_score.asc())
        )
        if args.limit is not None:
            stmt = stmt.limit(args.limit)
        rows = (await session.execute(stmt)).all()
        logger.info("найдено кандидатов: %d", len(rows))

        if not rows:
            return 0

        # Сводка по магазинам + score-buckets
        from collections import Counter
        by_store: Counter[str] = Counter(r.store_slug for r in rows)
        for slug, cnt in by_store.most_common():
            logger.info("  %s: %d", slug, cnt)

        if not args.apply:
            logger.info("DRY-RUN — UPDATE'ы не выполняем.")
            logger.info("Примеры (топ-10 по самому низкому score):")
            for r in rows[:10]:
                logger.info(
                    "  offer_id=%s store=%s score=%.2f tier=%s game_id=%s title=%r",
                    r.id, r.store_slug, r.match_score or 0.0, r.match_tier,
                    r.game_id, (r.title_raw or "")[:60],
                )
            return 0

        # 2) Реальный сброс — батчами по 200, чтобы транзакции были короткими.
        BATCH = 200
        total_reset = 0
        total_aliases_removed = 0
        now = datetime.now(timezone.utc)

        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            offer_ids = [r.id for r in batch]

            # 2a) Аудит-запись в match_log — ДО UPDATE, иначе prev_game_id/
            # score прочитаются уже обнулёнными. Берём данные напрямую из
            # `batch` (executemany через VALUES), не из SELECT FROM offers.
            await session.execute(
                text("""
                    INSERT INTO match_log
                        (offer_id, action, prev_game_id, new_game_id,
                         prev_status, new_status, tier, score, reason,
                         performed_by, created_at)
                    VALUES
                        (:offer_id, 'unlink', :prev_game_id, NULL,
                         'auto', 'unmatched', :tier, :score,
                         'cleanup_low_score_review',
                         'reset_mismatched', :now)
                """),
                [
                    {
                        "offer_id": r.id,
                        "prev_game_id": r.game_id,
                        "tier": r.match_tier,
                        "score": r.match_score,
                        "now": now,
                    }
                    for r in batch
                ],
            )

            # 2b) Удалить auto-match aliases для этих title_raw + game_id.
            # Сужаем по парам (game_id, title_raw) — иначе можем
            # подмести alias другой связи.
            for r in batch:
                if r.game_id is not None and r.title_raw:
                    deleted = await session.execute(
                        delete(GameAlias).where(
                            GameAlias.game_id == r.game_id,
                            GameAlias.source == "auto-match",
                            GameAlias.alias == r.title_raw,
                        )
                    )
                    total_aliases_removed += deleted.rowcount or 0

            # 2c) Reset offers в unmatched.
            await session.execute(
                update(Offer).where(Offer.id.in_(offer_ids)).values(
                    game_id=None,
                    match_status="unmatched",
                    match_score=None,
                    match_tier=None,
                    match_reason="cleanup_low_score_review",
                )
            )

            await session.commit()
            total_reset += len(batch)
            logger.info("сброшено %d/%d (aliases removed: %d)",
                        total_reset, len(rows), total_aliases_removed)

        logger.info("ГОТОВО. reset=%d aliases_removed=%d",
                    total_reset, total_aliases_removed)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
