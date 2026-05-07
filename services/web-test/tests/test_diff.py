"""Юнит-тесты для app/diff.py — product_key и diff_snapshots."""
from __future__ import annotations

import pytest

from app.diff import diff_snapshots, product_key


def _p(id_: int = 0, slug: str = "hobbygames", title: str = "Каркассон",
       price_rub: float = 1990.0, **kwargs):
    return {
        "id": id_, "store_slug": slug, "title": title, "price_rub": price_rub,
        "image_url": None, "image_url_hd": None, "description": None,
        "players": None, "age_min": None, "playtime": None, "rules_url": None,
        "url": "https://example.com",
        "fetched_at": "2026-05-01T10:00:00Z",
        "extra": {},
        **kwargs,
    }


# ── product_key ────────────────────────────────────────────────────────────

def test_product_key_uses_sku_when_present() -> None:
    p = _p(extra={"sku": "UT-00018963"})
    assert product_key(p) == "hobbygames:sku:UT-00018963"


def test_product_key_falls_back_to_normalized_title() -> None:
    p = _p(slug="lavkaigr", title="Каркассон, расширение!", players="2-5", age_min=8)
    key = product_key(p)
    assert key.startswith("lavkaigr:title:")
    assert "каркассон расширение" in key
    assert "8" in key
    assert "2-5" in key


def test_product_key_uses_slug_id_as_last_resort() -> None:
    """Без sku и без title — последний выбор slug:id."""
    p = _p(id_=42, title="")
    assert product_key(p) == "hobbygames:id:42"


def test_product_key_stable_under_pure_id_change() -> None:
    """Когда БД пересоздаётся, id меняется, но title+age_min+players дают одинаковый ключ."""
    a = _p(id_=1, slug="gaga", title="Манчкин", players="3-6", age_min=10)
    b = _p(id_=99, slug="gaga", title="Манчкин", players="3-6", age_min=10)
    assert product_key(a) == product_key(b)


def test_product_key_normalization_ignores_punctuation_and_case() -> None:
    a = _p(title="Каркассон. Базовый набор!")
    b = _p(title="каркассон базовый набор")
    assert product_key(a) == product_key(b)


# ── diff_snapshots ─────────────────────────────────────────────────────────

def test_diff_no_changes() -> None:
    a = [_p(id_=1, extra={"sku": "X1"})]
    b = [_p(id_=1, extra={"sku": "X1"})]
    diff = diff_snapshots(a, b)
    assert diff["summary"]["changed"] == 0
    assert diff["summary"]["added"] == 0
    assert diff["summary"]["removed"] == 0
    assert diff["products"] == []


def test_diff_price_change() -> None:
    a = [_p(id_=1, extra={"sku": "X1"}, price_rub=1000.0)]
    b = [_p(id_=1, extra={"sku": "X1"}, price_rub=1100.0)]
    diff = diff_snapshots(a, b)

    assert diff["summary"]["changed"] == 1
    assert len(diff["products"]) == 1

    item = diff["products"][0]
    assert item["status"] == "changed"
    assert item["fields"]["price_rub"]["a"] == 1000.0
    assert item["fields"]["price_rub"]["b"] == 1100.0
    assert item["fields"]["price_rub"]["delta_pct"] == pytest.approx(10.0)


def test_diff_added() -> None:
    a = [_p(id_=1, extra={"sku": "X1"})]
    b = [_p(id_=1, extra={"sku": "X1"}), _p(id_=2, extra={"sku": "X2"})]
    diff = diff_snapshots(a, b)
    assert diff["summary"]["added"] == 1
    statuses = [it["status"] for it in diff["products"]]
    assert "added" in statuses


def test_diff_removed() -> None:
    a = [_p(id_=1, extra={"sku": "X1"}), _p(id_=2, extra={"sku": "X2"})]
    b = [_p(id_=1, extra={"sku": "X1"})]
    diff = diff_snapshots(a, b)
    assert diff["summary"]["removed"] == 1


def test_diff_extra_field_changes() -> None:
    """Изменение в extra считается как diff (используем stable_json)."""
    a = [_p(id_=1, extra={"sku": "X1", "rating": "4.5"})]
    b = [_p(id_=1, extra={"sku": "X1", "rating": "4.7"})]
    diff = diff_snapshots(a, b)
    assert diff["summary"]["changed"] == 1
    assert "extra" in diff["products"][0]["fields"]


def test_diff_extra_key_order_does_not_matter() -> None:
    """Порядок ключей в dict не должен считаться изменением."""
    a = [_p(id_=1, extra={"sku": "X1", "rating": "4.5"})]
    b = [_p(id_=1, extra={"rating": "4.5", "sku": "X1"})]
    diff = diff_snapshots(a, b)
    assert diff["summary"]["changed"] == 0


def test_diff_summary_counts() -> None:
    a = [_p(id_=1, extra={"sku": "X1"}, price_rub=100.0),
         _p(id_=2, extra={"sku": "X2"})]
    b = [_p(id_=1, extra={"sku": "X1"}, price_rub=200.0),
         _p(id_=3, extra={"sku": "X3"})]
    diff = diff_snapshots(a, b)
    assert diff["summary"]["a_count"] == 2
    assert diff["summary"]["b_count"] == 2
    assert diff["summary"]["added"] == 1     # X3 в b
    assert diff["summary"]["removed"] == 1   # X2 убран
    assert diff["summary"]["changed"] == 1   # X1 изменил цену
