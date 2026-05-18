"""Runner для auto_recovery_rules (CAT-4.5).

Scheduler-job `auto_recovery_runner` (interval=60s) читает enabled=true
правила из `auto_recovery_rules` и для каждого:
  1. Проверяет condition против актуального состояния системы
     (OllamaHealth, последний ImportJob, breaker'ы parsers).
  2. Если condition выполнен И `last_triggered_at < now() - dedup_min`,
     выполняет action и обновляет last_triggered_at + last_result.

**Дедуп по времени, не edge detection.** При стабильно-выполненном
condition правило сработает раз в `dedup_min` (default 5 минут). Это
проще edge tracking'а (previous_state) и не теряет события при рестарте
сервиса. Action'ы идемпотентны: re-enqueue пустого набора → 0 строк,
trigger_job ловит `JobAlreadyRunning`.

Поддерживаемые condition types (см. миграцию 0014):
  - `circuit_state` — Ollama-модель в нужном state.
  - `breaker_state` — parsers per-store breaker (PRS-7) в нужном state.
    Требует HTTP-вызов к parsers `/api/debug/breakers`; кешируется на
    тик. Если parsers недоступен, condition НЕ выполняется (False).
  - `job_completed` — последний ImportJob нужного type имеет status='done'.

Action types:
  - `re_enqueue_skipped` — `match_queue.status='skipped'` →
    `status='pending'`. Filters: reason (LIKE), store_slug.
  - `trigger_job` — `trigger_scheduled_job(job_id)` с trigger='auto-recovery'.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.matching.v2.health import OllamaHealth
from catalog.models import AutoRecoveryRule, ImportJob

logger = logging.getLogger(__name__)

# Дефолт дедупа: чтобы UI «armed» отражал недавний trigger и не спамил.
# Override через `condition.dedup_minutes`.
_DEFAULT_DEDUP_MINUTES = 5


async def run_once(SessionFactory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """Один тик runner'а. Читает enabled rules, применяет каждое.

    Возвращает summary для логов: `{checked, triggered, errors}`.
    """
    checked = 0
    triggered = 0
    errors: list[str] = []

    # Кешируем breaker-snapshot на один тик — если несколько правил ссылаются
    # на разные store, один HTTP к parsers даст всё.
    breaker_cache: dict[str, str] | None = None

    async with SessionFactory() as session:
        rules = (await session.execute(
            select(AutoRecoveryRule).where(AutoRecoveryRule.enabled.is_(True))
        )).scalars().all()

    for rule in rules:
        checked += 1
        try:
            cond_dedup = rule.condition.get("dedup_minutes", _DEFAULT_DEDUP_MINUTES)
            if not _dedup_ok(rule.last_triggered_at, int(cond_dedup)):
                continue

            cond_type = rule.condition.get("type")
            ok = False
            if cond_type == "circuit_state":
                ok = _check_circuit_state(rule.condition)
            elif cond_type == "job_completed":
                ok = await _check_job_completed(SessionFactory, rule.condition)
            elif cond_type == "breaker_state":
                if breaker_cache is None:
                    breaker_cache = await _fetch_breaker_states()
                ok = _check_breaker_state(rule.condition, breaker_cache)
            else:
                logger.warning(
                    "auto_recovery: rule id=%d unknown condition.type=%r",
                    rule.id, cond_type,
                )
                continue

            if not ok:
                continue

            result_summary = await _execute_action(SessionFactory, rule.action)
            await _mark_triggered(SessionFactory, rule.id, result_summary)
            triggered += 1
            logger.info(
                "auto_recovery: rule '%s' triggered → %s",
                rule.name, result_summary,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("auto_recovery: rule '%s' failed", rule.name)
            errors.append(f"{rule.name}: {exc}")

    return {"checked": checked, "triggered": triggered, "errors": errors}


def _dedup_ok(last_triggered_at: datetime | None, dedup_minutes: int) -> bool:
    if last_triggered_at is None:
        return True
    return (datetime.now(timezone.utc) - last_triggered_at) >= timedelta(minutes=dedup_minutes)


# ── condition checkers ──────────────────────────────────────────────────


def _check_circuit_state(condition: dict[str, Any]) -> bool:
    """`condition`: {type: circuit_state, model: str, becomes: 'closed'|'open'|'half_open'}.

    `becomes` — целевое состояние. Если модель сейчас в нужном state,
    condition выполнен (дедуп защищает от перетриггера).
    """
    model = condition.get("model")
    becomes = condition.get("becomes", "closed")
    if not model:
        return False
    health = OllamaHealth.get_instance()
    summary = health.status_summary
    cur_state = summary.get("circuit_state", {}).get(model, "unknown")
    return cur_state == becomes


async def _check_job_completed(
    SessionFactory: async_sessionmaker[AsyncSession],
    condition: dict[str, Any],
) -> bool:
    """`condition`: {type: job_completed, job_type: str, status?: 'done'}.

    Проверяет последний ImportJob нужного типа. Default status='done'.
    """
    job_type = condition.get("job_type") or condition.get("type_filter")
    if not job_type:
        return False
    target_status = condition.get("status", "done")

    async with SessionFactory() as session:
        row = (await session.execute(
            select(ImportJob.status, ImportJob.created_at)
            .where(ImportJob.type == job_type)
            .order_by(ImportJob.created_at.desc())
            .limit(1)
        )).first()
    if row is None:
        return False
    return row.status == target_status


def _check_breaker_state(
    condition: dict[str, Any], cache: dict[str, str],
) -> bool:
    """`condition`: {type: breaker_state, store: str, becomes: 'closed'|'open'|'half_open'}.

    Опирается на закешированный snapshot из `/api/debug/breakers` parsers.
    """
    store = condition.get("store")
    becomes = condition.get("becomes", "closed")
    if not store:
        return False
    return cache.get(store) == becomes


async def _fetch_breaker_states() -> dict[str, str]:
    """HTTP GET к parsers `/api/debug/breakers`. Возвращает {store: state}.

    При ошибке/недоступности возвращает {} — все breaker-conditions
    автоматически невыполнены.
    """
    from catalog.config import get_settings
    base = (get_settings().parsers_base_url or "").rstrip("/")
    if not base:
        logger.debug("auto_recovery: PARSERS_BASE_URL не задан, breaker-conditions skip")
        return {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/api/debug/breakers")
            resp.raise_for_status()
            data = resp.json()
        return {b["store"]: b["state"] for b in data.get("breakers", [])}
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_recovery: failed to fetch breakers: %s", exc)
        return {}


# ── action executors ────────────────────────────────────────────────────


async def _execute_action(
    SessionFactory: async_sessionmaker[AsyncSession],
    action: dict[str, Any],
) -> str:
    """Возвращает короткую summary-строку для last_result."""
    action_type = action.get("type")
    if action_type == "re_enqueue_skipped":
        return await _action_re_enqueue(SessionFactory, action)
    if action_type == "trigger_job":
        return await _action_trigger_job(action)
    return f"unknown_action: {action_type}"


async def _action_re_enqueue(
    SessionFactory: async_sessionmaker[AsyncSession],
    action: dict[str, Any],
) -> str:
    """`action`: {type: re_enqueue_skipped, filters: {reason?: [str], store_slug?: [str]}}.

    Скопирована логика из `routers/matching.re_enqueue_skipped`.
    Идемпотентно: при пустом filter'е дёрнет все skipped, обычно — 0.
    """
    filters = action.get("filters", {})
    where: list[str] = ["status = 'skipped'"]
    params: dict[str, Any] = {}
    if reasons := filters.get("reason"):
        where.append(
            "EXISTS (SELECT 1 FROM unnest(CAST(:reasons AS text[])) r "
            "WHERE error_detail LIKE r || '%')"
        )
        params["reasons"] = reasons if isinstance(reasons, list) else [reasons]
    if stores := filters.get("store_slug"):
        where.append("store_slug = ANY(:stores)")
        params["stores"] = stores if isinstance(stores, list) else [stores]
    where_sql = " AND ".join(where)

    async with SessionFactory() as session:
        result = await session.execute(
            text(
                f"""
                UPDATE match_queue
                SET status = 'pending', attempts = 0, next_attempt_at = NULL,
                    error_detail = NULL, processed_at = NULL, claimed_at = NULL,
                    result_game_id = NULL, result_score = NULL, result_tier = NULL
                WHERE {where_sql}
                """
            ).bindparams(**params)
        )
        await session.commit()
        n = result.rowcount or 0
    return f"re_enqueued={n}"


async def _action_trigger_job(action: dict[str, Any]) -> str:
    """`action`: {type: trigger_job, job_id: str, params?: dict}."""
    job_id = action.get("job_id")
    if not job_id:
        return "no_job_id"
    params = action.get("params") or {}
    from catalog.scheduler import JobAlreadyRunning, trigger_scheduled_job
    try:
        import_job_id = await trigger_scheduled_job(
            job_id, params, trigger="auto-recovery",
        )
        return f"triggered={job_id} import_job={import_job_id}"
    except JobAlreadyRunning as exc:
        return f"skipped_already_running: {exc}"


# ── helpers ─────────────────────────────────────────────────────────────


async def _mark_triggered(
    SessionFactory: async_sessionmaker[AsyncSession],
    rule_id: int,
    result_summary: str,
) -> None:
    """Обновляет last_triggered_at + last_result."""
    async with SessionFactory() as session:
        rule = await session.get(AutoRecoveryRule, rule_id)
        if rule is None:
            return
        rule.last_triggered_at = datetime.now(timezone.utc)
        rule.last_result = result_summary[:500]
        await session.commit()
