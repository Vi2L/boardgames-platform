"""Unit-тесты для kind_classifier.

Rule-based regex — тесты должны покрыть:
  - точные positive cases: «expansion», «промо», «органайзер»;
  - точные negative cases (без маркеров → None);
  - edge cases: пустая строка, спорные кейсы (promo как expansion);
  - сохранение case-insensitivity.
"""
from __future__ import annotations

import pytest

from catalog.matching.kind_classifier import classify_kind


class TestClassifyKind:
    @pytest.mark.parametrize("title,expected", [
        # Чистый base — без маркеров
        ("Каркассон", None),
        ("Wingspan", None),
        ("Колонизаторы", None),
        ("Брасс: Бирмингем", None),

        # Expansion
        ("Каркассон: дополнение Замки", "expansion"),
        ("Wingspan: European Expansion", "expansion"),
        ("Catan Big Box", "expansion"),
        ("Каркассон Big Box", "expansion"),
        ("Брасс Делюкс-набор", "expansion"),
        ("Brass Deluxe Edition", "expansion"),
        ("Hobby World - Каркассон exp.", "expansion"),
        ("Pandemic Add-on", "expansion"),
        ("Pandemic add on", "expansion"),
        ("Тайны - аддон", "expansion"),
        ("Карты — extension pack", "expansion"),

        # Promo
        ("Каркассон промо", "promo"),
        ("Колонизаторы: промо-набор", "promo"),
        ("Wingspan promo", "promo"),
        ("Каркассон мини-доп", "promo"),
        ("Каркассон мини доп", "promo"),
        ("Тайны мини-расширение", "promo"),
        ("Промо-набор Каркассон", "promo"),

        # Accessory
        ("Органайзер для Брасс", "accessory"),
        ("Brass organizer", "accessory"),
        ("Card sleeves", "accessory"),
        ("Card-sleeves для Каркассон", "accessory"),
        ("Протекторы для карт Каркассон", "accessory"),
        ("Dice tower Каркассон", "accessory"),
        ("Inserts для Wingspan", "accessory"),
        ("Replacement tokens", "accessory"),

        # Edge: пустая строка
        ("", None),
    ])
    def test_classification(self, title: str, expected: str | None):
        assert classify_kind(title) == expected

    def test_promo_wins_over_expansion(self):
        # Когда title содержит и promo и expansion маркеры — promo важнее
        # (он более специфичен).
        result = classify_kind("Каркассон: дополнение промо")
        assert result == "promo"

    def test_accessory_wins_over_expansion(self):
        # Когда title содержит accessory и expansion маркеры — accessory важнее
        # (часто органайзеры есть «для дополнения»).
        result = classify_kind("Органайзер для дополнения Каркассон")
        assert result == "accessory"

    def test_case_insensitivity(self):
        assert classify_kind("ДОПОЛНЕНИЕ Каркассон") == "expansion"
        assert classify_kind("EXPANSION Wingspan") == "expansion"
        assert classify_kind("ПРОМО Каркассон") == "promo"

    def test_word_boundary(self):
        # «допуск» не должен считаться «дополнением» (часть слова)
        # Реалистичный пример — это не настолки, но тест ловит regex-баг.
        result = classify_kind("Каркассон допустимые материалы")
        # \b в regex предотвращает match — должно быть None
        assert result is None
