"""Юнит-тесты Circuit Breaker (PRS-7).

Time-зависимые тесты используют monkeypatch на `time.monotonic` —
без реального sleep. Это держит suite быстрым (<1s на весь файл).
"""
from __future__ import annotations

import pytest

from parsers.utils import breaker as br
from parsers.utils.breaker import CircuitBreaker, get_breaker, reset_for_tests


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    yield
    reset_for_tests()


def _fake_time(start: float = 1000.0):
    """Возвращает (now_fn, advance_fn). advance двигает фейковые часы вперёд."""
    state = {"t": start}

    def now():
        return state["t"]

    def advance(secs: float):
        state["t"] += secs

    return now, advance


def test_initial_state_is_closed():
    b = CircuitBreaker("test")
    assert b.state == "closed"
    assert b.is_available() is True


def test_few_failures_below_min_samples_stay_closed(monkeypatch):
    """Меньше min_samples событий — даже все failures не открывают цепь."""
    now, _ = _fake_time()
    monkeypatch.setattr("parsers.utils.breaker.time.monotonic", now)

    b = CircuitBreaker("test", min_samples=5, failure_threshold=0.5)
    for _ in range(3):
        b.record_failure("test")
    assert b.state == "closed"


def test_opens_after_threshold_failures(monkeypatch):
    """5 failures из 5 (rate 1.0 ≥ threshold 0.5) → open."""
    now, _ = _fake_time()
    monkeypatch.setattr("parsers.utils.breaker.time.monotonic", now)

    b = CircuitBreaker("test", min_samples=5, failure_threshold=0.5)
    for _ in range(5):
        b.record_failure("429")
    assert b.state == "open"
    assert b.is_available() is False
    snap = b.snapshot()
    assert snap["state"] == "open"
    assert snap["failure_rate"] == 1.0


def test_mixed_below_threshold_stays_closed(monkeypatch):
    """3 success + 2 fail (rate 0.4 < 0.5) → остаёмся в closed."""
    now, _ = _fake_time()
    monkeypatch.setattr("parsers.utils.breaker.time.monotonic", now)

    b = CircuitBreaker("test", min_samples=5, failure_threshold=0.5)
    b.record_success(); b.record_success(); b.record_success()
    b.record_failure(); b.record_failure()
    assert b.state == "closed"


def test_open_transitions_to_half_open_after_timeout(monkeypatch):
    """open_for_sec прошло → state == half_open, is_available True."""
    now, advance = _fake_time()
    monkeypatch.setattr("parsers.utils.breaker.time.monotonic", now)

    b = CircuitBreaker("test", min_samples=5, failure_threshold=0.5, open_for_sec=300)
    for _ in range(5):
        b.record_failure()
    assert b.state == "open"
    advance(299)
    assert b.state == "open"
    advance(2)  # 301s total
    assert b.state == "half_open"
    assert b.is_available() is True


def test_half_open_success_closes_circuit(monkeypatch):
    """half_open + success → closed, events reset."""
    now, advance = _fake_time()
    monkeypatch.setattr("parsers.utils.breaker.time.monotonic", now)

    b = CircuitBreaker("test", min_samples=5, failure_threshold=0.5, open_for_sec=300)
    for _ in range(5):
        b.record_failure()
    advance(301)
    assert b.state == "half_open"

    b.record_success()
    assert b.state == "closed"
    # Events окно сбрасывается — следующие 4 failure не должны открыть цепь
    # (т.к. min_samples=5 и старые забыты).
    for _ in range(4):
        b.record_failure()
    assert b.state == "closed"


def test_half_open_failure_reopens(monkeypatch):
    """half_open + failure → open опять, таймер пересчитан."""
    now, advance = _fake_time()
    monkeypatch.setattr("parsers.utils.breaker.time.monotonic", now)

    b = CircuitBreaker("test", min_samples=5, failure_threshold=0.5, open_for_sec=300)
    for _ in range(5):
        b.record_failure()
    advance(301)
    assert b.state == "half_open"

    b.record_failure("still broken")
    # Снова open
    assert b.state == "open"
    # И таймер пересчитан с нуля
    advance(100)
    assert b.state == "open"


def test_window_evicts_old_events(monkeypatch):
    """События старше window_sec не считаются — даже все failures
    в далёком прошлом не открывают цепь сейчас."""
    now, advance = _fake_time()
    monkeypatch.setattr("parsers.utils.breaker.time.monotonic", now)

    b = CircuitBreaker("test", min_samples=5, failure_threshold=0.5,
                      window_sec=60, open_for_sec=300)
    for _ in range(10):
        b.record_failure()
    # Уже open от 10 fresh failures.
    assert b.state == "open"

    # Перематываем 400с — это > open_for_sec (half_open), и старые
    # события вне окна. Ещё один success в half_open → closed.
    advance(400)
    assert b.state == "half_open"
    b.record_success()
    assert b.state == "closed"


def test_get_breaker_is_singleton_per_store():
    b1 = get_breaker("wb")
    b2 = get_breaker("wb")
    assert b1 is b2
    b3 = get_breaker("ozon")
    assert b1 is not b3


def test_get_breaker_kwargs_only_on_first_call():
    """Повторный get_breaker НЕ применяет новые kwargs — это сигнал, что
    разные параметры для одного store были бы запахом смешения."""
    b1 = get_breaker("wb", failure_threshold=0.9)
    b2 = get_breaker("wb", failure_threshold=0.1)
    assert b1 is b2
    assert b1.failure_threshold == 0.9


def test_snapshot_returns_diagnostics(monkeypatch):
    now, _ = _fake_time()
    monkeypatch.setattr("parsers.utils.breaker.time.monotonic", now)

    b = CircuitBreaker("test", min_samples=5)
    b.record_success()
    b.record_failure("HTTP 429")
    snap = b.snapshot()
    assert snap["store"] == "test"
    assert snap["state"] == "closed"
    assert snap["events_in_window"] == 2
    assert snap["last_failure_reason"] == "HTTP 429"
    assert snap["opens_until"] is None


def test_all_breakers_lists_registered():
    get_breaker("wb")
    get_breaker("ozon")
    breakers = br.all_breakers()
    slugs = {b.store for b in breakers}
    assert slugs == {"wb", "ozon"}
