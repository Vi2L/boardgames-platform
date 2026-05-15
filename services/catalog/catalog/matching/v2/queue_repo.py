"""CRUD для match_queue — outbox для async tier'ов T2/T3.

API:
  - enqueue(): пушим оффер в очередь (используется ingest при miss T0+T1).
  - claim_batch(): worker берёт batch через FOR UPDATE SKIP LOCKED.
  - finalize_*(): worker фиксирует результат (success/skipped/failed/retry).
  - count_*(): для UI ML status badge.

Идемпотентность: UNIQUE(offer_id) → ON CONFLICT DO UPDATE сбрасывает
status='pending' и attempts=0 — повторный enqueue после ручного reject
(который удалил из очереди) перезапускает.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from catalog.models import MatchQueue


# Backoff в секундах per attempt: 30s → 2min → 10min → 30min.
# После исчерпания BACKOFF — статус 'failed', но всё ещё в БД (можно вернуть
# вручную через UI).
_BACKOFF_SECONDS = [30, 120, 600, 1800]


async def enqueue(
    session: AsyncSession,
    *,
    offer_id: int,
    store_slug: str,
    title_raw: str,
    title_norm: str,
    priority: int = 0,
) -> int | None:
    """Пушим оффер в match_queue. Возвращает id записи или None если
    оффер уже в очереди (status='pending'/'processing').

    `priority` > 0 — для manual reassess (оператор хочет приоритетную обработку).
    Default priority=0 для авто-ingest.
    """
    stmt = (
        pg_insert(MatchQueue.__table__)
        .values(
            offer_id=offer_id,
            store_slug=store_slug,
            title_raw=title_raw,
            title_norm=title_norm,
            priority=priority,
            status="pending",
        )
        .on_conflict_do_update(
            constraint="uq_match_queue_offer",
            set_={
                # Если оффер уже в очереди — сбрасываем в pending (ingest
                # повторно обновил title_raw, нужно перематчить).
                "status": "pending",
                "title_raw": title_raw,
                "title_norm": title_norm,
                "attempts": 0,
                "next_attempt_at": None,
                "error_detail": None,
            },
        )
        .returning(MatchQueue.__table__.c.id)
    )
    row = (await session.execute(stmt)).first()
    return int(row[0]) if row else None


async def claim_batch(
    session: AsyncSession,
    batch_size: int,
) -> list[MatchQueue]:
    """Берём batch pending-записей, помечаем status='processing'. Атомарно.

    SELECT FOR UPDATE SKIP LOCKED — стандартный PG-паттерн для конкурентного
    воркера. Хотя у нас один воркер (max_instances=1 в APScheduler), SKIP
    LOCKED — insurance от race с long-running транзакциями.

    `next_attempt_at IS NULL OR <= now()` — учитываем backoff retry.

    Возвращает list[MatchQueue] (детачнутые) — caller обрабатывает каждый
    в своей session/transaction. Все нужные поля возвращаем сразу через
    RETURNING — без второго SELECT (защита от stale read при concurrent
    reject через UI).
    """
    # SET claimed_at=now() — это поле читает `recover_stuck` при старте
    # сервиса, чтобы отличить «давно лежит в pending» (старый created_at)
    # от «только что заклеймлено воркером» (свежий claimed_at). Без этой
    # денормализации recover мог ошибочно возвращать запись в pending.
    rows = (await session.execute(
        text(
            """
            UPDATE match_queue
            SET status = 'processing',
                claimed_at = now()
            WHERE id IN (
                SELECT id FROM match_queue
                WHERE status = 'pending'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                ORDER BY priority DESC, created_at ASC
                LIMIT :n
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, offer_id, store_slug, title_raw, title_norm,
                      priority, attempts
            """
        ).bindparams(n=batch_size)
    )).mappings().all()

    if not rows:
        return []

    # Конструируем объекты вручную из RETURNING (не трогаем БД повторно).
    # Это не ORM-инстансы (без identity map), а простые value objects —
    # caller их потом не сохраняет, только читает.
    return [
        MatchQueue(
            id=int(r["id"]),
            offer_id=int(r["offer_id"]),
            store_slug=r["store_slug"],
            title_raw=r["title_raw"],
            title_norm=r["title_norm"],
            status="processing",
            priority=int(r["priority"]),
            attempts=int(r["attempts"]),
        )
        for r in rows
    ]


async def finalize_success(
    session: AsyncSession,
    queue_id: int,
    *,
    game_id: int,
    score: float,
    tier: int,
) -> None:
    """Помечаем запись 'done' с результатом."""
    await session.execute(
        update(MatchQueue)
        .where(MatchQueue.id == queue_id)
        .values(
            status="done",
            result_game_id=game_id,
            result_score=score,
            result_tier=tier,
            processed_at=datetime.now(timezone.utc),
        )
    )


async def finalize_skipped(
    session: AsyncSession,
    queue_id: int,
    *,
    reason: str,
    score: float | None = None,
) -> None:
    """Воркер дошёл до T4: ML не дал уверенности, оффер отдан в manual."""
    await session.execute(
        update(MatchQueue)
        .where(MatchQueue.id == queue_id)
        .values(
            status="skipped",
            error_detail=reason,
            result_score=score,
            processed_at=datetime.now(timezone.utc),
        )
    )


async def reschedule_retry(
    session: AsyncSession,
    queue_id: int,
    *,
    error: str,
    max_attempts: int,
) -> str:
    """Возврат в pending с exponential backoff. Возвращает новый status:
    'pending' (будет retry) или 'failed' (исчерпан max_attempts)."""
    row = (await session.execute(
        select(MatchQueue.attempts).where(MatchQueue.id == queue_id)
    )).first()
    if row is None:
        return "missing"

    new_attempts = int(row[0]) + 1
    if new_attempts >= max_attempts:
        await session.execute(
            update(MatchQueue)
            .where(MatchQueue.id == queue_id)
            .values(
                status="failed",
                attempts=new_attempts,
                error_detail=error,
                processed_at=datetime.now(timezone.utc),
            )
        )
        return "failed"

    backoff_sec = _BACKOFF_SECONDS[min(new_attempts - 1, len(_BACKOFF_SECONDS) - 1)]
    next_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_sec)
    await session.execute(
        update(MatchQueue)
        .where(MatchQueue.id == queue_id)
        .values(
            status="pending",
            attempts=new_attempts,
            next_attempt_at=next_at,
            error_detail=error,
        )
    )
    return "pending"


async def recover_stuck(session: AsyncSession, *, stale_minutes: int = 5) -> int:
    """Recovery при старте: возвращает зависшие 'processing' записи в 'pending'.

    Сценарий: воркер упал в середине batch'а — записи остались в 'processing'
    навсегда. Вызывается в lifespan на старте сервиса.

    Условие — `claimed_at < now() - N min` (момент когда воркер забрал
    запись через `claim_batch`), НЕ `created_at`. Раньше использовался
    created_at, из-за чего запись, давно лежавшая в pending и только что
    переведённая в processing, ошибочно возвращалась в pending при горячем
    рестарте → могла обработаться повторно после рестарта.

    Через 5 минут любой батч точно завершён (max batch_size=32 × ~3 сек = 96 сек).

    `claimed_at IS NULL` пропускается — это «легаси»-строки из времён до
    миграции 0013 (`claimed_at` колонки не было). Их безопаснее оставить
    оператору на разбор, чем перепрогонять без точного timestamp claim'а.
    """
    # SET claimed_at = NULL вместе с возвратом в pending. Иначе при повторном
    # старте сервиса recover_stuck снова бы «нашёл» те же строки (status уже
    # pending, UPDATE не сработает, но всё равно семантический мусор) и
    # дебаггер не понял бы при просмотре строки — её клеймнул воркер или это
    # старый recover.
    result = await session.execute(
        text(
            """
            UPDATE match_queue
            SET status = 'pending', claimed_at = NULL
            WHERE status = 'processing'
              AND claimed_at IS NOT NULL
              AND claimed_at < now() - (:stale || ' minutes')::interval
            """
        ).bindparams(stale=stale_minutes)
    )
    return result.rowcount or 0


async def count_pending(session: AsyncSession) -> int:
    """SELECT COUNT(*) WHERE status='pending'. Для UI ML status."""
    row = (await session.execute(
        text("SELECT COUNT(*) FROM match_queue WHERE status = 'pending'")
    )).scalar_one()
    return int(row)


async def count_by_status(session: AsyncSession) -> dict[str, int]:
    """Аггрегаты для UI: {pending, processing, done, failed, skipped}."""
    rows = (await session.execute(
        text("SELECT status, COUNT(*) AS n FROM match_queue GROUP BY status")
    )).mappings().all()
    return {r["status"]: int(r["n"]) for r in rows}
