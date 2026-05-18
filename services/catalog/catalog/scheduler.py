"""APScheduler для периодической синхронизации BGG.

Запускается в lifespan catalog/api.py. Использует AsyncIOScheduler — работает
в том же event loop, что и uvicorn, без отдельного потока.

Зарегистрированные job'ы (миграция 0010 сидит дефолты в `scheduler_configs`):
  bgg_top_sync     — enrich_batch(rank_le=N, skip_recent_days=7) еженедельно.
  bgg_hotness_sync — fetch /hot → bgg_hotness + auto-import ежедневно.
  bgg_mini_batch   — daily catch-up enrichment 500-1000 игр (мягкий rate-limit).

Все три:
  - max_instances=1: не запускает параллельную копию если предыдущая ещё идёт.
  - coalesce=True: если сервис был down и пропустил запуск — выполнит один раз
    при старте, а не N раз подряд.
  - Унифицированы через `trigger_scheduled_job(job_id, params, trigger)` —
    создают ImportJob с `payload.trigger='scheduled'` и используют общую
    history через `GET /import/jobs?trigger=scheduled`.

Cron-выражения и `params` хранятся в `scheduler_configs` (миграция 0010), а не
в Settings. UI меняет их через PATCH /scheduler/jobs/{id} с hot-reload через
`scheduler.reschedule_job()` — без рестарта сервиса.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobAlreadyRunning(Exception):
    """trigger_scheduled_job отказался стартовать второй экземпляр того же job-type.

    Используется и для manual-trigger через POST /scheduler/jobs/{id}/trigger
    (роутер мапит в HTTP 409), и для cron-срабатываний (просто логируется).
    """


# ── Schema-driven UI для редактирования params (WT-F7) ───────────────────────
# UI получает per-job `params_schema: list[FieldSpec]` через `GET /scheduler/jobs`
# и рендерит динамическую форму вместо сырого JSON-textarea. На бэке используется
# для server-side validate в PATCH /scheduler/jobs/{id} (точный тип, диапазон, enum).
class FieldSpec(TypedDict, total=False):
    """Описание одного поля в schema-driven форме параметров job'а.

    `default` хранится как Python-значение и сериализуется в JSON как есть.
    `min`/`max` применимы только к int/float; `enum` — только к 'enum'.
    """
    name: str  # ключ в params dict
    type: Literal["int", "float", "bool", "string", "enum"]
    label: str  # человеко-читаемая метка над полем в UI
    description: str  # подсказка под полем (одно предложение, опционально)
    default: Any
    required: bool  # если True — пустое значение отвергается валидатором
    enum: list[str]  # доступные значения для type='enum'
    min: float  # включительно, для int/float
    max: float  # включительно, для int/float


# ── Реестр job'ов: для UI (display_name, description, params_schema) и роутера
# (trigger_handler). job_id строго совпадает с PK в `scheduler_configs` и id в
# APScheduler. `params_schema` опционально — без неё UI откатывается на JSON-textarea
# (бекворд-совместимость), но новые job'ы должны её декларировать.
JOB_METADATA: dict[str, dict[str, Any]] = {
    "bgg_top_sync": {
        "display_name": "BGG Top Sync (weekly)",
        "description": (
            "Еженедельное полное обогащение топ-N игр (rank ≤ N) через "
            "/thing batch. Параметры: rank_le (default 1000), skip_recent_days "
            "(default 7). Дефолтное расписание: пн 03:00 UTC."
        ),
        "params_schema": [
            {
                "name": "rank_le",
                "type": "int",
                "label": "Rank ≤",
                "description": "Обогащать игры с BGG rank ниже или равным этому числу.",
                "default": 1000,
                "required": False,
                "min": 1,
                "max": 30000,
            },
            {
                "name": "skip_recent_days",
                "type": "int",
                "label": "Skip если обновлено за (дней)",
                "description": "Пропускать игры, у которых game_bgg.fetched_at новее, чем N дней назад.",
                "default": 7,
                "required": False,
                "min": 0,
                "max": 365,
            },
        ],
    },
    "bgg_hotness_sync": {
        "display_name": "BGG Hotness (daily)",
        "description": (
            "Ежедневный snapshot 50 «горячих» игр + auto-import bgg_id'ов "
            "отсутствующих в каталоге. Дефолт: 06:00 UTC."
        ),
        # Hotness не принимает params (запускается без аргументов) — пустая схема
        # сигнализирует UI «параметров нет, форма пустая, только cron+enabled».
        "params_schema": [],
    },
    "bgg_mini_batch": {
        "display_name": "BGG Daily Mini-batch",
        "description": (
            "Ежедневный catch-up: 500-1000 игр из хвоста rank-таблицы со "
            "skip_recent_days > 30. Цикл обновления ~60 дней при 30K играх. "
            "Мягкий rate-limit (2с). Дефолт: 04:00 UTC."
        ),
        "params_schema": [
            {
                "name": "batch_size",
                "type": "int",
                "label": "Batch size",
                "description": "Сколько игр пытаемся обогатить за один прогон.",
                "default": 500,
                "required": False,
                "min": 10,
                "max": 5000,
            },
            {
                "name": "skip_recent_days",
                "type": "int",
                "label": "Skip если обновлено за (дней)",
                "description": "Пропускать игры с свежим fetched_at.",
                "default": 30,
                "required": False,
                "min": 0,
                "max": 365,
            },
            {
                "name": "rate_limit_sec",
                "type": "float",
                "label": "Rate limit (сек)",
                "description": "Пауза между батчами /thing.",
                "default": 2.0,
                "required": False,
                "min": 0.5,
                "max": 10.0,
            },
        ],
    },
    "ml_health_check": {
        "display_name": "ML Health Check (every 30s)",
        "description": (
            "Polling Ollama /api/tags для проверки доступности bge-m3 и "
            "qwen2.5:7b-instruct. Синглтон OllamaHealth кэширует статус; "
            "tier'ы T2/T3 проверяют его без HTTP. Interval-trigger (не cron)."
        ),
        "params_schema": [
            {
                "name": "interval_sec",
                "type": "int",
                "label": "Interval (сек)",
                "description": "Период опроса Ollama /api/tags.",
                "default": 30,
                "required": True,
                "min": 5,
                "max": 600,
            },
        ],
    },
    "match_worker": {
        "display_name": "Match Queue Worker (every 10s)",
        "description": (
            "Обработка match_queue: T2 (bge-m3 cosine) + T3 (qwen LLM-арбитр). "
            "Берёт batch=32 через FOR UPDATE SKIP LOCKED, embed/LLM, "
            "финализирует offer. Interval-trigger (не cron)."
        ),
        "params_schema": [
            {
                "name": "interval_sec",
                "type": "int",
                "label": "Interval (сек)",
                "description": "Период тика worker'а.",
                "default": 10,
                "required": True,
                "min": 5,
                "max": 300,
            },
        ],
    },
    "match_log_retention": {
        "display_name": "Match Log Retention (daily)",
        "description": (
            "Ежедневная чистка match_log: удаляет записи старше "
            "Settings.match_log_retention_days (default 90), сохраняя "
            "не-реверченные auto-match'и (потенциально нужны для отката). "
            "Параметр `retention_days` в scheduler_configs.params "
            "переопределяет default."
        ),
        "params_schema": [
            {
                "name": "retention_days",
                "type": "int",
                "label": "Retention (дней)",
                "description": "Override Settings.match_log_retention_days.",
                "default": 90,
                "required": False,
                "min": 7,
                "max": 730,
            },
        ],
    },
    "auto_recovery_runner": {
        "display_name": "Auto Recovery Runner (every 60s)",
        "description": (
            "CAT-4.5: читает enabled правила из `auto_recovery_rules` и "
            "применяет действия при выполнении condition. Поддерживает "
            "condition.type ∈ {circuit_state, breaker_state, "
            "job_completed} и action.type ∈ {re_enqueue_skipped, "
            "trigger_job}. Дедуп через last_triggered_at + "
            "dedup_minutes (default 5). Interval-trigger."
        ),
        "params_schema": [
            {
                "name": "interval_sec",
                "type": "int",
                "label": "Interval (сек)",
                "description": "Период тика runner'а.",
                "default": 60,
                "required": True,
                "min": 10,
                "max": 3600,
            },
        ],
    },
}


def validate_params_against_schema(
    job_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Server-side валидация params против `params_schema` зарегистрированного job'а.

    Зачем: UI рендерит форму по schema, но клиент может прислать что угодно через
    raw PATCH-запрос — мы должны защитить себя на бэке. Возвращает coerced params
    (например, '5' → 5 для int) или поднимает ValueError со списком проблем.

    Поведение:
    - Незнакомые ключи (не в schema) — пропускаются как есть (forward compat).
    - Пропущенные required ключи — ошибка, если их не было и в существующем params.
    - Type mismatch — ошибка с понятным message.
    - Out of range / not in enum — ошибка.

    Job'ы без schema (или с None) — params не валидируется (бэк-compat).
    """
    meta = JOB_METADATA.get(job_id)
    if not meta:
        return params  # неизвестный job, пусть PATCH-роутер сам отдаст 404
    schema = meta.get("params_schema")
    if schema is None:
        return params  # opt-out от валидации

    errors: list[str] = []
    coerced: dict[str, Any] = dict(params)

    by_name = {f["name"]: f for f in schema}
    for field in schema:
        name = field["name"]
        ftype = field["type"]
        if name not in coerced:
            # required-проверка делается на момент апдейта в PATCH: если в БД
            # уже лежит этот ключ — оставляем; merge на caller-side.
            continue
        value = coerced[name]

        # Type coercion (UI присылает строки из текстовых input'ов).
        try:
            if ftype == "int":
                if isinstance(value, bool):  # bool — это подкласс int, отделим
                    raise TypeError("bool вместо int")
                value = int(value)
            elif ftype == "float":
                if isinstance(value, bool):
                    raise TypeError("bool вместо float")
                value = float(value)
            elif ftype == "bool":
                if isinstance(value, str):
                    value = value.lower() in ("true", "1", "yes", "on")
                value = bool(value)
            elif ftype == "string":
                value = str(value)
            elif ftype == "enum":
                value = str(value)
                if value not in (field.get("enum") or []):
                    errors.append(f"{name}: '{value}' не входит в {field.get('enum')}")
                    continue
            else:
                errors.append(f"{name}: неизвестный type '{ftype}' в schema")
                continue
        except (TypeError, ValueError) as exc:
            errors.append(f"{name}: ожидался {ftype} ({exc})")
            continue

        # Диапазоны для int/float.
        if ftype in ("int", "float"):
            if "min" in field and value < field["min"]:
                errors.append(f"{name}: {value} < min={field['min']}")
            if "max" in field and value > field["max"]:
                errors.append(f"{name}: {value} > max={field['max']}")

        coerced[name] = value

    # Игнорируем unknown ключи (не падаем, не удаляем).
    _ = by_name  # подавим unused-предупреждение, by_name держим на будущее

    if errors:
        raise ValueError("; ".join(errors))
    return coerced

