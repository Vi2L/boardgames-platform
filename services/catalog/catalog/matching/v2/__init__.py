"""Matching v2 — tiered pipeline для канонизации офферов.

Архитектура:
  Tier 0 — точный hit по match_decisions (cache последних решений). Sync.
  Tier 1 — pg_trgm similarity ≥ 0.92 (узкий safety-net). Sync.
  Tier 2 — bge-m3 cosine top-K + ≥ 0.85. Async (через match_queue + worker).
  Tier 3 — qwen2.5:7b LLM-арбитр между близкими кандидатами. Async.
  Tier 4 — manual queue (UI ручного матчинга).

Sync-tiers (T0+T1) выполняются синхронно в `/ingest/offers` — низкая latency,
не зависят от Ollama. Если sync не дал уверенного матча — оффер пушится в
match_queue со status='pending'; APScheduler-воркер каждые N секунд берёт
batch и проходит T2+T3.

Graceful degradation: если Ollama недоступна, async tier'ы skip'аются (через
`OllamaHealth.is_available_for(model)`). Воркер тихо молчит, оффер остаётся
в очереди до восстановления. Sync ingest при этом продолжает работать через
T0+T1.
"""
from catalog.matching.v2.domain import (
    MatchAction,
    MatchContext,
    MatchResult,
    normalize_title,
)
from catalog.matching.v2.engine import MatchEngine, match_sync

__all__ = [
    "MatchAction",
    "MatchContext",
    "MatchEngine",
    "MatchResult",
    "match_sync",
    "normalize_title",
]
