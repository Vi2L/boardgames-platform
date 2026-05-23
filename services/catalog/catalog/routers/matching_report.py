"""GET-only роутер отчётности по матчингу (CAT-17, страница `/matching → Отчёт`).

Endpoints:
  - `GET /matching/report/top-unmatched` — top нормализованных title с
    `match_status='unmatched'` (что чаще всего не сматчено → импортировать в catalog).
  - `GET /matching/report/coverage`      — per store: matched / unmatched / rejected
    breakdown + coverage % (где какой источник деградирует).
  - `GET /matching/report/activity`      — match_log GROUP BY day × action × performed_by
    (productivity-метрика оператора, паттерны массового reject и т.п.).
  - `GET /matching/report/sla`           — tier share % + latency T2/T3 percentiles
    (health всего pipeline).

Вынесено в отдельный роутер от `routers/matching.py` (где живут все мутации
матчинга), чтобы read-only логика отчёта была изолирована и легче добавлять
новые секции без угрозы сломать ingest/reassess.

Все endpoints — `read` scope. Никаких UPDATE/INSERT/DELETE.
"""
from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session


router = APIRouter(prefix="/matching/report", tags=["matching", "report"])


# ─── Top unmatched ─────────────────────────────────────────────────────────


class TopUnmatchedItem(BaseModel):
    title_norm: str
    count: int
    first_seen: str
    last_seen: str
    sample_title_raw: str  # один пример «сырого» title из группы
    stores: list[str]


class TopUnmatchedOut(BaseModel):
    items: list[TopUnmatchedItem]
    days: int
    min_count: int


@router.get(
    "/top-unmatched",
    response_model=TopUnmatchedOut,
    dependencies=[Depends(require_scope("read"))],
)
async def top_unmatched(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=500),
    min_count: int = Query(
        2, ge=1, le=100,
        description="минимальное число офферов с этим title для включения",
    ),
    store_slug: str | None = Query(None, description="ограничить одним магазином"),
    session: AsyncSession = Depends(get_session),
) -> TopUnmatchedOut:
    """Ранжированный список «эти title чаще всего не сматчены».

    Группировка по `title_raw_norm` (generated column в offers). Используется
    оператором для решения «какую игру импортировать в catalog из BGG, чтобы
    закрыть максимум unmatched сразу».

    `min_count >= 2` по дефолту — единичные unmatched (опечатки покупателя)
    отфильтровываются. Можно поднять до 5-10 для ультра-критичного списка.

    `sample_title_raw` — один реальный пример сырого title из группы. Помогает
    оператору быстро понять «что это за игра?» без открытия отдельного оффера.
    """
    where_clauses = [
        "match_status = 'unmatched'",
        "last_seen_at > now() - make_interval(days => :days)",
    ]
    params: dict = {"days": days, "limit": limit, "min_count": min_count}
    if store_slug:
        where_clauses.append("store_slug = :store_slug")
        params["store_slug"] = store_slug

    where_sql = " AND ".join(where_clauses)

    rows = (await session.execute(
        text(
            f"""
            SELECT
                title_raw_norm AS title_norm,
                COUNT(*) AS count,
                MIN(last_seen_at)::text AS first_seen,
                MAX(last_seen_at)::text AS last_seen,
                (ARRAY_AGG(title_raw ORDER BY last_seen_at DESC))[1] AS sample_title_raw,
                ARRAY_AGG(DISTINCT store_slug) AS stores
            FROM offers
            WHERE {where_sql}
            GROUP BY title_raw_norm
            HAVING COUNT(*) >= :min_count
            ORDER BY COUNT(*) DESC, MAX(last_seen_at) DESC
            LIMIT :limit
            """
        ).bindparams(**params)
    )).mappings().all()

    return TopUnmatchedOut(
        items=[TopUnmatchedItem.model_validate(dict(r)) for r in rows],
        days=days,
        min_count=min_count,
    )


# ─── Coverage by store ─────────────────────────────────────────────────────


