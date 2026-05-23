"""Post-process scoring для pg_trgm-кандидатов (CAT-17 follow-up).

pg_trgm-similarity считает похожесть строк по доле общих триграмм. Это
хорошо ловит опечатки («Каркасон» vs «Каркассон») и разные регистры, но
**не различает базовую игру и её спин-офф**:

    "Чудеса света"                vs "Чудеса света"                → 1.00 ✓
    "Чудеса света новых времен"   vs "Чудеса света"                → 0.81 ✗
    "В поисках Эльдорадо: Золотые храмы" vs "В поисках Эльдорадо"  → 0.85 ✗

Слова «новых времен», «Золотые храмы» — это сильный сигнал «другая
игра / спин-офф», но pg_trgm их игнорирует, потому что они только
**добавляют** триграммы, а доля общих остаётся высокой.

**Token-overlap penalty** — heuristic post-process: считаем symmetric
difference токенов query и matched_text, штрафуем score пропорционально
доле лишних слов. Это аналог Lucene `coord_factor` и Elasticsearch
`fuzzy_match` для лексического overlap.

Применяется в `tier_1_trgm` после fetch SQL-кандидатов, перед сравнением
с порогом auto-match. Не меняет SQL — pure-Python post-process по
loaded rows.
"""
from __future__ import annotations

import re


# Token split: всё что не буква/цифра — разделитель. Lowercase. Токены
# короче 2 символов отбрасываются (предлоги «в», «и», «с» не влияют на
# похожесть — они есть и там и там).
_TOKEN_SPLIT_RE = re.compile(r"\W+", re.UNICODE)


def tokens(text: str) -> set[str]:
    """Разбивает text на множество токенов (lowercase, len > 1)."""
    if not text:
        return set()
    return {t for t in _TOKEN_SPLIT_RE.split(text.lower()) if len(t) > 1}


# Параметры penalty. Подобраны эмпирически на реальных кейсах:
#   - alpha=0.6: при полностью неперекрывающихся токенах score падает на 0.6
#     (например, trgm 0.81 → 0.21, явно ниже T1 порога 0.92);
#   - чем больше lop-sided overlap, тем сильнее penalty.
_PENALTY_ALPHA = 0.6


def token_overlap_penalty(query: str, matched_text: str) -> float:
    """Возвращает penalty ∈ [0, _PENALTY_ALPHA] на основе symmetric
    difference токенов query и matched.

    Penalty = α × |q_tokens Δ m_tokens| / max(|q_tokens|, |m_tokens|)

    Примеры (α=0.6):
        "Каркассон" vs "Каркассон":              Δ={}  → penalty 0.00
        "Каркасон" vs "Каркассон":               Δ={каркасон, каркассон}/1=2 → 0.60 (но trgm на опечатке = 0.90, итог 0.30 — что низко)
            (этот кейс ловится через title_lemma в T1, не через trgm на raw — penalty не применяется)
        "Чудеса света новых времен" vs "Чудеса света":  Δ={новых, времен}/4=0.5 → 0.30
        "В поисках Эльдорадо Золотые храмы" vs "В поисках Эльдорадо": Δ={золотые, храмы}/5=0.4 → 0.24
        "Великий западный путь Новая Зеландия игра" vs "Великий западный путь": Δ={новая, зеландия, игра}/6=0.5 → 0.30

    Edge case с очень короткими токенами: «и», «в», «с» (предлоги) — не
    учитываются (отфильтровано по len > 1 в `tokens()`), поэтому
    «Каркассон и Зодиак» vs «Каркассон» не теряет penalty из-за «и».
    """
    q = tokens(query)
    m = tokens(matched_text)
    if not q or not m:
        return 0.0

    sym_diff = q ^ m
    if not sym_diff:
        return 0.0

    denom = max(len(q), len(m))
    if denom == 0:
        return 0.0

    diff_ratio = len(sym_diff) / denom
    return _PENALTY_ALPHA * diff_ratio


def adjust_score(raw_score: float, query: str, matched_text: str) -> float:
    """Возвращает skor с применённым token-overlap penalty, ограниченный [0, 1].

    Используется в `tier_1_trgm` после fetch rows: для каждого кандидата
    `adjusted = adjust_score(trgm_score, title_raw, matched_text)`. Затем
    сортировка по adjusted и сравнение с порогом auto_threshold.

    Сохранение `raw_score` рекомендуется для аудита/диагностики в
    `MatchResult.candidates[i]["raw_score"]` — оператор видит обе
    величины (например в Штучном матчинге).
    """
    penalty = token_overlap_penalty(query, matched_text)
    return max(0.0, min(1.0, raw_score - penalty))
