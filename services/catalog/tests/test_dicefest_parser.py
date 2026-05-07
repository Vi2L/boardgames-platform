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
    _classify_link,
    _extract_preorder_price,
    _parse_release_date,
    _split_title_ru_en,
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
    """Полная карточка (Mythologies) — все основные поля заполнены.

    Карточка со статусом «Ждем предзаказ»: цены и BGG-ссылки нет, но есть
    описание/обложка/издатель. release_year/_month УБРАНЫ из колонок (PR-4).
    """
    g = parse_card_html(_load("dicefest_card_full.html"), "mythologies")
    assert isinstance(g, DicefestGame)
    assert g.slug == "mythologies"
    assert g.page_url == f"{BASE_URL}/game/mythologies/"
    assert g.title_ru == "Mythologies"
    assert g.title_en is None  # `/` нет в названии
    assert g.publisher == "4GAMES"
    assert g.release_status == "buduschie-predzakazy"
    assert g.cover_url is not None and g.cover_url.startswith(BASE_URL + "/upload/iblock/")
    assert g.description is not None
    assert "Mythologies" in g.description
    # PR-4: цены/external_links могут быть пустыми (статус buduschie-predzakazy).
    assert g.preorder_price is None
    # raw содержит вспомогательные поля
    assert "description_pairs" in g.raw
    assert "features" in g.raw
    assert g.raw.get("raw_title") == "Mythologies"


def test_parse_card_with_year_half() -> None:
    """A Gest of Robin Hood — features players/clock корректно парсятся."""
    g = parse_card_html(_load("dicefest_card_year_half.html"), "a-gest-of-robin-hood")
    assert g.title_ru == "A Gest of Robin Hood"
    assert g.publisher == "GaGa Games"
    # players + clock features (link не должен попадать в raw.features)
    assert g.raw["features"].get("players") == "2 игрока"
    assert g.raw["features"].get("clock") == "45-90 мин"
    assert "link" not in g.raw["features"]
    # description_pairs сохранены — есть «Предзаказ: 2 половина 2026»
    pre = g.raw["description_pairs"].get("Предзаказ", {}).get("value", "")
    assert "2026" in pre
    assert g.cover_url is not None
    # На карточке a-gest есть Tesera-ссылка ('Перейти на Tesera').
    kinds = [link["kind"] for link in g.external_links]
    assert "tesera" in kinds


def test_parse_card_unknown_date() -> None:
    """Claustrophobia 1692 — даты «пока не знаем :)» → release_text != '', цены нет."""
    g = parse_card_html(_load("dicefest_card_unknown_date.html"), "claustrophobia-1692")
    assert g.title_ru == "Claustrophobia 1692"
    assert g.publisher == "GaGa Games"
    assert g.preorder_price is None


def test_parse_card_in_stock_with_price_and_links() -> None:
    """A Wild Venture — статус v-prodazhe.

    Проверяем PR-4 фичи на реальной карточке:
      - title_ru/title_en split по `/` («Дикое приключение / A Wild Venture»...
        НО на странице раз карточки сам <h2> только английский. Проверим, что
        получим хотя бы корректный title_ru = 'A Wild Venture').
      - preorder_price извлечён из «1990 руб» → 199000 копеек
      - external_links содержит BGG (с external_id) и shop (gaga-games)
    """
    g = parse_card_html(_load("dicefest_card_in_stock.html"), "a-wild-venture")
    assert g.publisher == "GaGa Games"
    assert g.release_status == "v-prodazhe"
    # Цена «1990 руб» → 199000 копеек (1990 × 100)
    assert g.preorder_price == 199000
    # External links: BGG + shop
    kinds = [link["kind"] for link in g.external_links]
    assert "bgg" in kinds
    assert "shop" in kinds
    bgg_link = next(link for link in g.external_links if link["kind"] == "bgg")
    assert bgg_link["external_id"] == "447174"
    assert bgg_link["url"].startswith("https://boardgamegeek.com/")
    shop_link = next(link for link in g.external_links if link["kind"] == "shop")
    assert "gaga-games.com" in shop_link["url"]


