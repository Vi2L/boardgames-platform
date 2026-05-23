"""MatchEngine — оркестратор tier'ов. Точка входа для ingest и worker'а.

API:
  - match_sync(session, title_raw, ...) — синхронный T0→T1. Используется в
    `/ingest/offers`. Если матч не нашёлся — возвращает MatchResult(needs_async=True),
    caller сам решает: пушить в очередь или ставить 'unmatched'.
  - match_async(session, ctx, ...) — выполняется воркером для одной записи
    match_queue. Идёт T2→T3, использует pending tier'ы только если ML up.

Engine не пишет в match_log — это делает caller (ingest, worker, router).
Это даёт fine-grained контроль: caller знает batch_id, performed_by,
prev_state — engine не должен дублировать эту логику.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from catalog.config import get_settings
from catalog.matching.kind_classifier import classify_kind
from catalog.matching.morphology import safe_lemmatize_ru
from catalog.matching.title_pipeline import TitlePipeline, load_pipeline
from catalog.matching.v2.domain import (
    MatchAction,
    MatchContext,
    MatchResult,
    normalize_title,
)
from catalog.runtime_flags import is_ml_enabled
from catalog.matching.v2.tiers import tier_0_cache, tier_1_trgm

logger = logging.getLogger(__name__)


class MatchEngine:
    """Оркестратор. Не stateless — держит ссылку на OllamaHealth и threshold'ы.

    Не singleton: создаётся per-request (через FastAPI Depends) или per-batch
    в worker'е. Чтения, которые должны hot-reload'иться (`ml_enabled` через
    `runtime_flags`), делаются непосредственно в `match_sync` через
    `is_ml_enabled()`. Остальное (`match_t1_auto_threshold` и т.п.) пока
    зафиксировано на момент создания engine'а — Settings обёрнут lru_cache.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def match_sync(
        self,
        title_raw: str,
        *,
        store_slug: str | None = None,
        pipeline: TitlePipeline | None = None,
    ) -> MatchResult:
        """Sync pipeline: Tier 0 → Tier 1.

        Title pre-processing (CAT-17.2):
          1. Загружаем pipeline из match_publisher_prefixes (cached 5 мин).
          2. pipeline.process(title_raw) → title_clean — без префикса, без
             маркетинговых слов, без артикулов и edition markers.
          3. normalize_title(title_clean) → title_norm для T0 cache lookup.
          4. tier_1_trgm получает title_clean (PG сам сделает unaccent) и
             опционально title_lemma_query (CAT-17.3) для морфологического
             CTE.

        Caller может передать готовый `pipeline` — экономит на повторной
        загрузке внутри batch-операций (`reassess_all`).

        Возвращает:
          - matched MatchResult если T0 cache hit (даже negative cache)
          - matched MatchResult если T1 ≥ 0.92 auto threshold
          - unmatched MatchResult с needs_async=True если ML up и T0+T1 не сошлись
          - unmatched MatchResult с needs_async=False если ML disabled

        Не пишет в БД — только читает. Caller (ingest router) делает UPDATE
        offers + INSERT match_log + INSERT match_queue в своей транзакции.
        """
        # Title pre-processing (CAT-17.2).
        if pipeline is None:
            pipeline = await load_pipeline(self.session)
        title_clean = pipeline.process(title_raw)
        title_norm = normalize_title(title_clean)

        # Tier 0: cache hit по «чистому» title_norm.
        t0 = await tier_0_cache(self.session, title_norm)
        if t0 is not None:
            # Cache может быть negative (cached_reject) — тоже возвращаем.
            return t0

        # Tier 1: pg_trgm ≥ 0.92.
        # title_lemma_query (CAT-17.3) — query-time лемматизация для
        # сопоставления с games.title_lemma. Если pymorphy3 недоступен или
        # title_clean чисто латинский — None (CTE from_title_lemma пропустится).
        title_lemma_query = safe_lemmatize_ru(title_clean)

        t1 = await tier_1_trgm(
            self.session, title_clean,
            auto_threshold=self.settings.match_t1_auto_threshold,
            title_lemma_query=title_lemma_query,
        )
        if t1 is not None and t1.matched:
            return t1

        # Sync tier'ы не дали уверенного матча. Решаем — нужен ли async.
        # ML может быть выключен через runtime_flags.ml_enabled — kill switch
        # без рестарта (PATCH /admin/runtime-flags/ml_enabled).
        if not await is_ml_enabled(self.session):
            return MatchResult(
                game_id=None,
                tier=t1.tier if t1 else None,
                action=None,
                reason="ml_disabled",
                score=t1.score if t1 else None,
                candidates=t1.candidates if t1 else None,
                needs_async=False,
            )

        # CAT-17.1: rule-based kind_classifier ДО enqueue. Воркер передаст
        # predicted_kind в `tier_2_vector(kind_filter=...)` — это экономит
        # embed-вызовы и улучшает precision на expansion/promo.
        # ВАЖНО: вызываем с title_raw (до pipeline), а не title_clean —
        # pipeline вырезает «big box» как edition marker, и classify_kind
        # его потеряет. На raw маркер сохраняется. См. title_pipeline._EDITION_RE.
        predicted_kind = classify_kind(title_raw)

        # ML включён — оффер должен попасть в очередь воркера.
        # Реальная проверка доступности Ollama (circuit breaker) делается в
        # worker'е перед обработкой; здесь мы просто помечаем «нужен async».
        return MatchResult(
            game_id=None,
            tier=t1.tier if t1 else None,
            action=None,
            reason="needs_ml",
            score=t1.score if t1 else None,
            candidates=t1.candidates if t1 else None,
            predicted_kind=predicted_kind,
            needs_async=True,
        )

    async def match_async(
        self,
        ctx: MatchContext,
    ) -> MatchResult:
        """Async pipeline: Tier 2 (bge-m3 cosine) → Tier 3 (qwen LLM-арбитр).

        Используется альтернативно к `worker.py` flow — нужен для тестов
        и кейсов когда матчинг хочется выполнить в request-pipeline'е без
        очереди (например, `POST /matching/{offer_id}/reassess` мог бы
        дёрнуть сюда вместо enqueue).

        Возвращает:
          - matched MatchResult (tier=2/3) при успехе T2 или T3.
          - unmatched (`vec_no_candidates`) если pgvector ничего не вернул.
          - unmatched (`ml_unavailable`) если bge-m3 down.
          - unmatched (`llm_unavailable`) если bge-m3 ok, но LLM down — у
            оператора будет T2-кандидат для контекста в manual queue.
          - результат `tier_3_llm` (matched или `llm_low_confidence`/`llm_no_match`)
            если T2 был ambiguous.
        """
        from catalog.matching.v2.embeddings import tier_2_vector
        from catalog.matching.v2.llm_arbiter import tier_3_llm
        from catalog.matching.v2.health import OllamaHealth

        health = OllamaHealth.get_instance()

        # T2: bge-m3 cosine
        if not health.is_available_for(self.settings.ml_embed_model):
            return MatchResult(
                game_id=None, tier=None, action=None,
                reason="ml_unavailable", needs_async=True,
            )

        t2 = await tier_2_vector(
            self.session, ctx,
            top_k=self.settings.match_t2_top_k,
            auto_threshold=self.settings.match_t2_auto_threshold,
            min_score=self.settings.match_t3_min_score,
        )
        if t2 is None:
            return MatchResult(
                game_id=None, tier=2, action=None,
                reason="vec_no_candidates",
            )
        if t2.matched:
            return t2

        # T3: LLM арбитр над несколькими кандидатами от T2.
        if not t2.candidates:
            return t2  # nothing to arbitrate
        if not health.is_available_for(self.settings.ml_llm_model):
            # T2 вернул кандидатов, но LLM down — отдаём в manual queue
            # (T4) с лучшим кандидатом для contextа оператору.
            return MatchResult(
                game_id=None,
                tier=2,
                action=None,
                reason="llm_unavailable",
                score=t2.score,
                candidates=t2.candidates,
            )

        t3 = await tier_3_llm(
            ctx, t2.candidates,
            confidence_threshold=self.settings.match_t3_confidence_threshold,
        )
        return t3


# Тонкая удобная обёртка для вызова из ingest router'а.
async def match_sync(
    session: AsyncSession,
    title_raw: str,
    *,
    store_slug: str | None = None,
    pipeline: TitlePipeline | None = None,
) -> MatchResult:
    """Shortcut для ingest: создать engine + match_sync.

    `pipeline` опционален — caller (например, reassess_all) может передать
    один экземпляр на весь batch чтобы избежать повторных SELECT'ов из БД.
    """
    engine = MatchEngine(session)
    return await engine.match_sync(
        title_raw, store_slug=store_slug, pipeline=pipeline,
    )
