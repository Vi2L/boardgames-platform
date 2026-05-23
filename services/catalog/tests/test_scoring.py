"""Unit-тесты для token-overlap penalty (CAT-17 follow-up).

Покрывают:
  - точное совпадение (penalty=0)
  - спин-офф/extension (penalty снижает score ниже T1 порога)
  - частичный overlap (proportional penalty)
  - edge cases: пустая строка, разный регистр, пунктуация
"""
from __future__ import annotations

import pytest

from catalog.matching.scoring import (
    adjust_score,
    token_overlap_penalty,
    tokens,
)


class TestTokens:
    def test_basic_split(self):
        assert tokens("Каркассон Замки") == {"каркассон", "замки"}

    def test_short_tokens_filtered(self):
        # Предлоги «и», «в», «с» — длина 1, отфильтрованы.
        assert tokens("Каркассон и Замки") == {"каркассон", "замки"}

    def test_punctuation_split(self):
        assert tokens("В поисках Эльдорадо: Золотые храмы") == {
            "поисках", "эльдорадо", "золотые", "храмы"
        }

    def test_case_insensitive(self):
        assert tokens("КАРКАССОН") == tokens("каркассон") == {"каркассон"}

    def test_empty(self):
        assert tokens("") == set()
        assert tokens("   ") == set()


class TestTokenOverlapPenalty:
    def test_identical_no_penalty(self):
        assert token_overlap_penalty("Каркассон", "Каркассон") == 0.0

    def test_completely_different(self):
        # Полностью разные токены: q={каркассон}, m={колонизаторы}
        # sym_diff = {каркассон, колонизаторы}, max=1, ratio=2.0 → 0.6 × 2 = 1.2, clamped
        # Но max(1,1)=1, sym_diff len = 2 → 2/1 = 2.0 → penalty 1.2 (но clamped по логике adjust_score)
        # Здесь возвращаем raw penalty.
        penalty = token_overlap_penalty("Каркассон", "Колонизаторы")
        assert penalty > 0.5  # сильный штраф

    def test_spinoff_case(self):
        # «Чудеса света новых времен» vs «Чудеса света»:
        # q={чудеса, света, новых, времен}, m={чудеса, света}
        # sym_diff = {новых, времен}, max=4, ratio=0.5 → 0.6 × 0.5 = 0.30
        penalty = token_overlap_penalty(
            "Чудеса света новых времен", "Чудеса света"
        )
        assert 0.25 <= penalty <= 0.35

    def test_extension_case(self):
        # «В поисках Эльдорадо. Золотые храмы» vs «В поисках Эльдорадо»:
        # q={поисках, эльдорадо, золотые, храмы} (4), m={поисках, эльдорадо} (2)
        # sym_diff = {золотые, храмы}, max=4, ratio=0.5 → 0.30
        penalty = token_overlap_penalty(
            "В поисках Эльдорадо. Золотые храмы", "В поисках Эльдорадо"
        )
        assert penalty >= 0.25

    def test_subset_with_extras(self):
        # «Великий западный путь Новая Зеландия игра» vs «Великий западный путь»:
        # q={великий, западный, путь, новая, зеландия, игра} (6), m={великий, западный, путь} (3)
        # sym_diff = {новая, зеландия, игра}, max=6, ratio=0.5 → 0.30
        penalty = token_overlap_penalty(
            "Великий западный путь Новая Зеландия игра", "Великий западный путь"
        )
        assert penalty >= 0.25

    def test_empty_query(self):
        assert token_overlap_penalty("", "Каркассон") == 0.0

    def test_empty_matched(self):
        assert token_overlap_penalty("Каркассон", "") == 0.0


class TestAdjustScore:
    def test_identical_keeps_score(self):
        # Точное совпадение — score не меняется.
        assert adjust_score(1.0, "Каркассон", "Каркассон") == 1.0
        assert adjust_score(0.85, "Каркассон", "Каркассон") == 0.85

    def test_spinoff_drops_below_threshold(self):
        # Главный кейс из репорта: «Чудеса света новых времен» с trgm 0.81
        # должно упасть ниже T1 порога 0.92 (на самом деле сильно ниже).
        result = adjust_score(0.81, "Чудеса света новых времен", "Чудеса света")
        assert result < 0.92  # ниже T1 auto
        assert result < 0.60  # сильно ниже — близко к cold

    def test_extension_with_collon(self):
        # «В поисках Эльдорадо. Золотые храмы» vs «В поисках Эльдорадо»
        # raw_score 0.85 (типичный trgm для substring match) → adjusted < 0.7
        result = adjust_score(0.85, "В поисках Эльдорадо. Золотые храмы", "В поисках Эльдорадо")
        assert result < 0.65

    def test_below_zero_clamped(self):
        # Очень высокий penalty не уводит score в отрицательные значения.
        result = adjust_score(0.30, "Совершенно разный текст", "Каркассон")
        assert result >= 0.0

    def test_above_one_clamped(self):
        # На всякий случай (penalty не может уйти отрицательным, но проверим).
        result = adjust_score(1.0, "Каркассон", "Каркассон")
        assert result <= 1.0
