"""Sync tier'ы (T0, T1) — выполняются прямо в `/ingest/offers` handler'е.

T0 (alias cache):
  Один SELECT по match_decisions WHERE title_norm = :norm AND age < ttl_days.
  Если hit → instant match, MatchResult(tier=0). Это самый частый случай для
  повторных ingest'ов одного и того же товара.

T1 (pg_trgm 0.92):
  Узкий safety-net. Используется существующий paradigm `find_best_match`,
  но порог поднят с 0.6 до 0.92. Это значит: T1 берёт только почти-точные
  совпадения (опечатка в одну букву, разный регистр, другая локализация).
  Всё ниже 0.92 — в очередь T2.

Async tier'ы (T2, T3) — в `engine.py:match_async()`, выполняются воркером.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.matching.v2.domain import MatchAction, MatchResult


async def tier_0_cache(session: AsyncSession, title_norm: str) -> MatchResult | None:
    """Поиск в match_decisions по нормализованному title.

    Возвращает MatchResult(matched=True, tier=0) если запись есть и не TTL'нулась.
    None — иначе (cache miss или expired).

    TTL логика inline в SQL: WHERE ttl_days IS NULL OR (decided_at + ttl_days days > now()).
    Для negative cache (game_id IS NULL — оператор reject'нул как "не игра")
    — отдаём MatchResult(matched=False, tier=0, action=REJECT, reason='cached_reject').
    """
    row = (await session.execute(
        text(
            """
            SELECT game_id, source, score, tier, ttl_days, decided_at
            FROM match_decisions
            WHERE title_norm = :norm
              AND (
                ttl_days IS NULL
                OR decided_at > now() - (ttl_days || ' days')::interval
              )
            LIMIT 1
            """
        ).bindparams(norm=title_norm)
    )).mappings().first()

    if row is None:
        return None

    if row["game_id"] is None:
        # Negative cache: оператор когда-то нажал reject. Не пушим в очередь
        # повторно — уважаем решение.
        return MatchResult(
            game_id=None,
            score=None,
            tier=0,
            action=MatchAction.REJECT,
            reason="cached_reject",
        )

    return MatchResult(
        game_id=int(row["game_id"]),
        score=float(row["score"]) if row["score"] is not None else None,
        tier=0,
        action=MatchAction.AUTO_T0,
        reason=f"cache_hit_{row['source']}",
    )


async def tier_1_trgm(
    session: AsyncSession,
    title_raw: str,
    *,
    auto_threshold: float = 0.92,
) -> MatchResult | None:
    """pg_trgm similarity по games.title_norm + games.title_ru + game_aliases.

    UNION четырёх источников с разными весами:
      - games.title (en canonical)            × 1.0
      - games.title_ru (ru canonical)         × 1.0
      - game_aliases по ru-source             × 1.0  (manual/dicefest/wikidata)
      - game_aliases остальные (auto-match, en) × 1.0
    GROUP BY game_id + MAX(score) — одна игра = один кандидат с лучшим score.

    Возвращает:
      MatchResult(tier=1, matched=True) — если best score >= auto_threshold (0.92).
      MatchResult(tier=1, matched=False, candidates=[top-N]) — для контекста T2.
      None — если совсем нет кандидатов с score ≥ 0.30 (cold).

    Расширения (миграция 0006: games.kind='expansion'): не пенализируем здесь —
    это делает LLM-арбитр в T3, который видит kind в кандидатах и принимает
    решение «база vs дополнение».
    """
    stmt = text(
        """
        WITH q AS (SELECT lower(immutable_unaccent(:q)) AS norm),
        from_title_en AS (
            SELECT g.id AS game_id,
                   similarity(g.title_norm, q.norm) AS score,
                   'title_en'::text AS via,
                   g.title AS matched_text
            FROM games g, q
            WHERE g.title_norm % q.norm
              AND (g.status IS NULL OR g.status != 'merged')
        ),
        from_title_ru AS (
            SELECT g.id AS game_id,
                   similarity(lower(immutable_unaccent(g.title_ru)), q.norm) AS score,
                   'title_ru'::text AS via,
                   g.title_ru AS matched_text
            FROM games g, q
            WHERE g.title_ru IS NOT NULL
              AND lower(immutable_unaccent(g.title_ru)) % q.norm
              AND (g.status IS NULL OR g.status != 'merged')
        ),
        from_alias AS (
            SELECT a.game_id,
                   similarity(a.alias_norm, q.norm) AS score,
                   ('alias_' || COALESCE(a.language, 'unk'))::text AS via,
                   a.alias AS matched_text
            FROM game_aliases a, q
            WHERE a.alias_norm % q.norm
        ),
        all_matches AS (
            SELECT * FROM from_title_en
            UNION ALL SELECT * FROM from_title_ru
            UNION ALL SELECT * FROM from_alias
        ),
        per_game AS (
            SELECT game_id,
                   MAX(score) AS score,
                   (ARRAY_AGG(via       ORDER BY score DESC))[1] AS via,
                   (ARRAY_AGG(matched_text ORDER BY score DESC))[1] AS matched_text
            FROM all_matches
            WHERE score >= 0.30
            GROUP BY game_id
        )
        SELECT pg.game_id,
               pg.score::float AS score,
               pg.via,
               pg.matched_text,
               g.title,
               g.title_ru,
               g.year,
               g.kind
        FROM per_game pg
        JOIN games g ON g.id = pg.game_id
        ORDER BY pg.score DESC
        LIMIT 5
        """
    ).bindparams(q=title_raw)

    rows = list((await session.execute(stmt)).mappings().all())
    if not rows:
        return None

    best = rows[0]
    candidates = [
        {
            "game_id": int(r["game_id"]),
            "title": r["title"],
            "title_ru": r["title_ru"],
            "year": r["year"],
            "kind": r["kind"],
            "score": float(r["score"]),
            "via": r["via"],
            "matched_text": r["matched_text"],
        }
        for r in rows
    ]

    if best["score"] >= auto_threshold:
        return MatchResult(
            game_id=int(best["game_id"]),
            score=float(best["score"]),
            tier=1,
            action=MatchAction.AUTO_T1,
            reason=f"trgm_{best['via']}",
            candidates=candidates,
        )

    # Кандидаты есть, но < 0.92 — отдаём для T2.
    return MatchResult(
        game_id=None,
        score=float(best["score"]),
        tier=1,
        action=None,
        reason="trgm_below_threshold",
        candidates=candidates,
    )
