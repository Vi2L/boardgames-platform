"""Tier 2: bge-m3 cosine search через pgvector.

Поток:
  1. embed query через OllamaEmbedder → vector(1024)
  2. SELECT WITH ORDER BY embedding <=> :vec LIMIT top_k → top-K кандидатов
  3. classify:
       best.score >= auto_threshold (0.85) AND нет другого близкого → matched
       2+ кандидата >= min_score (0.70) → отдаём в T3 (LLM арбитр)
       1 кандидат с 0.70..0.85 → возврат как needs T3 (если LLM up) или T4
       нет ≥ 0.70 → no_candidates

vec_search_top_k() возвращает list[dict] с метаданными игры (title, title_ru,
year, kind) — это нужно для prompt'а T3 LLM-арбитра.

Cosine semantics: pgvector `<=>` это distance (0..2), `1 - distance` = similarity.
Используем `1 - (embedding <=> :vec)` AS score в SELECT для удобства.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.matching.v2.domain import MatchAction, MatchContext, MatchResult
from catalog.matching.v2.embedder import OllamaError, embed_one

logger = logging.getLogger(__name__)


async def vec_search_top_k(
    session: AsyncSession,
    embedding: list[float],
    *,
    top_k: int = 5,
    kind_filter: str | None = None,
) -> list[dict]:
    """Cosine-поиск ближайших векторов в game_embeddings.

    GROUP BY game_id (одна game = один результат) с MAX score, чтобы дубликаты
    title/alias эмбеддингов не вытесняли разные игры из top-K.

    Сначала получаем top_k * 4 строк (на случай дубликатов) с ORDER BY <=>,
    потом GROUP BY и берём top_k по best.

    kind_filter (например, 'expansion') фильтрует по games.kind в JOIN.
    """
    # pgvector ожидает строковое представление вектора '[0.1, 0.2, ...]'.
    vec_str = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"

    sql = """
        WITH ranked AS (
            SELECT ge.game_id,
                   ge.text_used,
                   1 - (ge.embedding <=> :vec ::vector) AS score,
                   ge.alias_id
            FROM game_embeddings ge
            JOIN games g ON g.id = ge.game_id
            WHERE g.status IS NULL OR g.status != 'merged'
            { kind_clause }
            ORDER BY ge.embedding <=> :vec ::vector
            LIMIT :pre_limit
        ),
        per_game AS (
            SELECT game_id,
                   MAX(score) AS score,
                   (ARRAY_AGG(text_used ORDER BY score DESC))[1] AS matched_text,
                   (ARRAY_AGG(alias_id ORDER BY score DESC))[1] AS alias_id
            FROM ranked
            GROUP BY game_id
        )
        SELECT pg.game_id,
               pg.score::float AS score,
               pg.matched_text,
               pg.alias_id,
               g.title,
               g.title_ru,
               g.year,
               g.kind
        FROM per_game pg
        JOIN games g ON g.id = pg.game_id
        ORDER BY pg.score DESC
        LIMIT :top_k
    """
    kind_clause = "AND g.kind = :kind" if kind_filter else ""
    sql = sql.replace("{ kind_clause }", kind_clause)

    bind = {"vec": vec_str, "pre_limit": top_k * 4, "top_k": top_k}
    if kind_filter:
        bind["kind"] = kind_filter

    rows = (await session.execute(text(sql).bindparams(**bind))).mappings().all()
    return [
        {
            "game_id": int(r["game_id"]),
            "score": float(r["score"]),
            "title": r["title"],
            "title_ru": r["title_ru"],
            "year": r["year"],
            "kind": r["kind"],
            "matched_text": r["matched_text"],
            "alias_id": r["alias_id"],
            "via": "embedding",
        }
        for r in rows
    ]


async def tier_2_vector(
    session: AsyncSession,
    ctx: MatchContext,
    *,
    top_k: int = 5,
    auto_threshold: float = 0.85,
    min_score: float = 0.70,
) -> MatchResult | None:
    """T2: получить embedding и найти top-K в pgvector.

    Возвращает:
      - matched MatchResult (tier=2) если best ≥ auto_threshold и единственный
        близкий (никто другой не >= auto_threshold - 0.05).
      - unmatched MatchResult (candidates=N) если 2+ кандидата >= min_score —
        для T3 LLM-арбитра.
      - unmatched MatchResult (score=best) если 1 кандидат < auto_threshold.
      - None если совсем нет кандидатов с score >= min_score.

    OllamaError → пропагируем наружу: worker откатит queue в pending.
    """
    try:
        embedding = await embed_one(ctx.title_raw)
    except OllamaError as e:
        logger.warning("tier_2_vector: embed_one failed: %s", e)
        raise  # worker handle'ит retry / requeue

    candidates = await vec_search_top_k(
        session, embedding, top_k=top_k,
        kind_filter=ctx.predicted_kind,  # None = no filter
    )

    if not candidates:
        return MatchResult(
            game_id=None,
            tier=2,
            action=None,
            reason="vec_no_candidates",
        )

    best = candidates[0]
    above_min = [c for c in candidates if c["score"] >= min_score]

    # Только лучший выше auto_threshold + остальные значительно ниже = confident.
    margin = 0.05
    if best["score"] >= auto_threshold and (
        len(above_min) == 1 or above_min[1]["score"] < auto_threshold - margin
    ):
        return MatchResult(
            game_id=best["game_id"],
            score=best["score"],
            tier=2,
            action=MatchAction.AUTO_T2,
            reason="vec_confident",
            candidates=candidates,
        )

    # Иначе — нужен T3 (несколько близких) или manual (один < auto_threshold).
    return MatchResult(
        game_id=None,
        score=best["score"],
        tier=2,
        action=None,
        reason=("vec_ambiguous" if len(above_min) >= 2 else "vec_below_threshold"),
        candidates=above_min if above_min else candidates,
    )
