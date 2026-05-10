"""Unit-тесты matching v2 — не требуют БД / Ollama.

Покрывают чистую логику: нормализация title, парсинг LLM-ответа,
circuit breaker, embedder.build_text. Эти тесты безопасны для CI
без поднятого Postgres/Ollama.

Integration-тесты с реальной БД (pgvector cosine search, FOR UPDATE
SKIP LOCKED, TTL в match_decisions) — в test_matching_v2_integration.py
(будет добавлен после применения миграции 0011 и warmup эмбеддингов).
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from catalog.matching.v2.domain import (
    MATCH_STATUS_PENDING,
    MatchAction,
    MatchContext,
    MatchResult,
    normalize_title,
)
from catalog.matching.v2.embedder import OllamaError, build_text
from catalog.matching.v2.health import OllamaHealth
from catalog.matching.v2.llm_arbiter import _parse_response


# ── normalize_title ────────────────────────────────────────────────────────


class TestNormalizeTitle:
    """NFKD-нормализация: lower + strip combining marks + strip whitespace.

    Важна корректность для Tier 0 cache lookup — должна совпадать с тем,
    что записано в match_decisions.title_norm при save_decision.
    """

    def test_lowercase(self):
        assert normalize_title("Carcassonne") == "carcassonne"

    def test_cyrillic(self):
        assert normalize_title("Каркассон") == "каркассон"

    def test_strip_whitespace(self):
        assert normalize_title("  Catan  ") == "catan"

    def test_diacritics_removed(self):
        # NFKD: 'é' → 'e' + acute, потом удаляем acute
        assert normalize_title("Société") == "societe"
        assert normalize_title("für") == "fur"

    def test_cyrillic_with_diacritics(self):
        # Й и Ё разлагаются, но й/ё в combining marks не разваливаются
        # одинаково — проверим что хотя бы lower работает.
        assert normalize_title("Сапёр") == normalize_title("Сапёр")  # idempotent
        assert "сапёр" in normalize_title("Сапёр") or "сапер" in normalize_title("Сапёр")

    def test_idempotent(self):
        """normalize(normalize(x)) == normalize(x)"""
        for s in ["Carcassonne", "Каркассон", "Société d'Édition", "  spaces  "]:
            assert normalize_title(normalize_title(s)) == normalize_title(s)

    def test_empty(self):
        assert normalize_title("") == ""
        assert normalize_title("   ") == ""

    def test_punctuation_preserved(self):
        # Знаки препинания НЕ удаляются — это часть title'а.
        assert normalize_title("Каркассон: Замок") == "каркассон: замок"


# ── MatchResult / MatchAction ──────────────────────────────────────────────


class TestMatchResult:
    def test_matched_property_true_when_game_id_set(self):
        r = MatchResult(game_id=42)
        assert r.matched is True

    def test_matched_property_false_when_game_id_none(self):
        r = MatchResult(game_id=None)
        assert r.matched is False

    def test_immutable(self):
        """frozen dataclass — нельзя случайно изменить."""
        r = MatchResult(game_id=42)
        with pytest.raises(Exception):  # FrozenInstanceError или TypeError
            r.game_id = 100  # type: ignore

    def test_default_factory(self):
        """Дефолты безопасны: пустой MatchResult — это «не сматчено»."""
        r = MatchResult()
        assert r.game_id is None
        assert r.score is None
        assert r.matched is False
        assert r.needs_async is False


def test_match_action_enum_values():
    """Enum значения должны совпадать с DB CHECK CONSTRAINT'ами match_log.action."""
    assert MatchAction.AUTO_T0.value == "auto_t0"
    assert MatchAction.AUTO_T1.value == "auto_t1"
    assert MatchAction.AUTO_T2.value == "auto_t2"
    assert MatchAction.AUTO_T3.value == "auto_t3"
    assert MatchAction.MANUAL.value == "manual"
    assert MatchAction.REJECT.value == "reject"
    assert MatchAction.UNLINK.value == "unlink"
    assert MatchAction.REASSESS.value == "reassess"
    assert MatchAction.REVERT.value == "revert"


# ── embedder.build_text ────────────────────────────────────────────────────


class TestBuildText:
    """text_used для эмбеддинга: title_ru + title + top-N aliases без дублей."""

    def test_title_only(self):
        assert build_text(title="Catan") == "Catan"

    def test_title_with_ru(self):
        result = build_text(title="Catan", title_ru="Колонизаторы")
        # ru идёт первым (приоритет для bge-m3 в RU-магазинах)
        assert result == "Колонизаторы Catan"

    def test_aliases_appended(self):
        result = build_text(
            title="Catan", title_ru="Колонизаторы",
            aliases=["Settlers of Catan", "Поселенцы"],
        )
        assert "Settlers of Catan" in result
        assert "Поселенцы" in result

    def test_dedup(self):
        """Если alias == title — не дублируем."""
        result = build_text(
            title="Catan", title_ru="Catan",
            aliases=["catan", "CATAN"],
        )
        # Один раз "Catan" в результате (case-insensitive dedup)
        assert result.lower().count("catan") == 1

    def test_max_aliases_limit(self):
        aliases = [f"alias{i}" for i in range(20)]
        result = build_text(title="X", aliases=aliases, max_aliases=3)
        # 3 алиаса включены
        for i in range(3):
            assert f"alias{i}" in result
        # 4-й — нет
        assert "alias3" not in result

    def test_none_safe(self):
        """None в любом поле не должен падать."""
        assert build_text(title="X", title_ru=None) == "X"
        assert build_text(title="X", aliases=None) == "X"
        assert build_text(title="X", title_ru=None, aliases=None) == "X"

    def test_empty_strings_skipped(self):
        result = build_text(title="X", title_ru="", aliases=["", "y"])
        # Пустые строки пропускаются
        assert result == "X y"


