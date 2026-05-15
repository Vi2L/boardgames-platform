"""APScheduler-job: обрабатывает match_queue (T2 + T3).

Каждые N секунд (Settings.match_worker_interval_sec):
  1. Если `is_ml_enabled() == False` (runtime_flags) — skip cycle.
  2. Если Ollama down — skip cycle (не открываем БД-транзакцию).
  3. claim_batch(N) с FOR UPDATE SKIP LOCKED — атомарно берём batch,
     проставляем claimed_at=now() (используется recover_stuck).
  4. Per offer:
       a. tier_2_vector — embed + cosine search.
       b. Если matched (score ≥ 0.85, single confident) → finalize_success.
       c. Если ambiguous (≥2 кандидата ≥ 0.70) → tier_3_llm.
       d. Если LLM matched (confidence ≥ 0.75) → finalize_success.
       e. Если 1 кандидат < auto_threshold (`vec_below_threshold`) → finalize_skipped
          напрямую, без T3 (один слабый кандидат не стоит вызова LLM).
       f. Иначе — finalize_skipped (manual queue T4).
  5. UPDATE offers + INSERT match_log в той же транзакции.

При OllamaError — откатываем batch обратно в pending (с attempts+1, backoff).
При других exceptions — логируем и помечаем 'failed' (operator вмешается).

Идемпотентность: claim_batch использует FOR UPDATE SKIP LOCKED, race conditions
не страшны. Если случилась паника между claim и finalize — recover_stuck()
вернёт записи в pending при следующем старте (по `claimed_at`, не `created_at`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from catalog.config import get_settings
from catalog.db import get_engine
from catalog.matching.v2.auditor import log_change
from catalog.matching.v2.decisions import save_decision
from catalog.matching.v2.domain import MatchAction, MatchContext
from catalog.matching.v2.embedder import OllamaError, OllamaUnavailable
from catalog.matching.v2.embeddings import tier_2_vector
from catalog.matching.v2.engine import MatchEngine
from catalog.matching.v2.health import OllamaHealth
from catalog.matching.v2.llm_arbiter import tier_3_llm
from catalog.matching.v2.queue_repo import (
    claim_batch,
    finalize_skipped,
    finalize_success,
    reschedule_retry,
)
from catalog.runtime_flags import is_ml_enabled
from catalog.models import Offer

logger = logging.getLogger(__name__)


async def match_worker_job() -> None:
    """Обрабатывает один batch очереди. APScheduler вызывает это периодически.

    max_instances=1 + coalesce=True в scheduler гарантирует, что параллельная
    копия не запустится — если предыдущий тик длился дольше interval'а,
    APScheduler пропустит следующий запуск.
    """
    settings = get_settings()
    health = OllamaHealth.get_instance()

    # Quick exit без открытия БД-транзакции.
    # `is_ml_enabled` читает runtime_flags с TTL 5 сек — оператор может
    # выключить ML без рестарта сервиса (PATCH /admin/runtime-flags/ml_enabled).
    if not await is_ml_enabled():
        return
    if not health.is_available_for(settings.ml_embed_model):
        logger.debug("match_worker: bge-m3 down, skip cycle")
        return

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as session:
        queue_items = await claim_batch(session, settings.match_worker_batch_size)
        await session.commit()

    if not queue_items:
        return

    logger.info("match_worker: claimed %d items", len(queue_items))

    # Каждый offer обрабатываем в собственной транзакции — если один упал,
    # остальные не должны откатываться.
    for q in queue_items:
        await _process_one(q, settings, SessionFactory)


async def _process_one(q, settings, SessionFactory) -> None:
    """Обработка одного match_queue-item'а: T2 → optional T3 → finalize."""
    ctx = MatchContext(
        title_raw=q.title_raw,
        title_norm=q.title_norm,
        store_slug=q.store_slug,
        offer_id=q.offer_id,
    )

    async with SessionFactory() as session:
        try:
            t2 = await tier_2_vector(
                session, ctx,
                top_k=settings.match_t2_top_k,
                auto_threshold=settings.match_t2_auto_threshold,
                min_score=settings.match_t3_min_score,
            )
        except OllamaUnavailable as e:
            await _retry(q, str(e), settings, SessionFactory)
            return
        except OllamaError as e:
            await _retry(q, f"ollama_error: {e}", settings, SessionFactory)
            return
        except Exception:  # noqa: BLE001
            logger.exception("match_worker: T2 failed for queue_id=%d", q.id)
            await _retry(q, "unexpected_t2_error", settings, SessionFactory)
            return

        if t2 is None or t2.reason == "vec_no_candidates":
            # Ничего похожего → manual queue T4.
            await finalize_skipped(session, q.id, reason="no_candidates")
            await _update_offer_unmatched(session, q.offer_id, "vec_no_candidates", tier=2)
            await session.commit()
            return

        result = t2

        # Если T2 ambiguous (≥2 кандидата score ≥ min_score) — нужен T3 LLM
        # арбитр для выбора одного из них.
        # `vec_below_threshold` (1 кандидат < auto_threshold) — НЕ запускаем T3:
        # один слабый кандидат не стоит вызова LLM, отдаём оператору в T4.
        is_ambiguous = (
            not t2.matched
            and t2.reason == "vec_ambiguous"
            and t2.candidates
            and len(t2.candidates) >= 2
        )
        if is_ambiguous:
            health = OllamaHealth.get_instance()
            if health.is_available_for(settings.ml_llm_model):
                try:
                    t3 = await tier_3_llm(
                        ctx, t2.candidates,
                        confidence_threshold=settings.match_t3_confidence_threshold,
                    )
                    result = t3
                except OllamaUnavailable as e:
                    # T3 down — отдадим оператору с T2-кандидатом
                    await finalize_skipped(session, q.id, reason=f"llm_unavailable: {e}",
                                           score=t2.score)
                    await _update_offer_unmatched(
                        session, q.offer_id, "llm_unavailable", tier=2,
                        score=t2.score,
                    )
                    await session.commit()
                    return
            else:
                # LLM circuit breaker open — оффер в manual с лучшим T2 кандидатом.
                # Используем то же значение reason что и для `OllamaUnavailable` /
                # `_update_offer_unmatched` — иначе оператор видит "llm_disabled"
                # в queue.error_detail и "llm_unavailable" в offers.match_reason для
                # одного и того же события, что затрудняет диагностику.
                await finalize_skipped(session, q.id, reason="llm_unavailable", score=t2.score)
                await _update_offer_unmatched(
                    session, q.offer_id, "llm_unavailable", tier=2, score=t2.score,
                )
                await session.commit()
                return

        # Финализация
        if result.matched:
            await _finalize_match(session, q, result, settings)
        else:
            # T3 dunno или low confidence
            await finalize_skipped(
                session, q.id,
                reason=result.reason or "ml_no_match",
                score=result.score,
            )
            await _update_offer_unmatched(
                session, q.offer_id, result.reason or "ml_no_match",
                tier=result.tier, score=result.score,
                predicted_kind=result.predicted_kind,
            )
        await session.commit()