# Interval-jobs (не cron) — не пишутся в scheduler_configs cron_expr,
# а используют specialized resolver. Заводим сюда: ml_health_check,
# match_worker, auto_recovery_runner.
_INTERVAL_JOBS = {"ml_health_check", "match_worker", "auto_recovery_runner"}


# ── Унифицированный trigger ───────────────────────────────────────────────────


async def trigger_scheduled_job(
    job_id: str,
    params: dict[str, Any],
    trigger: str = "scheduled",
) -> int:
    """Запустить job через ImportJob-паттерн. Возвращает id созданного ImportJob.

    Используется и из APScheduler-cron'а (`trigger='scheduled'`), и из
    `POST /scheduler/jobs/{job_id}/trigger` (`trigger='manual'`). Это даёт
    единую историю в `import_jobs` с фильтром по `payload->>'trigger'`.

    Не блокирует caller'а: job регистрируется, `asyncio.create_task` запускает
    background-runner, возвращаем id. Caller может poll'ить `GET /import/jobs/{id}`.

    Также денормализуем `last_run_*` в `scheduler_configs` для health-блока UI.
    """
    from catalog.db import get_engine
    from catalog.models import ImportJob, SchedulerConfig

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    # Подготавливаем background-функцию по job_id.
    background_fn, import_job_type = _resolve_handler(job_id, params)

    async with SessionFactory() as session:
        # Race-protection: если такой type уже pending/running, не запускаем
        # параллельный. Защита от double-trigger (manual + cron в одну секунду)
        # и от 25-минутного `bgg_top_sync` который может перекрыться следующим
        # cron'ом если зависнет. Не идеально (TOCTOU), но устраняет 99% случаев —
        # для 100% нужен advisory lock или unique partial index по status.
        existing = (
            await session.execute(
                select(ImportJob.id)
                .where(ImportJob.type == import_job_type)
                .where(ImportJob.status.in_(("pending", "running")))
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise JobAlreadyRunning(
                f"job '{job_id}' (type={import_job_type}) уже выполняется "
                f"(import_job_id={existing})"
            )

        job_payload = {**params, "trigger": trigger}
        job = ImportJob(type=import_job_type, payload=job_payload, status="pending")
        session.add(job)
        await session.commit()
        await session.refresh(job)

        # Денормализованные last_run_* в scheduler_configs.
        await session.execute(
            update(SchedulerConfig)
            .where(SchedulerConfig.job_id == job_id)
            .values(
                last_run_job_id=job.id,
                last_run_status="pending",
                last_run_at=_utcnow(),
            )
        )
        await session.commit()

        # Fire-and-forget. background_fn внутри обновит job.status и last_run_status
        # (через тот же scheduler_configs UPDATE на финише).
        asyncio.create_task(
            _run_with_status_update(job_id, job.id, background_fn),
            name=f"sched-{job_id}-{job.id}",
        )

    return job.id


def _resolve_handler(job_id: str, params: dict[str, Any]):
    """Возвращает (background_async_fn, import_job_type) по job_id.

    Обернуто в lazy-import чтобы не тащить routers/importers на module-load.
    """
    if job_id == "bgg_top_sync":
        from catalog.routers.imports import _run_bgg_batch_job
        from catalog.schemas import BggBatchImportRequest

        rank_le = params.get("rank_le", 1000)
        skip = params.get("skip_recent_days", 7)
        req = BggBatchImportRequest(
            rank_le=rank_le,
            batch_size=20,
            skip_recent_days=skip,
            limit=None,
            dry_run=False,
            rate_limit_sec=1.0,
        )
        return (lambda jid: _run_bgg_batch_job(jid, req)), "bgg-batch"

    if job_id == "bgg_hotness_sync":
        from catalog.importers.bgg_hotness import run_hotness_import_job

        return run_hotness_import_job, "bgg-hotness"

    if job_id == "match_log_retention":
        # Retention: один SQL DELETE через auditor.evict_older_than.
        # Параметр `retention_days` из scheduler_configs.params
        # переопределяет Settings.match_log_retention_days — это даёт
        # оператору ручку «прогнать с меньшим окном» без рестарта.
        retention_days = params.get("retention_days")
        return (
            lambda jid: _run_match_log_retention(jid, retention_days),
            "match-log-retention",
        )

    if job_id == "bgg_mini_batch":
        from catalog.routers.imports import _run_bgg_batch_job
        from catalog.schemas import BggBatchImportRequest

        batch_size = params.get("batch_size", 500)
        skip = params.get("skip_recent_days", 30)
        rl = params.get("rate_limit_sec", 2.0)
        req = BggBatchImportRequest(
            all_ranked=True,
            batch_size=20,
            skip_recent_days=skip,
            limit=batch_size,
            dry_run=False,
            rate_limit_sec=rl,
        )
        return (lambda jid: _run_bgg_batch_job(jid, req)), "bgg-mini-batch"

    # Interval-jobs (ml_health_check, match_worker) — поддерживаются через
    # trigger_scheduled_job для UI «Запустить сейчас». Wrapper'у нужна
    # сигнатура `(import_job_id) -> awaitable` — оборачиваем простой runner
    # без аргументов в lambda. ImportJob создаётся как обычно (для consistency
    # UI: `/import/jobs?type=interval-<job_id>`), но runner его не использует —
    # interval-tick короткий и пишет own state через `match_queue` / `OllamaHealth`.
    if job_id in _INTERVAL_JOBS:
        runner = _interval_runner(job_id)  # raises ValueError если неизвестен
        return (lambda _jid: runner()), f"interval-{job_id}"

    raise ValueError(f"Unknown scheduler job_id: {job_id}")


# ── Interval-job runners (не используют trigger_scheduled_job + ImportJob) ───
# Эти job'ы — короткие, не нужны polling/log_lines/progress. APScheduler
# вызывает их напрямую без обёртки в _make_cron_job.


async def _run_match_log_retention(import_job_id: int, retention_days: int | None) -> None:
    """Runner для job 'match_log_retention'. Дёргает auditor.evict_older_than,
    обновляет ImportJob с count удалённых.

    Если `retention_days` не задан в params — берётся из Settings.
    """
    from catalog.config import get_settings
    from catalog.db import get_engine
    from catalog.matching.v2.auditor import evict_older_than
    from catalog.models import ImportJob

    days = retention_days if retention_days is not None else get_settings().match_log_retention_days

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    deleted = 0
    error_msg: str | None = None
    try:
        async with SessionFactory() as session:
            deleted = await evict_older_than(session, days=days)
            await session.commit()
    except Exception as exc:
        logger.exception("match_log_retention: failed")
        error_msg = f"{type(exc).__name__}: {exc}"

    # Завершаем ImportJob со статусом и кратким отчётом — UI sched-history
    # показывает их в `/import/jobs?type=match-log-retention`.
    async with SessionFactory() as session:
        job = await session.get(ImportJob, import_job_id)
        if job is not None:
            job.status = "failed" if error_msg else "done"
            payload = dict(job.payload or {})
            payload.update({
                "retention_days": days,
                "deleted": deleted,
                "error": error_msg,
            })
            job.payload = payload
            await session.commit()


async def _ml_health_check_runner() -> None:
    """Periodic poll Ollama health — обновляет OllamaHealth singleton."""
    from catalog.matching.v2.worker import ml_health_check_job

    try:
        await ml_health_check_job()
    except Exception:
        logger.exception("ml_health_check_runner failed")


async def _match_worker_runner() -> None:
    """Один тик match_worker — берёт batch из match_queue, processes T2/T3.

    Замеряет длительность тика и пишет в `_TICK_HISTORY` (ring buffer 30).
    История идёт в `/scheduler/jobs/match_worker` для UI sparkline'а
    Worker run-history.
    """
    import time as _time
    from catalog.matching.v2.worker import match_worker_job

    started = _time.monotonic()
    error = False
    try:
        await match_worker_job()
    except Exception:
        logger.exception("match_worker_runner failed")
        error = True
    duration_ms = (_time.monotonic() - started) * 1000.0
    _push_tick("match_worker", duration_ms=duration_ms, error=error)


# Ring-buffer per-interval-job для UI run-history. Хранит до 30 последних
# тиков (~5 мин при 10s interval). Reset при рестарте сервиса — OK, это
# operational metric, не persistence.
_TICK_HISTORY: dict[str, list[dict]] = {}


def _push_tick(job_id: str, *, duration_ms: float, error: bool) -> None:
    buf = _TICK_HISTORY.setdefault(job_id, [])
    buf.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round(duration_ms, 1),
        "error": error,
    })
    # Trim — держим только 30 последних. list.pop(0) O(n) для 30 — норм.
    while len(buf) > 30:
        buf.pop(0)


