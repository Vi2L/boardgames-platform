"""CRUD для match_decisions — Tier 0 кэш.

API:
  - lookup(): см. tiers.tier_0_cache (специализированный SELECT с TTL).
  - save(): после auto/manual матча пишем запись с TTL per source.
  - invalidate_for_game(): при unlink/reject/delete game — снимаем кэш.

TTL стратегия:
  manual         → ttl_days = NULL (∞)
  auto_t1 (trgm) → 30 дней
  auto_t2 (vec)  → 14 дней
  auto_t3 (llm)  →  7 дней
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from catalog.config import get_settings
from catalog.models import MatchDecision


def _ttl_days_for(source: str) -> int | None:
    """Возвращает TTL для записи match_decisions per source. None = бессрочно.

    `auto_t0` намеренно отсутствует — T0 cache hit означает что запись уже
    в кэше, повторное сохранение не имеет смысла. Caller (ingest) пропускает
    `save_decision` при tier=None / tier=0.
    """
    settings = get_settings()
    return {
        "manual": None,
        "auto_t1": settings.match_decisions_ttl_t1_days,
        "auto_t2": settings.match_decisions_ttl_t2_days,
        "auto_t3": settings.match_decisions_ttl_t3_days,
    }.get(source)


async def save_decision(
    session: AsyncSession,
    *,
    title_norm: str,
    game_id: int | None,
    source: str,
    tier: int | None = None,
    score: float | None = None,
) -> None:
    """Upsert в match_decisions. ON CONFLICT обновляет всё (новое решение
    свежее старого).

    `game_id` может быть None — это negative cache (reject). Source='manual'.
    """
    ttl = _ttl_days_for(source)
    stmt = (
        pg_insert(MatchDecision.__table__)
        .values(
            title_norm=title_norm,
            game_id=game_id,
            source=source,
            tier=tier,
            score=score,
            ttl_days=ttl,
        )
        .on_conflict_do_update(
            index_elements=["title_norm"],
            set_={
                "game_id": game_id,
                "source": source,
                "tier": tier,
                "score": score,
                "ttl_days": ttl,
                "decided_at": text("now()"),
            },
        )
    )
    await session.execute(stmt)


async def invalidate_for_game(session: AsyncSession, game_id: int) -> int:
    """DELETE FROM match_decisions WHERE game_id = :gid. Возвращает кол-во удалённых.

    Вызывается при: unlink, reject, merge games, удалении game вручную.
    Без этого Tier 0 продолжал бы возвращать удалённую/перемещённую игру.
    """
    result = await session.execute(
        text("DELETE FROM match_decisions WHERE game_id = :gid").bindparams(gid=game_id)
    )
    return result.rowcount or 0


async def invalidate_for_title(session: AsyncSession, title_norm: str) -> int:
    """DELETE WHERE title_norm = :norm. Используется в revert одной записи."""
    result = await session.execute(
        text("DELETE FROM match_decisions WHERE title_norm = :norm").bindparams(norm=title_norm)
    )
    return result.rowcount or 0


async def invalidate_bulk(
    session: AsyncSession,
    *,
    title_contains: str | None = None,
    only_negative: bool = False,
) -> int:
    """Bulk-delete по фильтрам (CAT-12).

    `title_contains` — подстрочный фильтр по `title_norm` (ILIKE).
    `only_negative` — только negative cache (`game_id IS NULL`),
    т.е. reject'ы и LLM `not_a_boardgame`. Манипуляция позитивным кешем
    более рискованная — следующий ingest пройдёт T1/T2/T3 заново.

    Без фильтров — НЕ удаляет всё (защита). Вернётся 0.
    """
    if title_contains is None and not only_negative:
        return 0

    conditions: list[str] = []
    params: dict = {}
    if title_contains is not None:
        conditions.append("title_norm ILIKE :pattern")
        params["pattern"] = f"%{title_contains}%"
    if only_negative:
        conditions.append("game_id IS NULL")

    sql = f"DELETE FROM match_decisions WHERE {' AND '.join(conditions)}"
    result = await session.execute(text(sql).bindparams(**params))
    return result.rowcount or 0