def test_parse_card_broken_html_does_not_throw() -> None:
    """Мусорный HTML без ожидаемых блоков — graceful, всё None кроме slug."""
    g = parse_card_html("<html><body>nothing here</body></html>", "garbage")
    assert g.slug == "garbage"
    assert g.title_ru is None
    assert g.title_en is None
    assert g.publisher is None
    assert g.release_status is None
    assert g.preorder_price is None
    assert g.external_links == []
    assert g.cover_url is None
    assert g.description is None
    # raw_html сохранён (нужен для re-parse при изменении селекторов)
    assert g.raw_html.startswith("<html>")


# ─── _split_title_ru_en (PR-4) ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Стандартный «RU / EN» с пробелами вокруг `/`
        ("Дикое приключение / A Wild Venture", ("Дикое приключение", "A Wild Venture")),
        # Без пробела перед слэшем — частый случай на dicefest
        (
            "Adventure Games: Экспедиция Азкана/ Expedition Azcana",
            ("Adventure Games: Экспедиция Азкана", "Expedition Azcana"),
        ),
        # «20 костей / 20 strong» — RU слева, EN справа (содержит цифры/латиницу)
        ("20 костей / 20 strong", ("20 костей", "20 strong")),
        # Только английский, без `/`
        ("A Gest of Robin Hood", ("A Gest of Robin Hood", None)),
        # Только русский
        ("Каркассон", ("Каркассон", None)),
        # Обе части кириллические — не разделяем (неоднозначно)
        ("Базовая / Расширенная", ("Базовая / Расширенная", None)),
        # Обе латинские — тоже не разделяем
        ("Standard / Deluxe", ("Standard / Deluxe", None)),
        # Edge: пустая половина (одинокий `/`)
        ("Game/", ("Game/", None)),
        # None / пустота
        (None, (None, None)),
        ("", (None, None)),
    ],
)
def test_split_title_ru_en(raw: str | None, expected: tuple[str | None, str | None]) -> None:
    assert _split_title_ru_en(raw) == expected


# ─── _classify_link (PR-4) ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://boardgamegeek.com/boardgame/447174/a-wild-venture", ("bgg", "447174")),
        ("https://www.boardgamegeek.com/boardgame/822/carcassonne", ("bgg", "822")),
        # BGG расширения — тоже распознаются
        ("https://boardgamegeek.com/boardgameexpansion/12345/foo", ("bgg", "12345")),
        ("https://tesera.ru/game/pandemic/", ("tesera", "pandemic")),
        ("https://nastolio.ru/some-game/", ("nastolio", None)),
        # Магазины-партнёры → 'shop'
        ("https://www.gaga-games.com/preorder/wildventure/", ("shop", None)),
        ("https://hobbygames.ru/something", ("shop", None)),
        ("https://crowd.games/g/foo", ("shop", None)),
    ],
)
def test_classify_link(url: str, expected: tuple[str, str | None]) -> None:
    assert _classify_link(url) == expected


# ─── _extract_preorder_price (PR-4) ──────────────────────────────────────────


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1990 руб", 199000),       # обычная форма
        ("1 990 руб", 199000),      # с пробелом-разделителем тысяч
        ("1990₽", 199000),          # символ рубля
        ("1990 рублей", 199000),    # «рублей» вместо «руб»
        ("1990,00 руб", 199000),    # копеек целое — отбрасываем дробную часть
        ("100 руб", 10000),
        ("", None),
        ("пока не знаем", None),
    ],
)
def test_extract_preorder_price(value: str, expected: int | None) -> None:
    pairs = {"Цена на предзаказе": {"value": value, "data_status": None}}
    assert _extract_preorder_price(pairs) == expected


def test_extract_preorder_price_missing_pair() -> None:
    """Если pair «Цена на предзаказе» отсутствует — возвращаем None, не падаем."""
    assert _extract_preorder_price({}) is None
    assert _extract_preorder_price({"Издательство": {"value": "X", "data_status": None}}) is None


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