def get_tick_history(job_id: str) -> list[dict]:
    """Reader для UI: возвращает копию ring-buffer тиков. Empty list если нет данных."""
    return list(_TICK_HISTORY.get(job_id, []))


async def _auto_recovery_runner() -> None:
    """CAT-4.5: тик auto_recovery — читает rules, применяет action'ы."""
    import time as _time
    from catalog.db import get_engine
    from catalog.matching.v2.auto_recovery import run_once

    SessionFactory = async_sessionmaker(get_engine(), expire_on_commit=False)
    started = _time.monotonic()
    error = False
    try:
        await run_once(SessionFactory)
    except Exception:
        logger.exception("auto_recovery_runner failed")
        error = True
    duration_ms = (_time.monotonic() - started) * 1000.0
    _push_tick("auto_recovery_runner", duration_ms=duration_ms, error=error)


def _interval_runner(job_id: str):
    """Возвращает runner для interval-job'а по id."""
    if job_id == "ml_health_check":
        return _ml_health_check_runner
    if job_id == "match_worker":
        return _match_worker_runner
    if job_id == "auto_recovery_runner":
        return _auto_recovery_runner
    raise ValueError(f"Unknown interval job_id: {job_id}")


async def _run_with_status_update(job_id: str, import_job_id: int, fn) -> None:
    """Обёртка вокруг background-runner: после завершения денормализует
    last_run_status в scheduler_configs (читает финальный статус ImportJob).
    """
    from catalog.db import get_engine
    from catalog.models import ImportJob, SchedulerConfig

    try:
        await fn(import_job_id)
    except Exception:
        logger.exception("scheduler: %s (job_id=%d) raised", job_id, import_job_id)

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        job = (
            await session.execute(select(ImportJob).where(ImportJob.id == import_job_id))
        ).scalar_one_or_none()
        if job is None:
            return
        await session.execute(
            update(SchedulerConfig)
            .where(SchedulerConfig.job_id == job_id)
            .values(last_run_status=job.status)
        )
        await session.commit()


