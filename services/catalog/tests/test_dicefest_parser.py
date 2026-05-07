"""Unit-тесты pure-функций парсера dicefest.

Тестируем на реальных HTML-фикстурах в tests/fixtures/dicefest_*.html (одна
полная карточка, одна с "1/2 половина 2026", одна с "пока не знаем когда").
Без сети: parse_card_html / parse_listing_html — pure-функции от bytes.

Сетевые операции (fetch_card / fetch_listing) тестируются через
httpx.MockTransport (паттерн test_bgg_parser.py:54-79).
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from catalog.importers.dicefest import (
    BASE_URL,
    DicefestGame,
    _parse_release_date,
    fetch_card,
    fetch_listing,
    parse_card_html,
    parse_listing_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ─── parse_card_html ──────────────────────────────────────────────────────────


def test_parse_card_full() -> None:
    """Полная карточка (Mythologies) — все основные поля заполнены."""
    g = parse_card_html(_load("dicefest_card_full.html"), "mythologies")
    assert isinstance(g, DicefestGame)
    assert g.slug == "mythologies"
    assert g.page_url == f"{BASE_URL}/game/mythologies/"
    assert g.title_ru == "Mythologies"
    assert g.publisher == "4GAMES"
    # data-status code (machine-readable, стабилен между переводами UI)
    assert g.release_status == "buduschie-predzakazy"
    # Карточка с "пока не знаем" — release_year/_month остаются None
    assert g.release_year is None
    assert g.release_month is None
    assert g.cover_url is not None and g.cover_url.startswith(BASE_URL + "/upload/iblock/")
    assert g.description is not None
    assert "Mythologies" in g.description  # описание начинается с названия
    # raw содержит вспомогательные поля
    assert "description_pairs" in g.raw
    assert "features" in g.raw
    # players/clock могут быть в features (если они показаны на странице)


def test_parse_card_with_year_half() -> None:
    """A Gest of Robin Hood — "Предзаказ: 2 половина 2026" → year=2026, month=7."""
    g = parse_card_html(_load("dicefest_card_year_half.html"), "a-gest-of-robin-hood")
    assert g.title_ru == "A Gest of Robin Hood"
    assert g.publisher == "GaGa Games"
    assert g.release_year == 2026
    assert g.release_month == 7  # 2-я половина → июль (середина)
    # players + clock features
    assert g.raw["features"].get("players") == "2 игрока"
    assert g.raw["features"].get("clock") == "45-90 мин"
    assert g.cover_url is not None


def test_parse_card_unknown_date() -> None:
    """Claustrophobia 1692 — даты "пока не знаем :)" → year/month None."""
    g = parse_card_html(_load("dicefest_card_unknown_date.html"), "claustrophobia-1692")
    assert g.title_ru == "Claustrophobia 1692"
    assert g.release_year is None
    assert g.release_month is None
    assert g.publisher == "GaGa Games"


def test_parse_card_broken_html_does_not_throw() -> None:
    """Мусорный HTML без ожидаемых блоков — graceful, всё None кроме slug."""
    g = parse_card_html("<html><body>nothing here</body></html>", "garbage")
    assert g.slug == "garbage"
    assert g.title_ru is None
    assert g.publisher is None
    assert g.release_year is None
    assert g.cover_url is None
    assert g.description is None
    # raw_html сохранён (нужен для re-parse при изменении селекторов)
    assert g.raw_html.startswith("<html>")


# ─── _parse_release_date ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Январь 2026", (2026, 1)),
        ("январь 2026", (2026, 1)),
        ("Декабрь 2025", (2025, 12)),
        ("марта 2024", (2024, 3)),
        ("2 половина 2026", (2026, 7)),
        ("1 половина 2026", (2026, 1)),
        ("1 квартал 2026", (2026, 2)),
        ("3 квартал 2025", (2025, 8)),
        ("2026", (2026, None)),
        ("пока не знаем когда :)", (None, None)),
        ("пока не знаем когда (;", (None, None)),
        ("уточняется", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_release_date(text: str | None, expected: tuple[int | None, int | None]) -> None:
    assert _parse_release_date(text) == expected


# ─── parse_listing_html ───────────────────────────────────────────────────────


def test_parse_listing_dedupes_and_filters() -> None:
    """Mini-листинг: 4 уникальных slug'а игр, дубль и не-игровая ссылка отброшены."""
    slugs = parse_listing_html(_load("dicefest_listing_mini.html"))
    assert slugs == sorted([
        "mythologies",
        "a-gest-of-robin-hood",
        "claustrophobia-1692",
        "azuleo",
    ])


def test_parse_listing_extracts_from_real_card() -> None:
    """Реальная карточка тоже содержит ссылки на другие игры (recommended).
    Парсер их подберёт — это OK для сбора slug'ов, дедуп через set() выше."""
    slugs = parse_listing_html(_load("dicefest_card_full.html"))
    # У нас как минимум сама игра не должна быть в результате (ссылка вида /game/...)
    # Это смоук-проверка: парсер не падает на полном HTML карточки.
    assert isinstance(slugs, list)
    # Все slug'ы — корректные string'и
    for s in slugs:
        assert isinstance(s, str) and len(s) > 0


# ─── fetch_card / fetch_listing через MockTransport ───────────────────────────


@pytest.mark.asyncio
async def test_fetch_card_via_mock_transport() -> None:
    """fetch_card возвращает body, корректно обрабатывая 200."""
    fixture = _load("dicefest_card_full.html")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/game/mythologies/"
        return httpx.Response(200, text=fixture)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        html = await fetch_card(client, "mythologies")
        assert "<title>" in html.lower() or len(html) > 1000


@pytest.mark.asyncio
async def test_fetch_card_retries_on_5xx() -> None:
    """500 → 200: ретрай через бэкофф (мокаем sleep)."""
    fixture = "<html>ok</html>"
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        # первые два запроса — 503, третий — 200
        if call_count <= 2:
            return httpx.Response(503)
        return httpx.Response(200, text=fixture)

    # Замокаем asyncio.sleep чтобы тест не ждал реально 2+4=6 секунд
    import catalog.importers.dicefest as mod

    real_sleep = mod.asyncio.sleep

    async def fast_sleep(_):  # noqa: ANN001
        return None

    mod.asyncio.sleep = fast_sleep
    try:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            html = await fetch_card(client, "any")
        assert html == fixture
        assert call_count == 3
    finally:
        mod.asyncio.sleep = real_sleep


@pytest.mark.asyncio
async def test_fetch_listing_homepage_and_year() -> None:
    """fetch_listing(year=None) → /, fetch_listing(year=2026) → /?year=2026."""
    listing_html = _load("dicefest_listing_mini.html")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=listing_html)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        slugs1, src1 = await fetch_listing(client, year=None)
        slugs2, src2 = await fetch_listing(client, year=2026)

    assert src1 == "homepage"
    assert src2 == "year=2026"
    assert "?year=2026" in seen[1]
    assert len(slugs1) == 4
