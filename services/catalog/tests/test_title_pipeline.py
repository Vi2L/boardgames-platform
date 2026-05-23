"""Unit-тесты для title_pipeline.

Тестируем только синхронные функции (`process`, `strip_publisher_prefix`) —
БД-зависимая часть (`load_pipeline`) тестируется отдельно через integration-тесты
в `test_matching_v2_integration.py`.

Список префиксов передаётся явно в каждый тест — это делает тесты независимыми
от состояния таблицы `match_publisher_prefixes` и от order'а seed-данных в
миграции.

Тесты построены вокруг **реальных** title из WB/Avito/Ozon. Если pipeline
сломается на одном из них — это значит, что product owner потеряет реальный
кейс матчинга. См. также `seed` в миграции `match_publisher_prefixes` —
там должны быть те же префиксы.
"""
from __future__ import annotations

import pytest

from catalog.matching.title_pipeline import (
    TitlePipeline,
    strip_publisher_prefix,
)


# Реальные префиксы из WB/Avito. Должны совпадать с seed в миграции
# `match_publisher_prefixes`. Отсортированы по длине DESC для greedy match.
DEFAULT_PREFIXES = tuple(sorted(
    [
        "Hobby World",
        "Hobby World -",
        "Hobby World:",
        "GaGa Games",
        "GaGa Games -",
        "GaGa Games |",
        "GaGa Games:",
        "Лавка Игр",
        "Лавка Игр:",
        "Звезда",
        "Звезда:",
        "Crowd Games",
        "Crowd Games:",
        "CrowdGames:",
        "Стиль Жизни",
        "Стиль Жизни:",
        "Мосигра",
        "Мосигра:",
        "Cosmodrome Games",
        "АСТ",
        "Мир Хобби",
        "Игромаг",
        "Правильные игры",
        "Hasbro",
        "Mattel",
    ],
    key=len,
    reverse=True,
))


@pytest.fixture
def pipeline() -> TitlePipeline:
    """Готовый pipeline с дефолтным набором префиксов."""
    return TitlePipeline(prefixes=DEFAULT_PREFIXES)


# ─── strip_publisher_prefix ──────────────────────────────────────────────────


class TestStripPublisherPrefix:
    def test_exact_prefix_removed(self):
        assert strip_publisher_prefix("Hobby World Каркассон", DEFAULT_PREFIXES) == "Каркассон"

    def test_prefix_with_colon(self):
        assert strip_publisher_prefix("Hobby World: Каркассон", DEFAULT_PREFIXES) == "Каркассон"

    def test_prefix_with_dash(self):
        assert strip_publisher_prefix("GaGa Games - Колонизаторы", DEFAULT_PREFIXES) == "Колонизаторы"

    def test_prefix_with_em_dash(self):
        # `—` (em-dash) после префикса — типографский разделитель WB
        assert strip_publisher_prefix("Hobby World — Каркассон", DEFAULT_PREFIXES) == "Каркассон"

    def test_case_insensitive(self):
        assert strip_publisher_prefix("HOBBY WORLD Каркассон", DEFAULT_PREFIXES) == "Каркассон"
        assert strip_publisher_prefix("hobby world Каркассон", DEFAULT_PREFIXES) == "Каркассон"

    def test_greedy_longest_match(self):
        # «Hobby World -» (длинный) matches раньше «Hobby World» (короткого)
        # → остаток без висящего «-».
        result = strip_publisher_prefix("Hobby World - Каркассон", DEFAULT_PREFIXES)
        assert result == "Каркассон"
        assert not result.startswith("-")

    def test_no_match_returns_original(self):
        assert strip_publisher_prefix("Каркассон базовая версия", DEFAULT_PREFIXES) == "Каркассон базовая версия"

    def test_empty_title(self):
        assert strip_publisher_prefix("", DEFAULT_PREFIXES) == ""

    def test_prefix_in_middle_not_removed(self):
        # «Hobby World» в середине title — НЕ удаляется (только prefix)
        result = strip_publisher_prefix("Каркассон от Hobby World", DEFAULT_PREFIXES)
        assert result == "Каркассон от Hobby World"


# ─── process(): полный пайплайн ──────────────────────────────────────────────


class TestProcess:
    @pytest.mark.parametrize("raw,expected", [
        # Реальные кейсы WB/Avito (см. roadmap CAT-17.2)
        ("Hobby World Настольная игра Каркассон базовая версия", "Каркассон"),
        ("GaGa Games: Колонизаторы (2-е изд.)", "Колонизаторы"),
        ("Каркассон Арт. 12345", "Каркассон"),
        ("Hobby World - Каркассон", "Каркассон"),
        ("HOBBY WORLD КАРКАССОН (2023)", "КАРКАССОН"),
        ("Hobby World: Каркассон — настольная игра", "Каркассон"),
        # Без префикса, но с маркетингом
        ("Настольная игра Каркассон", "Каркассон"),
        ("Каркассон — настольная игра для всей семьи", "Каркассон"),
        # Edition markers
        ("Колонизаторы 2nd edition", "Колонизаторы"),
        ("Брасс (новое издание)", "Брасс"),
        ("Брасс: Бирмингем", "Брасс: Бирмингем"),  # двоеточие в середине → оставляем
        # Артикулы разных форматов
        ("Каркассон Арт. B1234", "Каркассон"),
        ("Каркассон артикул 12345", "Каркассон"),
        # Год в скобках
        ("Каркассон (2023)", "Каркассон"),
        ("Wingspan [2019]", "Wingspan"),
        # Не трогаем год БЕЗ скобок — может быть частью названия
        ("1984", "1984"),
        # Чистый title — не должен меняться
        ("Каркассон", "Каркассон"),
        ("Wingspan", "Wingspan"),
        # Пустой
        ("", ""),
    ])
    def test_real_world_cases(self, pipeline: TitlePipeline, raw: str, expected: str):
        assert pipeline.process(raw) == expected

    def test_marketing_collapses_spaces(self, pipeline: TitlePipeline):
        # «Настольная игра» удаляется, остаются два пробела — должны схлопнуться
        result = pipeline.process("Каркассон настольная игра 2 копии")
        assert "  " not in result
        assert "Каркассон" in result

    def test_idempotent(self, pipeline: TitlePipeline):
        # Повторный прогон одного и того же title не меняет результат
        first = pipeline.process("Hobby World Настольная игра Каркассон")
        second = pipeline.process(first)
        assert first == second

    def test_preserves_case(self, pipeline: TitlePipeline):
        # Pipeline НЕ делает lower() — это работа normalize_title()
        assert pipeline.process("Hobby World КАРКАССОН") == "КАРКАССОН"
        assert pipeline.process("Hobby World каркассон") == "каркассон"

    def test_only_punctuation_remains_empty(self, pipeline: TitlePipeline):
        # Если после strip остался только мусор — возвращаем пустую строку
        assert pipeline.process("Hobby World :-—") == ""

    def test_handles_unicode(self, pipeline: TitlePipeline):
        # Pipeline должен корректно работать с любыми Unicode символами
        result = pipeline.process("Hobby World Pötter & Spüze")
        assert "Pötter & Spüze" in result
