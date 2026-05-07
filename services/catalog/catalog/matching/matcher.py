"""Матчер оффер'ов из магазинов на канонические Game.

Алгоритм:
1. По присланному `title_raw` ищем в `games.title_norm` И в `game_aliases.alias_norm`
   через pg_trgm `%`-оператор (уже под GIN-индексом).
2. Берём максимальный similarity по всем источникам.
3. Если ≥ AUTO_MATCH_THRESHOLD — это auto-match.
4. Если ≥ MIN_CANDIDATE_THRESHOLD но ниже auto — оффер идёт в unmatched-queue
   с записанным `match_score` (так оператор видит лучшего кандидата).
5. Иначе — unmatched, match_score=NULL (полностью посторонний товар).

AUTO_MATCH_THRESHOLD = 0.6 — компромисс. На pg_trgm трёхбуквенных триграммах
русский «Каркассон» vs «Каркасон» даёт ~0.73; «Колонизаторы» vs «колонизатор»
~0.85. 0.6 уверенно ловит опечатки и обрезанные хвосты, не давая false-positive
на разных играх.

Эвристики на будущее (не реализовано здесь):
- бонус +0.1, если совпало по alias, а не по title (alias добавляли руками)
- штраф, если не совпали publisher / year (но мы их в parsers'ах редко имеем)
- учёт расширений: «Каркассон: Король и разбойник» не должна матчиться
  на базовую «Каркассон» (для этого — проверка длины и наличия `:`)
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTO_MATCH_THRESHOLD = 0.6
MIN_CANDIDATE_THRESHOLD = 0.3  # ниже — даже не показываем оператору


@dataclass(frozen=True)
class MatchCandidate:
    game_id: int
    score: float
    via: str  # 'title' | 'alias'


async def find_best_match(
    session: AsyncSession, title_raw: str
) -> MatchCandidate | None:
    """Возвращает лучшего кандидата (score ≥ MIN_CANDIDATE_THRESHOLD) или None.

    Один SQL-запрос с UNION'ом из двух источников. Использует pg_trgm индексы.
    """
    stmt = text(
        """
        WITH q AS (SELECT lower(immutable_unaccent(:q)) AS norm),
        from_title AS (
            SELECT g.id AS game_id,
                   similarity(g.title_norm, q.norm) AS score,
                   'title'::text AS via
            FROM games g, q
            WHERE g.title_norm % q.norm
        ),
        from_alias AS (
            SELECT a.game_id,
                   similarity(a.alias_norm, q.norm) AS score,
                   'alias'::text AS via
            FROM game_aliases a, q
            WHERE a.alias_norm % q.norm
        ),
        all_matches AS (
            SELECT * FROM from_title
            UNION ALL
            SELECT * FROM from_alias
        )
        SELECT game_id, score, via
        FROM all_matches
        WHERE score >= :threshold
        ORDER BY score DESC
        LIMIT 1
        """
    ).bindparams(q=title_raw, threshold=MIN_CANDIDATE_THRESHOLD)
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return MatchCandidate(game_id=row.game_id, score=float(row.score), via=row.via)


def classify(score: float | None) -> str:
    """`auto` если score ≥ AUTO_MATCH_THRESHOLD, иначе `unmatched`."""
    if score is None:
        return "unmatched"
    return "auto" if score >= AUTO_MATCH_THRESHOLD else "unmatched"