# ── Создание / hot-reload ─────────────────────────────────────────────────────


def _make_cron_job(job_id: str):
    """Возвращает async-функцию обёртку для APScheduler.add_job.

    APScheduler при срабатывании вызывает этот wrapper; внутри читаем актуальные
    params из scheduler_configs (на случай если их обновили через PATCH без
    рестарта) и зовём `trigger_scheduled_job`.
    """
    async def _runner() -> None:
        from catalog.db import get_engine
        from catalog.models import SchedulerConfig

        try:
            engine = get_engine()
            SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
            async with SessionFactory() as session:
                cfg = (
                    await session.execute(
                        select(SchedulerConfig).where(SchedulerConfig.job_id == job_id)
                    )
                ).scalar_one_or_none()
                if cfg is None or not cfg.enabled:
                    logger.warning(
                        "scheduler: %s — config отсутствует или disabled, пропуск",
                        job_id,
                    )
                    return
                params = dict(cfg.params or {})

            try:
                await trigger_scheduled_job(job_id, params, trigger="scheduled")
            except JobAlreadyRunning as exc:
                # Cron сработал, но предыдущий запуск ещё идёт. Это типично для
                # длинных задач (bgg_top_sync ~25 мин) или для concurrent
                # manual+cron в одну секунду. Не ошибка — просто пропускаем.
                logger.info("scheduler: %s — пропуск (%s)", job_id, exc)
        except Exception:
            logger.exception("scheduler: %s wrapper failed", job_id)

    return _runner


