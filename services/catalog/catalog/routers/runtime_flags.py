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
from catalog.config import get_settings
from catalog.db import get_session
from catalog.runtime_flags import set_bool
from catalog.models import RuntimeFlag
from catalog.schemas import RuntimeFlagBoolUpdate, RuntimeFlagOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/runtime-flags", tags=["admin"])


# Whitelist разрешённых ключей: запрещаем оператору создавать произвольные
# флаги через PATCH — это поверхность для misconfiguration. Если нужен новый —
# добавляется кодом одновременно с потребителем.
_ALLOWED_KEYS = {"ml_enabled", "bgg_family_cascade_enabled"}


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


# ── BGG-сводка для UI Global Settings (WT-F7) ────────────────────────────────


# Отдельный сводный endpoint, а не три по отдельности — UI BGG Sync рисует одну
# секцию шапки, нужно одно обращение. token_set — bool, не значение
# (никогда не возвращаем сам токен из API).
@router.get(
    "/bgg",
    dependencies=[Depends(require_scope("read"))],
)
async def get_bgg_summary(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Сводка BGG-настроек для секции Global Settings в UI BGG Sync.

    - `bgg_api_token_set`: bool — задан ли BGG_API_TOKEN в окружении.
    - `family_cascade_enabled`: bool — берётся из runtime_flags при наличии,
      иначе Settings.bgg_family_cascade_enabled (env default). Поскольку для
      этого ключа в коммите 1 (WT-F7) ещё нет миграции-сидера, в БД его может
      не оказаться — тогда отдаём ENV-default и помечаем `source='env'`.
    - `family_cascade_rate_limit_sec`: float (ENV-only, не editable через UI).
    """
    settings = get_settings()
    flag_row = (await session.execute(
        select(RuntimeFlag).where(RuntimeFlag.key == "bgg_family_cascade_enabled")
    )).scalar_one_or_none()
    cascade_value = (
        flag_row.value_bool
        if flag_row is not None and flag_row.value_bool is not None
        else settings.bgg_family_cascade_enabled
    )
    return {
        "bgg_api_token_set": bool(settings.bgg_api_token),
        "family_cascade_enabled": cascade_value,
        "family_cascade_enabled_editable": flag_row is not None,
        "family_cascade_rate_limit_sec": settings.bgg_family_cascade_rate_limit_sec,
    }
