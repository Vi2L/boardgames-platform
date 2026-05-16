"""Admin CRUD для auto_recovery_rules (handoff §D).

Правила реагируют на системные события (модель Ollama → closed, job завершился)
и выполняют действия (re-enqueue skipped, trigger job). Frontend в
`/matching → Очередь` показывает список с toggle/edit/delete.

Runner-job (`auto_recovery_runner` scheduler-job, scheduled separately) читает
эту таблицу раз в минуту и применяет правила. Runner — отдельный модуль, в
этом PR только CRUD-endpoints без runner'а (TODO в roadmap).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.models import AutoRecoveryRule
from catalog.schemas import (
    AutoRecoveryRuleCreate,
    AutoRecoveryRuleOut,
    AutoRecoveryRuleUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/auto-recovery-rules", tags=["admin"])


@router.get(
    "",
    response_model=list[AutoRecoveryRuleOut],
    dependencies=[Depends(require_scope("read"))],
)
async def list_rules(
    session: AsyncSession = Depends(get_session),
) -> list[AutoRecoveryRuleOut]:
    """Список всех правил, sort by enabled DESC, name ASC."""
    rows = (await session.execute(
        select(AutoRecoveryRule).order_by(
            AutoRecoveryRule.enabled.desc(),
            AutoRecoveryRule.name.asc(),
        )
    )).scalars().all()
    return [AutoRecoveryRuleOut.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=AutoRecoveryRuleOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def create_rule(
    payload: AutoRecoveryRuleCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AutoRecoveryRuleOut:
    updated_by = getattr(request.state, "api_key_owner", None) or "api"
    rule = AutoRecoveryRule(
        name=payload.name,
        condition=payload.condition,
        action=payload.action,
        enabled=payload.enabled,
        updated_by=updated_by,
    )
    session.add(rule)
    try:
        await session.commit()
    except Exception as e:  # noqa: BLE001
        # IntegrityError на UNIQUE(name) — самый частый случай.
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"правило не создано: {e}") from e
    await session.refresh(rule)
    logger.info("auto_recovery_rule created: id=%d name=%s by=%s", rule.id, rule.name, updated_by)
    return AutoRecoveryRuleOut.model_validate(rule)


@router.patch(
    "/{rule_id}",
    response_model=AutoRecoveryRuleOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def update_rule(
    rule_id: int,
    payload: AutoRecoveryRuleUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AutoRecoveryRuleOut:
    rule = await session.get(AutoRecoveryRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"rule {rule_id} not found")

    updated_by = getattr(request.state, "api_key_owner", None) or "api"
    if payload.name is not None:
        rule.name = payload.name
    if payload.condition is not None:
        rule.condition = payload.condition
    if payload.action is not None:
        rule.action = payload.action
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    rule.updated_by = updated_by
    await session.commit()
    await session.refresh(rule)
    return AutoRecoveryRuleOut.model_validate(rule)


@router.delete(
    "/{rule_id}",
    status_code=204,
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    rule = await session.get(AutoRecoveryRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"rule {rule_id} not found")
    await session.delete(rule)
    await session.commit()
    logger.info("auto_recovery_rule deleted: id=%d", rule_id)