def _register_job(
    scheduler: AsyncIOScheduler,
    job_id: str,
    trigger: CronTrigger,
) -> None:
    """Регистрирует cron-job в scheduler'е с едиными для всего модуля параметрами.

    Унифицирует add_job вызовы из `create_scheduler` и `reload_job_from_db` —
    при добавлении нового параметра (например, `misfire_grace_time`) меняется
    одно место, а не два.
    """
    scheduler.add_job(
        _make_cron_job(job_id),
        trigger,
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def _register_interval_job(
    scheduler: AsyncIOScheduler,
    job_id: str,
    interval_sec: int,
) -> None:
    """Симметричный `_register_job` для interval-jobs (ml_health_check,
    match_worker). Использует прямой runner (`_interval_runner`), а не
    `_make_cron_job` — interval-jobs не идут через ImportJob-паттерн.
    """
    scheduler.add_job(
        _interval_runner(job_id),
        IntervalTrigger(seconds=interval_sec, timezone="UTC"),
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


async def create_scheduler() -> AsyncIOScheduler:
    """Создаёт и конфигурирует APScheduler на основе `scheduler_configs` в БД.

    Async — потому что читает БД (миграция 0010 сидит дефолты). Если БД ещё не
    готова или таблицы нет — создаёт пустой scheduler и логирует warning;
    lifespan позднее сделает .start().
    """
    from catalog.db import get_engine
    from catalog.models import SchedulerConfig

    scheduler = AsyncIOScheduler(timezone="UTC")

    try:
        engine = get_engine()
        SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionFactory() as session:
            configs = (
                await session.execute(select(SchedulerConfig))
            ).scalars().all()
    except Exception:
        logger.exception("scheduler: не удалось прочитать scheduler_configs — пустой scheduler")
        return scheduler

    for cfg in configs:
        if not cfg.enabled:
            logger.info("scheduler: %s — disabled, пропускаем регистрацию", cfg.job_id)
            continue

        # Interval-jobs (matching v2): особый путь — не trigger_scheduled_job,
        # а прямой runner с IntervalTrigger. cron_expr игнорируется (но
        # хранится для совместимости PATCH /scheduler/jobs/{id}).
        if cfg.job_id in _INTERVAL_JOBS:
            interval_sec = int(cfg.params.get("interval_sec", 30))
            try:
                _register_interval_job(scheduler, cfg.job_id, interval_sec)
            except ValueError:
                logger.error("scheduler: %s — unknown interval runner", cfg.job_id)
                continue
            logger.info(
                "scheduler: %s зарегистрирован (interval=%ds, params=%s)",
                cfg.job_id, interval_sec, cfg.params,
            )
            continue

        try:
            trigger = CronTrigger.from_crontab(cfg.cron_expr, timezone="UTC")
        except Exception:
            logger.error(
                "scheduler: %s — невалидный cron %r, пропускаем",
                cfg.job_id, cfg.cron_expr,
            )
            continue

        _register_job(scheduler, cfg.job_id, trigger)
        logger.info(
            "scheduler: %s зарегистрирован (%s UTC, params=%s)",
            cfg.job_id, cfg.cron_expr, cfg.params,
        )

    return scheduler


async def reload_job_from_db(scheduler: AsyncIOScheduler, job_id: str) -> None:
    """Hot-reload одного job'а после PATCH /scheduler/jobs/{id}.

    Читает актуальный `scheduler_configs` row → reschedule / pause / remove
    в running APScheduler. Безопасно для конкурентных вызовов через одну сессию
    APScheduler (он использует свой собственный SchedulerLock внутри).
    """
    from catalog.db import get_engine
    from catalog.models import SchedulerConfig

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        cfg = (
            await session.execute(
                select(SchedulerConfig).where(SchedulerConfig.job_id == job_id)
            )
        ).scalar_one_or_none()

    if cfg is None:
        # Конфиг удалён → удалить job из scheduler'а если есть.
        try:
            scheduler.remove_job(job_id)
            logger.info("scheduler: %s удалён (конфиг отсутствует)", job_id)
        except Exception:
            pass
        return

    if not cfg.enabled:
        # Disabled → pause или remove существующий.
        try:
            scheduler.remove_job(job_id)
            logger.info("scheduler: %s удалён (enabled=false)", job_id)
        except Exception:
            pass
        return

    # Interval-jobs (ml_health_check, match_worker) — отдельная ветка:
    # CronTrigger тут неприменим (PATCH меняет params.interval_sec, а не cron).
    # Без этой ветки hot-reload через PATCH /scheduler/jobs/{id} молча игнорировал
    # бы interval_sec — оставался старый scheduler.add_job из create_scheduler.
    if cfg.job_id in _INTERVAL_JOBS:
        interval_sec = int((cfg.params or {}).get("interval_sec", 30))
        try:
            _register_interval_job(scheduler, cfg.job_id, interval_sec)
        except ValueError:
            logger.error("scheduler: reload %s — unknown interval runner", cfg.job_id)
            return
        logger.info(
            "scheduler: %s reloaded (interval=%ds, params=%s)",
            cfg.job_id, interval_sec, cfg.params,
        )
        return

    try:
        trigger = CronTrigger.from_crontab(cfg.cron_expr, timezone="UTC")
    except Exception:
        logger.error(
            "scheduler: reload %s — невалидный cron %r, оставляем старое расписание",
            job_id, cfg.cron_expr,
        )
        return

    # _register_job делает add_job с replace_existing=True (работает и для update).
    _register_job(scheduler, job_id, trigger)
    logger.info(
        "scheduler: %s reloaded (%s UTC, params=%s)",
        cfg.job_id, cfg.cron_expr, cfg.params,
    )
