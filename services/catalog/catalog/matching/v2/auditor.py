"""Аудит изменений offers.game_id/match_status в `match_log`.

Запись через явный вызов из service-слоя (engine, routers/ingest, routers/matching),
не через DB-триггер. Причины:
  - триггер не знает performed_by (system|worker|llm|api-key)
  - триггер не различает action (auto_t1 vs manual vs reassess)
  - тесты с фейковым auditor'ом без живой БД

Единая точка `log_change()` гарантирует консистентность: prev_/new_ pair всегда
снимается в одной транзакции с UPDATE offers — не теряется при rollback.

Bulk-revert через `revert_batch(batch_id)`: одной транзакцией восстанавливаем
prev_state у всех offers в batch'е и помечаем log-записи reverted_at=now().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.matching.v2.domain import MatchAction, normalize_title
from catalog.models import GameAlias, MatchDecision, MatchLog, Offer

logger = logging.getLogger(__name__)


async def log_change(
    session: AsyncSession,
    *,
    offer_id: int,
    action: MatchAction,
    prev_game_id: int | None,
    new_game_id: int | None,
    prev_status: str | None,
    new_status: str,
    tier: int | None = None,
    score: float | None = None,
    reason: str | None = None,
    batch_id: UUID | None = None,
    alias_created_id: int | None = None,
    performed_by: str = "system",
) -> int:
    """Создаёт запись в match_log. Возвращает id записи.

    Не делает commit — caller отвечает за транзакцию. Это критично для
    атомарности с UPDATE offers.

    `alias_created_id` — id alias'а, созданного в этой же операции (auto-match
    добавляет title_raw как alias). При revert(delete_alias=True) удаляем
    конкретно эту запись, а не все алиасы оффера.
    """
    log = MatchLog(
        offer_id=offer_id,
        action=action.value if isinstance(action, MatchAction) else str(action),
        prev_game_id=prev_game_id,
        new_game_id=new_game_id,
        prev_status=prev_status,
        new_status=new_status,
        tier=tier,
        score=score,
        reason=reason,
        batch_id=batch_id,
        alias_created_id=alias_created_id,
        performed_by=performed_by,
    )
    session.add(log)
    await session.flush()  # получаем log.id без commit
    return log.id


async def revert_one(
    session: AsyncSession,
    log_id: int,
    *,
    performed_by: str = "operator",
    delete_alias: bool = False,
) -> dict[str, Any]:
    """Откат одной записи match_log.

    Восстанавливает у offer prev_game_id + prev_status. Опционально удаляет
    alias, добавленный этой записью (alias_created_id). Удаляет соответствующую
    строку в match_decisions (чтобы Tier 0 не вернул отменённый матч).

    Не трогает match_log запись'и, которые уже reverted (409). Не трогает
    revert-action записи (нельзя revert revert).

    Возвращает dict для роутера: {log_id, offer_id, restored_status, ...}.
    """
    log = await session.get(MatchLog, log_id)
    if log is None:
        raise ValueError(f"match_log.id={log_id} not found")
    if log.reverted_at is not None:
        raise ValueError(f"match_log.id={log_id} already reverted at {log.reverted_at}")
    if log.action == MatchAction.REVERT.value:
        raise ValueError("нельзя revert revert-action")

    # Восстанавливаем оффер
    await session.execute(
        update(Offer)
        .where(Offer.id == log.offer_id)
        .values(
            game_id=log.prev_game_id,
            match_status=log.prev_status or "unmatched",
            # match_score, match_tier, match_reason оставляем — они диагностика,
            # не источник истины. Реальный смысл несёт match_status.
        )
    )

    # Удаляем match_decisions для этого title — чтобы T0 не отдал старый матч.
    # ВАЖНО: используем тот же `normalize_title()` (NFKD + strip + lower), что и
    # при записи в save_decision. Postgres `immutable_unaccent` НЕ эквивалентен
    # NFKD (например, лигатура 'ﬁ' через NFKD → 'fi', через unaccent остаётся);
    # инвалидация по SQL-нормализации могла бы не найти запись.
    offer = await session.get(Offer, log.offer_id)
    if offer is not None:
        await session.execute(
            text("DELETE FROM match_decisions WHERE title_norm = :norm")
            .bindparams(norm=normalize_title(offer.title_raw))
        )

    # Опциональное удаление alias
    if delete_alias and log.alias_created_id is not None:
        alias = await session.get(GameAlias, log.alias_created_id)
        if alias is not None:
            await session.delete(alias)

    # Помечаем log как reverted
    log.reverted_at = datetime.now(timezone.utc)
    log.reverted_by = performed_by

    # Записываем revert-action отдельной строкой (для аудита: «кто откатил и когда»)
    revert_log = MatchLog(
        offer_id=log.offer_id,
        action=MatchAction.REVERT.value,
        prev_game_id=log.new_game_id,
        new_game_id=log.prev_game_id,
        prev_status=log.new_status,
        new_status=log.prev_status or "unmatched",
        tier=None,
        score=None,
        reason=f"revert of log #{log_id}",
        batch_id=log.batch_id,  # тот же batch_id, чтобы группировать в UI
        performed_by=performed_by,
    )
    session.add(revert_log)
    await session.flush()

    return {
        "log_id": log_id,
        "offer_id": log.offer_id,
        "revert_log_id": revert_log.id,
        "restored_game_id": log.prev_game_id,
        "restored_status": log.prev_status or "unmatched",
        "alias_deleted": delete_alias and log.alias_created_id is not None,
    }


async def revert_batch(
    session: AsyncSession,
    batch_id: UUID,
    *,
    performed_by: str = "operator",
    delete_alias: bool = False,
) -> dict[str, Any]:
    """Bulk-revert по batch_id одной транзакцией.

    Все записи match_log с одним batch_id (например, один reassess-all) ↔
    атомарно откатить. Записи, которые уже были reverted'ы — пропускаются
    (idempotent повторный bulk не падает).

    Возвращает counts: {requested, reverted, skipped}.
    """
    rows = (await session.execute(
        select(MatchLog).where(
            MatchLog.batch_id == batch_id,
            MatchLog.reverted_at.is_(None),
            MatchLog.action != MatchAction.REVERT.value,
        )
    )).scalars().all()

    if not rows:
        return {"requested": 0, "reverted": 0, "skipped": 0}

    reverted = 0
    skipped = 0
    for log in rows:
        try:
            await revert_one(
                session, log.id, performed_by=performed_by, delete_alias=delete_alias,
            )
            reverted += 1
        except ValueError as e:
            logger.warning("revert_batch: skipping log %d: %s", log.id, e)
            skipped += 1

    return {
        "requested": len(rows),
        "reverted": reverted,
        "skipped": skipped,
        "batch_id": str(batch_id),
    }


async def revert_many(
    session: AsyncSession,
    log_ids: list[int],
    *,
    performed_by: str = "operator",
    delete_alias: bool = False,
) -> dict[str, Any]:
    """Bulk-revert по списку id (когда оператор выбрал чекбоксами в UI)."""
    reverted = 0
    skipped = 0
    errors: list[dict] = []
    for log_id in log_ids:
        try:
            await revert_one(
                session, log_id, performed_by=performed_by, delete_alias=delete_alias,
            )
            reverted += 1
        except ValueError as e:
            skipped += 1
            errors.append({"log_id": log_id, "error": str(e)})

    return {
        "requested": len(log_ids),
        "reverted": reverted,
        "skipped": skipped,
        "errors": errors,
    }
