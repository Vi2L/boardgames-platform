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


_PROGRESS_ACTIONS = (
    MatchAction.T2_PROGRESS.value,
    MatchAction.T3_PROGRESS.value,
)


async def log_progress(
    session: AsyncSession,
    *,
    offer_id: int,
    action: MatchAction,
    tier: int,
    payload: str,
    score: float | None = None,
    performed_by: str = "worker",
) -> int:
    """Записывает прогресс-строку в match_log БЕЗ изменения offer'а.

    Используется воркером для отображения промежуточных стадий T2/T3 в UI
    Штучного матчинга (live-stages). Не меняет offers.game_id / match_status.
    `payload` — текстовое описание (например JSON с топ-кандидатами), пишется
    в `reason` (text). `tier` — 2 для T2_PROGRESS, 3 для T3_PROGRESS.

    Revert этих записей запрещён — `revert_one` отказывает с ValueError.
    """
    if action not in (MatchAction.T2_PROGRESS, MatchAction.T3_PROGRESS):
        raise ValueError(f"log_progress: action {action} не является progress-action")
    log = MatchLog(
        offer_id=offer_id,
        action=action.value,
        prev_game_id=None,
        new_game_id=None,
        prev_status=None,
        # Progress не меняет статус — но колонка NOT NULL, пишем 'progress' как marker.
        new_status="progress",
        tier=tier,
        score=score,
        reason=payload,
        performed_by=performed_by,
    )
    session.add(log)
    await session.flush()
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
    if log.action in _PROGRESS_ACTIONS:
        # T2/T3 progress-entries — не изменения offer'а, revert бессмысленен.
        raise ValueError(f"нельзя revert progress-action ({log.action})")

    # ВАЖНО: читаем offer.title_raw ДО UPDATE — нам нужен title для очистки
    # match_decisions. Раньше offer.get вызывался ПОСЛЕ UPDATE, и при удалённом
    # оффере (CASCADE → нет offer) decisions оставались в кэше → T0 продолжал
    # возвращать «откатанный» матч. Теперь снимаем snapshot title заранее.
    offer = await session.get(Offer, log.offer_id)
    cached_title_norm: str | None = None
    if offer is not None:
        cached_title_norm = normalize_title(offer.title_raw)
    else:
        # Оффер удалён — match_log запись осталась за счёт ON DELETE CASCADE
        # на FK (это редкость, но возможно при ручном `DELETE FROM offers`).
        # Решения в decisions очистить не можем (нет title), но remaining
        # revert-логика всё равно должна выполниться: записать revert_log
        # для аудита и пометить исходный log как reverted.
        logger.warning(
            "revert_one(log_id=%d): offer_id=%d удалён, match_decisions "
            "не очищаются — T0 cache может содержать устаревший матч",
            log_id, log.offer_id,
        )

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
    if cached_title_norm is not None:
        await session.execute(
            text("DELETE FROM match_decisions WHERE title_norm = :norm")
            .bindparams(norm=cached_title_norm)
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
