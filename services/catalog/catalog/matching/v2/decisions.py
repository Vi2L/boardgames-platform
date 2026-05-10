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
    """Возвращает TTL для записи match_decisions per source. None = бессрочно."""
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
