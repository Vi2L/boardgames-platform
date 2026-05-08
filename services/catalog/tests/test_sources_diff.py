"""Тесты canonical-хеша и field-diff'а для detection-логики.

Pure-function тесты — без БД и HTTP. Цель — гарантировать, что:
  * хеш стабилен относительно порядка ключей и порядка списков ссылок;
  * шумящие поля (raw_html, fetched_at, source_listing) в хеш не попадают;
  * field_diffs корректно ловит изменения и игнорирует переставленные внутри
    списка элементы.
"""
from __future__ import annotations

from catalog.sources.diff import compute_content_hash, compute_field_diffs


# ─── content_hash ─────────────────────────────────────────────────────────────


def test_hash_stable_for_identical_payload() -> None:
    payload = {"title_ru": "Каркассон", "publisher": "Hobby World"}
    assert compute_content_hash(payload) == compute_content_hash(payload)


def test_hash_independent_of_dict_key_order() -> None:
    a = {"title_ru": "Каркассон", "publisher": "Hobby World"}
    b = {"publisher": "Hobby World", "title_ru": "Каркассон"}
    assert compute_content_hash(a) == compute_content_hash(b)


def test_hash_independent_of_external_links_order() -> None:
    """Парсер dicefest может возвращать ссылки в разном порядке от запуска
    к запуску. Это не должно ломать detection."""
    payload_a = {
        "title_ru": "X",
        "external_links": [
            {"kind": "bgg", "url": "https://bgg/1"},
            {"kind": "tesera", "url": "https://tesera/2"},
        ],
    }
    payload_b = {
        "title_ru": "X",
        "external_links": [
            {"kind": "tesera", "url": "https://tesera/2"},
            {"kind": "bgg", "url": "https://bgg/1"},
        ],
    }
    assert compute_content_hash(payload_a) == compute_content_hash(payload_b)


def test_hash_changes_when_payload_changes() -> None:
    base = {"title_ru": "Каркассон", "preorder_price": 199000}
    changed = {"title_ru": "Каркассон", "preorder_price": 250000}
    assert compute_content_hash(base) != compute_content_hash(changed)


def test_hash_ignores_raw_html_and_fetched_at() -> None:
    """raw_html большой и шумит timestamp'ами; fetched_at тривиально меняется."""
    a = {"title_ru": "X", "raw_html": "<html>v1</html>", "fetched_at": "2026-01-01"}
    b = {"title_ru": "X", "raw_html": "<html>v2</html>", "fetched_at": "2026-05-08"}
    assert compute_content_hash(a) == compute_content_hash(b)


def test_hash_is_64_hex_chars() -> None:
    h = compute_content_hash({"a": 1})
    assert len(h) == 64
    int(h, 16)  # должен парситься как hex


# ─── field_diffs ──────────────────────────────────────────────────────────────


def test_diffs_none_when_prev_is_none() -> None:
    assert compute_field_diffs(None, {"a": 1}) is None


def test_diffs_none_when_no_changes() -> None:
    payload = {"title_ru": "X", "publisher": "Y"}
    assert compute_field_diffs(payload, payload) is None


def test_diffs_capture_simple_change() -> None:
    prev = {"title_ru": "X", "preorder_price": 100}
    curr = {"title_ru": "X", "preorder_price": 200}
    diffs = compute_field_diffs(prev, curr)
    assert diffs == {"preorder_price": {"before": 100, "after": 200}}


def test_diffs_ignore_reordered_external_links() -> None:
    """Перестановка элементов списка не должна попадать в diff (синхронно с hash)."""
    prev = {
        "external_links": [
            {"kind": "bgg", "url": "https://bgg/1"},
            {"kind": "tesera", "url": "https://tesera/2"},
        ],
    }
    curr = {
        "external_links": [
            {"kind": "tesera", "url": "https://tesera/2"},
            {"kind": "bgg", "url": "https://bgg/1"},
        ],
    }
    assert compute_field_diffs(prev, curr) is None


def test_diffs_capture_added_field() -> None:
    prev = {"title_ru": "X"}
    curr = {"title_ru": "X", "publisher": "New"}
    diffs = compute_field_diffs(prev, curr)
    assert diffs == {"publisher": {"before": None, "after": "New"}}


def test_diffs_capture_removed_field() -> None:
    prev = {"title_ru": "X", "publisher": "Old"}
    curr = {"title_ru": "X"}
    diffs = compute_field_diffs(prev, curr)
    assert diffs == {"publisher": {"before": "Old", "after": None}}


def test_diffs_skip_excluded_keys() -> None:
    """raw_html / raw / fetched_at не должны попадать в UI-diff: они либо
    шумят (raw_html, fetched_at), либо слишком большие (raw — JSONB-дамп)."""
    prev = {"title_ru": "X", "raw_html": "<v1>", "raw": {"a": 1}, "fetched_at": "old"}
    curr = {"title_ru": "X", "raw_html": "<v2>", "raw": {"a": 2}, "fetched_at": "new"}
    assert compute_field_diffs(prev, curr) is None
