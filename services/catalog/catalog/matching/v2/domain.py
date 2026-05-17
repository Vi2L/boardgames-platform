"""Domain types для matching v2: dataclass-результаты + helpers.

Иммутабельные value objects — создаются tier'ами, не мутируются. MatchResult
проходит насквозь через engine, ingest и worker без копирований; легко тестировать
(equals, repr).

normalize_title — единая точка нормализации title для cache lookup. На SQL-стороне
делает то же самое: `lower(immutable_unaccent(title))`. Реализация на Python нужна,
чтобы вычислить ключ кэша до SQL-запроса (Tier 0 — это просто SELECT по
`title_norm = :norm`).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum


# Допустимые значения action в match_log.
class MatchAction(str, Enum):
    """Что произошло с привязкой оффера. Значения совпадают с DB enum (str)."""
    AUTO_T0 = "auto_t0"     # Tier 0 cache hit
    AUTO_T1 = "auto_t1"     # Tier 1 pg_trgm ≥ 0.92
    AUTO_T2 = "auto_t2"     # Tier 2 embedding ≥ 0.85
    AUTO_T3 = "auto_t3"     # Tier 3 LLM арбитр
    MANUAL = "manual"       # ручной link через UI
    REJECT = "reject"       # пометка «не игра»
    UNLINK = "unlink"       # отвязать (вернуть в unmatched)
    REASSESS = "reassess"   # batch reassess
    REVERT = "revert"       # откат конкретной записи match_log
    INVALIDATE = "invalidate"  # инвалидация Tier 0 cache (CAT-12)
    # Промежуточные progress-entries для UI Штучного матчинга. Не меняют
    # offer.game_id — пишутся через `log_progress()` вместо `log_change()`.
    # При revert игнорируются (revert_one фильтрует по action не in PROGRESS).
    T2_PROGRESS = "t2_progress"  # T2 vec_search завершён, top-кандидаты в reason JSON
    T3_PROGRESS = "t3_progress"  # T3 LLM-запрос начат / завершён, payload в reason


# Допустимые значения match_status (расширение существующих).
# 'auto'|'manual'|'unmatched'|'rejected' — старые.
# 'pending_ml' — оффер в очереди T2/T3 (новое).
MATCH_STATUS_PENDING = "pending_ml"


@dataclass(frozen=True)
class MatchContext:
    """Контекст одного матчинг-запроса. Передаётся между tier'ами.

    Все поля иммутабельны — результат stateless. Не содержит ORM-объектов
    (Game/Offer), только примитивы и id'ы — это позволяет кэшировать context
    и использовать как ключ для дедупликации в очереди.
    """

    title_raw: str
    title_norm: str            # normalize_title(title_raw)
    store_slug: str | None = None
    offer_id: int | None = None        # NULL при reassess без оффера
    predicted_kind: str | None = None  # 'base'|'expansion'|'accessory' если уже знаем


@dataclass(frozen=True)
class MatchResult:
    """Результат одного tier'а или итог engine.match_*().

    Поля:
      game_id        — найденная игра или None (если не сматчен).
      score          — confidence 0..1; для T0 cache = старый saved score.
      tier           — 0..3 кто принял решение; None если не сматчен.
      action         — MatchAction для записи в match_log.
      reason         — короткое текстовое объяснение для UI ('cache_hit',
                       'vec_confident', 'llm_picked', 'no_candidates', ...).
      candidates     — top-K с score (для UI и для T3-арбитра); пусто на cache hit.
      predicted_kind — определён LLM-арбитром в T3; None для T0/T1/T2.
      needs_async    — True если sync tier'ы не сошлись и нужен T2/T3 (для
                       engine.match_sync — индикатор «push в очередь»).
    """

    game_id: int | None = None
    score: float | None = None
    tier: int | None = None
    action: MatchAction | None = None
    reason: str | None = None
    candidates: list[dict] | None = None
    predicted_kind: str | None = None
    needs_async: bool = False

    @property
    def matched(self) -> bool:
        return self.game_id is not None


def normalize_title(title: str) -> str:
    """lower + unaccent — для Tier 0 cache lookup и dedup в match_queue.

    На SQL-стороне эквивалент: `lower(immutable_unaccent(:title))`. Здесь NFKD
    + filter combining marks даёт тот же результат для большинства случаев
    (диакритика латиницы, кириллицы) без зависимости от Postgres.

    Edge cases отличий от unaccent:
      - 'ß' → 'ss' в un_unaccent (немецкое слияние) — но bge-m3 multilingual
        делает это семантически, не нужна точная эквивалентность.
      - Хеброне/арабские символы: NFKD не разлагает их, unaccent тоже.
    """
    # NFKD разлагает 'é' → 'e' + ' ́' (combining acute accent).
    nfkd = unicodedata.normalize("NFKD", title)
    # Mn = Mark, nonspacing — combining diacritics. Удаляем их.
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower().strip()