# ── llm_arbiter._parse_response ────────────────────────────────────────────


class TestParseLLMResponse:
    """Защиты от: невалидный JSON, markdown wrap, hallucinated game_id,
    multiple JSON objects, non-numeric confidence."""

    def test_valid_json(self):
        raw = '{"game_id": 42, "kind": "base", "confidence": 0.9, "reason": "match"}'
        result = _parse_response(raw, valid_ids={42})
        assert result is not None
        assert result["game_id"] == 42
        assert result["kind"] == "base"
        assert result["confidence"] == 0.9

    def test_null_game_id_is_valid(self):
        """game_id=null = LLM сказал «нет совпадения». Это валидный ответ."""
        raw = '{"game_id": null, "kind": "base", "confidence": 0.3, "reason": "no match"}'
        result = _parse_response(raw, valid_ids={1, 2})
        assert result is not None
        assert result["game_id"] is None

    def test_hallucinated_game_id_nulled(self):
        """LLM вернул game_id, которого нет в кандидатах — обнуляем."""
        raw = '{"game_id": 99999, "kind": "base", "confidence": 0.9, "reason": "x"}'
        result = _parse_response(raw, valid_ids={1, 2, 3})
        assert result is not None
        assert result["game_id"] is None  # hallucinated → null

    def test_invalid_kind_nulled(self):
        raw = '{"game_id": 1, "kind": "invalid_kind", "confidence": 0.5, "reason": "x"}'
        result = _parse_response(raw, valid_ids={1})
        assert result is not None
        assert result["kind"] is None  # не из whitelist'а

    def test_markdown_wrapped(self):
        """LLM добавил ```json``` обёртку."""
        raw = '```json\n{"game_id": 1, "kind": "base", "confidence": 0.8}\n```'
        result = _parse_response(raw, valid_ids={1})
        assert result is not None
        assert result["game_id"] == 1

    def test_multiple_json_objects_takes_first(self):
        """LLM написал размышления с двумя JSON — non-greedy regex берёт первый."""
        raw = 'Думаю {"game_id": 1, "kind": "base", "confidence": 0.9} или нет {"game_id": null}'
        result = _parse_response(raw, valid_ids={1, 2})
        assert result is not None
        assert result["game_id"] == 1  # первый объект

    def test_completely_invalid_returns_none(self):
        result = _parse_response("not json at all", valid_ids={1})
        assert result is None

    def test_non_numeric_confidence_defaults_to_zero(self):
        raw = '{"game_id": 1, "kind": "base", "confidence": "high", "reason": "x"}'
        result = _parse_response(raw, valid_ids={1})
        assert result is not None
        assert result["confidence"] == 0.0  # parse error → 0.0

    def test_missing_confidence_defaults_to_zero(self):
        raw = '{"game_id": 1, "kind": "base"}'
        result = _parse_response(raw, valid_ids={1})
        assert result is not None
        assert result["confidence"] == 0.0

    def test_not_dict_returns_none(self):
        raw = '[1, 2, 3]'
        result = _parse_response(raw, valid_ids={1})
        assert result is None


# ── OllamaHealth (singleton + circuit breaker) ─────────────────────────────


class TestOllamaHealth:
    """Состояние per-model: closed → open after N failures → recovery probe."""

    def setup_method(self):
        OllamaHealth.reset_for_tests()

    def teardown_method(self):
        OllamaHealth.reset_for_tests()

    def test_singleton(self):
        a = OllamaHealth.get_instance()
        b = OllamaHealth.get_instance()
        assert a is b

    def test_initially_all_unavailable(self):
        h = OllamaHealth.get_instance()
        # До первого check() — статус неизвестен, считаем недоступным.
        assert h.is_available_for("bge-m3") is False
        assert h.is_available_for("qwen2.5:7b-instruct") is False

    def test_mark_failed_after_threshold(self):
        h = OllamaHealth.get_instance()
        # 1-2 ошибки — ещё closed (если бы был раз up'd)
        h._status["bge-m3"] = True
        for _ in range(h._failure_threshold):
            h._record_failure("bge-m3", "test")
        assert h.is_available_for("bge-m3") is False

    def test_status_summary_includes_failures(self):
        h = OllamaHealth.get_instance()
        h._record_failure("bge-m3", "test_reason")
        summary = h.status_summary
        assert "failures" in summary
        assert summary["failures"]["bge-m3"] == 1

    def test_last_check_at_is_iso_string(self):
        """status_summary возвращает timestamps как ISO-строки (не float)."""
        h = OllamaHealth.get_instance()
        h._last_check_at = time.time()
        summary = h.status_summary
        # ISO-формат: содержит 'T' и timezone (UTC)
        assert summary["last_check_at"] is not None
        assert "T" in summary["last_check_at"]


# ── MatchContext: dataclass invariants ─────────────────────────────────────


def test_match_context_immutable():
    ctx = MatchContext(title_raw="X", title_norm="x")
    with pytest.raises(Exception):
        ctx.title_raw = "Y"  # type: ignore


def test_match_context_minimal():
    """Минимальный конструктор — без store_slug, offer_id."""
    ctx = MatchContext(title_raw="Каркассон", title_norm="каркассон")
    assert ctx.store_slug is None
    assert ctx.offer_id is None
    assert ctx.predicted_kind is None


# ── MATCH_STATUS_PENDING константа ──────────────────────────────────────────


def test_pending_status_constant():
    """Используется в queue_repo и tests — должна быть единственной точкой."""
    assert MATCH_STATUS_PENDING == "pending_ml"