class CoverageStoreItem(BaseModel):
    store_slug: str
    total: int
    matched_auto: int
    matched_manual: int
    pending_ml: int
    unmatched: int
    rejected: int
    coverage_pct: float  # (auto + manual) / total * 100, округлено до 0.01


class CoverageOut(BaseModel):
    stores: list[CoverageStoreItem]
    days: int


@router.get(
    "/coverage",
    response_model=CoverageOut,
    dependencies=[Depends(require_scope("read"))],
)
async def coverage_by_store(
    days: int = Query(7, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
) -> CoverageOut:
    """Per-store breakdown по статусам матчинга + % matched.

    Помогает оператору быстро увидеть, какой магазин деградирует:
      - low coverage_pct + high unmatched → парсер начал слать новые форматы
        title (например, после редизайна WB)
      - high pending_ml → Ollama не справляется (см. /matching → Контроль)
      - high rejected → много не-настолок проходит через категорийный
        whitelist (надо проверить `_ALLOWED_CATEGORIES` или парсер).
    """
    rows = (await session.execute(
        text(
            """
            SELECT
                store_slug,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE match_status = 'auto')        AS matched_auto,
                COUNT(*) FILTER (WHERE match_status = 'manual')      AS matched_manual,
                COUNT(*) FILTER (WHERE match_status = 'pending_ml')  AS pending_ml,
                COUNT(*) FILTER (WHERE match_status = 'unmatched')   AS unmatched,
                COUNT(*) FILTER (WHERE match_status = 'rejected')    AS rejected,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE match_status IN ('auto','manual'))
                    / NULLIF(COUNT(*), 0),
                    2
                )::float AS coverage_pct
            FROM offers
            WHERE last_seen_at > now() - make_interval(days => :days)
            GROUP BY store_slug
            ORDER BY total DESC
            """
        ).bindparams(days=days)
    )).mappings().all()

    return CoverageOut(
        stores=[CoverageStoreItem.model_validate(dict(r)) for r in rows],
        days=days,
    )


# ─── Activity timeline ─────────────────────────────────────────────────────


class ActivityRow(BaseModel):
    day: str  # ISO date
    action: str
    performed_by: str
    count: int


class ActivityOut(BaseModel):
    rows: list[ActivityRow]
    days: int


@router.get(
    "/activity",
    response_model=ActivityOut,
    dependencies=[Depends(require_scope("read"))],
)
async def activity_timeline(
    days: int = Query(14, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
) -> ActivityOut:
    """Productivity-таймлайн оператора: сколько link/reject/revert/reassess в день.

    Прогресс-action'ы (`t0_progress`/`t1_progress`/...) фильтруются — это
    промежуточная диагностика, не операторская активность. Сортировка по
    дате DESC (свежие сверху для UI с timeline-чартом).

    Полезно для:
      - выявления массовых reject (паттерн «не-настолки» от какого-то парсера)
      - оценки нагрузки оператора (если N reject/день > N auto/день — пайплайн
        требует доработки)
      - аудита (кто что делал по дням, performed_by — owner API-ключа или
        X-User header)
    """
    rows = (await session.execute(
        text(
            """
            SELECT
                date_trunc('day', performed_at AT TIME ZONE 'UTC')::date::text AS day,
                action,
                COALESCE(performed_by, 'system') AS performed_by,
                COUNT(*) AS count
            FROM match_log
            WHERE performed_at > now() - make_interval(days => :days)
              AND action NOT IN ('t0_progress', 't1_progress', 't2_progress', 't3_progress')
            GROUP BY 1, 2, 3
            ORDER BY 1 DESC, 2
            """
        ).bindparams(days=days)
    )).mappings().all()

    return ActivityOut(
        rows=[ActivityRow.model_validate(dict(r)) for r in rows],
        days=days,
    )


# ─── SLA per tier ──────────────────────────────────────────────────────────


class TierShare(BaseModel):
    """Share & count для одного tier (или статуса unmatched/rejected)."""
    count: int
    share_pct: float


class TierLatency(BaseModel):
    """Percentiles задержки в миллисекундах для async tier'ов."""
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None


class SlaOut(BaseModel):
    days: int
    # Tier share: ключи 't0', 't1', 't2', 't3', 'manual', 'unmatched', 'rejected', 'pending'.
    tier_share: dict[str, TierShare]
    # Latency для T2/T3 — только async tier'ы, у sync (T0/T1) latency пренебрежимо мала.
    latency: dict[str, TierLatency]


@router.get(
    "/sla",
    response_model=SlaOut,
    dependencies=[Depends(require_scope("read"))],
)
async def sla_per_tier(
    days: int = Query(7, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
) -> SlaOut:
    """Health всего pipeline: distribution по tier'ам + latency T2/T3.

    Tier share вычисляется по `offers.match_tier` за период:
      - tier=0 (cache hit), 1 (trgm), 2 (vec), 3 (LLM) — это `auto`-офферы.
      - manual — оператор связал руками (NULL tier).
      - unmatched / rejected / pending_ml — особые статусы.

    Latency T2/T3 — `processed_at - created_at` в `match_queue` для
    `status='done'`. PostgreSQL `percentile_disc()` точнее чем _cont для
    дискретных задержек.
    """
    # Tier share
    tier_rows = (await session.execute(
        text(
            """
            SELECT
                match_status,
                match_tier,
                COUNT(*) AS count
            FROM offers
            WHERE last_seen_at > now() - make_interval(days => :days)
            GROUP BY 1, 2
            """
        ).bindparams(days=days)
    )).mappings().all()

    counts: dict[str, int] = {
        "t0": 0, "t1": 0, "t2": 0, "t3": 0,
        "manual": 0, "unmatched": 0, "rejected": 0, "pending": 0,
    }
    for r in tier_rows:
        status = r["match_status"]
        tier = r["match_tier"]
        n = int(r["count"])
        if status == "auto" and tier is not None and 0 <= tier <= 3:
            counts[f"t{tier}"] += n
        elif status == "manual":
            counts["manual"] += n
        elif status == "unmatched":
            counts["unmatched"] += n
        elif status == "rejected":
            counts["rejected"] += n
        elif status == "pending_ml":
            counts["pending"] += n
        # auto с NULL tier (легаси-данные до миграции 0011) — игнорируем.

    total = sum(counts.values()) or 1  # защита от деления на 0
    tier_share = {
        key: TierShare(count=n, share_pct=round(100 * n / total, 2))
        for key, n in counts.items()
    }

    # Latency T2/T3 — только processed_at - created_at для done.
    # percentile_disc возвращает interval; конвертируем в миллисекунды.
    latency_rows = (await session.execute(
        text(
            """
            SELECT
                result_tier,
                COUNT(*) AS n,
                EXTRACT(EPOCH FROM
                  percentile_disc(0.5) WITHIN GROUP (ORDER BY processed_at - created_at)
                ) * 1000 AS p50_ms,
                EXTRACT(EPOCH FROM
                  percentile_disc(0.95) WITHIN GROUP (ORDER BY processed_at - created_at)
                ) * 1000 AS p95_ms,
                EXTRACT(EPOCH FROM
                  percentile_disc(0.99) WITHIN GROUP (ORDER BY processed_at - created_at)
                ) * 1000 AS p99_ms
            FROM match_queue
            WHERE status = 'done'
              AND processed_at IS NOT NULL
              AND created_at > now() - make_interval(days => :days)
              AND result_tier IN (2, 3)
            GROUP BY result_tier
            """
        ).bindparams(days=days)
    )).mappings().all()

    latency: dict[str, TierLatency] = {
        "t2": TierLatency(p50_ms=None, p95_ms=None, p99_ms=None),
        "t3": TierLatency(p50_ms=None, p95_ms=None, p99_ms=None),
    }
    for r in latency_rows:
        key = f"t{r['result_tier']}"
        latency[key] = TierLatency(
            p50_ms=float(r["p50_ms"]) if r["p50_ms"] is not None else None,
            p95_ms=float(r["p95_ms"]) if r["p95_ms"] is not None else None,
            p99_ms=float(r["p99_ms"]) if r["p99_ms"] is not None else None,
        )

    return SlaOut(days=days, tier_share=tier_share, latency=latency)