async def _finalize_match(session, q, result, settings) -> None:
    """Записываем успешный auto-match: UPDATE offers + match_log + decisions."""
    # Прочитаем текущее состояние оффера для аудита prev_*
    offer = await session.get(Offer, q.offer_id)
    if offer is None:
        await finalize_skipped(session, q.id, reason="offer_disappeared")
        return

    prev_game_id = offer.game_id
    prev_status = offer.match_status

    # Защита от race: если оператор успел сделать manual link — не перетираем
    if prev_status in ("manual", "rejected"):
        await finalize_skipped(session, q.id, reason=f"raced_{prev_status}")
        return

    offer.game_id = result.game_id
    offer.match_status = "auto"
    offer.match_score = result.score
    offer.match_tier = result.tier
    offer.match_reason = result.reason
    if result.predicted_kind:
        offer.predicted_kind = result.predicted_kind

    # match_decisions cache (TTL per source: 14 days for T2, 7 days for T3)
    source = "auto_t2" if result.tier == 2 else "auto_t3"
    await save_decision(
        session,
        title_norm=q.title_norm,
        game_id=result.game_id,
        source=source,
        tier=result.tier,
        score=result.score,
    )

    # Аудит-запись
    await log_change(
        session,
        offer_id=q.offer_id,
        action=result.action or MatchAction.AUTO_T2,
        prev_game_id=prev_game_id,
        new_game_id=result.game_id,
        prev_status=prev_status,
        new_status="auto",
        tier=result.tier,
        score=result.score,
        reason=result.reason,
        performed_by="worker",
    )

    await finalize_success(
        session, q.id,
        game_id=result.game_id,
        score=result.score or 0.0,
        tier=result.tier or 0,
    )


async def _update_offer_unmatched(
    session,
    offer_id: int,
    reason: str,
    *,
    tier: int | None = None,
    score: float | None = None,
    predicted_kind: str | None = None,
) -> None:
    """Обновить offer что воркер не сматчил — оставляем в manual queue (T4)."""
    values = {
        "match_tier": tier,
        "match_reason": reason,
        "match_score": score,
    }
    if predicted_kind:
        values["predicted_kind"] = predicted_kind
    await session.execute(
        update(Offer).where(Offer.id == offer_id).values(**values)
    )


async def _retry(q, error: str, settings, SessionFactory) -> None:
    """Backoff retry. После max_attempts → 'failed' (operator смотрит)."""
    async with SessionFactory() as session:
        new_status = await reschedule_retry(
            session, q.id,
            error=error[:500],
            max_attempts=settings.match_worker_max_attempts,
        )
        await session.commit()
    logger.warning(
        "match_worker: queue_id=%d → %s (error=%s)", q.id, new_status, error[:100],
    )


async def ml_health_check_job() -> None:
    """APScheduler-job: poll Ollama /api/tags. Singleton OllamaHealth обновляется."""
    health = OllamaHealth.get_instance()
    await health.check()
