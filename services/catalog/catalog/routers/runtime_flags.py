"""Admin-API для runtime-флагов (`runtime_flags` таблица).

Сейчас один пользователь — `ml_enabled` (kill-switch matching v2). PATCH
сразу инвалидирует in-memory кэш ЭТОГО процесса; другие инстансы catalog'а
подхватят значение в течение TTL (≤ 5 сек) — см. `matching/v2/runtime_flags.py`.

Эндпоинты под `admin` scope: значения этих флагов меняют поведение всего
сервиса (в данный момент — выключают ML-pipeline), а это не операция оператора
матчинга.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.runtime_flags import set_bool
from catalog.models import RuntimeFlag
from catalog.schemas import RuntimeFlagBoolUpdate, RuntimeFlagOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/runtime-flags", tags=["admin"])


# Whitelist разрешённых ключей: запрещаем оператору создавать произвольные
# флаги через PATCH — это поверхность для misconfiguration. Если нужен новый —
# добавляется кодом одновременно с потребителем.
_ALLOWED_KEYS = {"ml_enabled"}


@router.get(
    "/{key}",
    response_model=RuntimeFlagOut,
    dependencies=[Depends(require_scope("read"))],
)
async def get_flag(
    key: str,
    session: AsyncSession = Depends(get_session),
) -> RuntimeFlagOut:
    if key not in _ALLOWED_KEYS:
        raise HTTPException(status_code=404, detail=f"unknown flag: {key}")
    row = (await session.execute(
        select(RuntimeFlag).where(RuntimeFlag.key == key)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"flag '{key}' не засеян в БД (миграция 0013 не накатана?)",
        )
    return RuntimeFlagOut.model_validate(row)


@router.patch(
    "/{key}",
    response_model=RuntimeFlagOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def update_flag(
    key: str,
    payload: RuntimeFlagBoolUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RuntimeFlagOut:
    """Upsert bool-флага. Возвращает обновлённое состояние."""
    if key not in _ALLOWED_KEYS:
        raise HTTPException(status_code=404, detail=f"unknown flag: {key}")

    # `updated_by` — opaque строка для аудита. Берём API-key alias из request
    # (если есть в state), иначе — generic "api".
    updated_by = getattr(request.state, "api_key_owner", None) or "api"

    await set_bool(key, payload.value, updated_by=updated_by, session=session)
    await session.commit()

    row = (await session.execute(
        select(RuntimeFlag).where(RuntimeFlag.key == key)
    )).scalar_one()
    logger.info("runtime_flag %s set to %s (by %s)", key, payload.value, updated_by)
    return RuntimeFlagOut.model_validate(row)
