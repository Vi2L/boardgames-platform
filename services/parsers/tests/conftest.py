"""Глобальные фикстуры для parsers tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_breakers():
    """PRS-7: breaker state per-process. Между тестами обнуляем, иначе
    предыдущий тест может оставить open-breaker и сломать соседний."""
    from parsers.utils.breaker import reset_for_tests
    reset_for_tests()
    yield
    reset_for_tests()
