"""Smoke-тесты OzonParser + _parse_cards.

Сеть и browser-service не трогаем — подменяем BrowserClient.fetch на
ин-мемори payload. Цель — поймать регрессии в:
  - _parse_cards (8 уникальных карточек из реального SSR-фрагмента)
  - _parse_price_kopecks (рубли × 100, с nbsp-разделителем тысяч)
  - _title_from_slug (fallback при отсутствии русского text-node)
  - search() — protocol метрик и обработка ошибок browser-service
"""
from __future__ import annotations

import pytest

from parsers.browser_client import BrowserServiceError
from parsers.stores.ozon import (
    OzonParser,
    _parse_cards,
    _parse_price_kopecks,
    _title_from_slug,
)


# ---------------------------------------------------------------------------
# Минимальный SSR-фрагмент с тремя карточками
# ---------------------------------------------------------------------------
# Структура подобрана так, чтобы покрыть три типичных кейса Ozon:
#  1) обычная карточка с двумя ценами (price + original_price) и brand
#  2) карточка с одной ценой (без скидки) — original_price=None
#  3) карточка без русского text-node — title восстанавливается из slug

_SSR = """
<div data-widget="searchResultsV2">
  <a href="/product/nastolnaya-igra-karkasson-160655150/?at=token1" rel="noopener" class="tile">
    <img src="https://ir.ozone.ru/s3/multimedia-1-h/wc500/img1.jpg">
  </a>
  <span>1 957 ₽</span>
  <span>2 388 ₽</span>
  <span>Hobby World</span>
  <span>Настольная игра Каркассон классическая</span>

  <a href="/product/nastolnaya-igra-monopoliya-99999/?at=token2" rel="noopener" class="tile">
    <img src="https://ir.ozone.ru/s3/multimedia-1-2/wc500/img2.jpg">
  </a>
  <span>3 500 ₽</span>
  <span>Hasbro</span>
  <span>Настольная игра Монополия Россия большое издание</span>

  <a href="/product/hobby-world-nastolka-bez-titlea-77777/?at=token3" rel="noopener" class="tile">
    <img src="https://ir.ozone.ru/s3/multimedia-1-1/wc500/img3.jpg">
  </a>
  <span>500 ₽</span>
  <span>800 ₽</span>
</div>
"""


# ---------------------------------------------------------------------------
# Юниты на helpers
# ---------------------------------------------------------------------------

def test_parse_price_basic():
    """«1 957» (с nbsp) → 195700 копеек."""
    assert _parse_price_kopecks("1 957") == 195700


def test_parse_price_with_regular_space():
    """Поддерживаем и обычный пробел, и nbsp как разделитель тысяч."""
    assert _parse_price_kopecks("3 500") == 350000


def test_parse_price_invalid():
    """Текст без цифр → 0."""
    assert _parse_price_kopecks("N/A") == 0
    assert _parse_price_kopecks("") == 0


def test_title_from_slug_strips_id():
    """`/product/<slug>-<id>/` → читаемый title из slug."""
    title = _title_from_slug("/product/hobby-world-nastolka-77777/")
    assert title == "Hobby World Nastolka"


def test_title_from_slug_skips_numeric_words():
    """Числовые сегменты в slug отбрасываются (например, год)."""
    title = _title_from_slug("/product/nastolka-2023-edition-12345/")
    assert title == "Nastolka Edition"


def test_title_from_slug_invalid_path():
    assert _title_from_slug("/category/foo/") is None
    assert _title_from_slug("") is None


# ---------------------------------------------------------------------------
# Парсинг карточек
# ---------------------------------------------------------------------------

def test_parse_cards_extracts_all_three():
    products = _parse_cards(_SSR, limit=10)
    assert len(products) == 3
    assert [p.external_id for p in products] == ["160655150", "99999", "77777"]


def test_parse_cards_price_and_original_price():
    """Первая цена → price, вторая (большая) → raw['original_price']."""
    products = _parse_cards(_SSR, limit=10)
    first = products[0]
    assert first.price == 195700  # 1957 ₽ в копейках
    assert first.raw["original_price"] == 238800  # 2388 ₽


def test_parse_cards_skips_original_price_when_single():
    """Если в карточке одна цена — original_price отсутствует в raw."""
    products = _parse_cards(_SSR, limit=10)
    second = products[1]  # Монополия — одна цена 3500
    assert second.price == 350000
    assert "original_price" not in second.raw


def test_parse_cards_title_fallback_to_slug():
    """Третья карточка без русского text-node → title из slug."""
    products = _parse_cards(_SSR, limit=10)
    third = products[2]
    # slug: hobby-world-nastolka-bez-titlea
    assert third.title == "Hobby World Nastolka Bez Titlea"


def test_parse_cards_image_url():
    products = _parse_cards(_SSR, limit=10)
    assert products[0].image_url == "https://ir.ozone.ru/s3/multimedia-1-h/wc500/img1.jpg"


def test_parse_cards_url_built_from_path():
    products = _parse_cards(_SSR, limit=10)
    assert products[0].url == "https://www.ozon.ru/product/nastolnaya-igra-karkasson-160655150/"


def test_parse_cards_brand_when_present():
    """Brand попадает в raw, когда найден латинский text-node."""
    products = _parse_cards(_SSR, limit=10)
    assert products[0].raw["brand"] == "Hobby World"


def test_parse_cards_in_stock_always_true():
    """Ozon не показывает out-of-stock в search-выдаче — кладём True."""
    products = _parse_cards(_SSR, limit=10)
    assert all(p.raw["in_stock"] is True for p in products)


def test_parse_cards_dedupes_repeated_links():
    """Каждый товар повторяется в HTML 2-3 раза (фото-ссылка + title-ссылка)."""
    html = _SSR.replace(
        '<a href="/product/nastolnaya-igra-karkasson-160655150/?at=token1"',
        '<a href="/product/nastolnaya-igra-karkasson-160655150/?at=token1a"',
        1,
    )
    # Добавим вторую ссылку на тот же товар
    html = html + '<a href="/product/nastolnaya-igra-karkasson-160655150/">x</a>'
    products = _parse_cards(html, limit=10)
    ids = [p.external_id for p in products]
    assert ids.count("160655150") == 1


def test_parse_cards_respects_limit():
    products = _parse_cards(_SSR, limit=2)
    assert len(products) == 2


def test_parse_cards_empty_html():
    assert _parse_cards("", limit=10) == []
    assert _parse_cards("<html><body>nothing</body></html>", limit=10) == []


# ---------------------------------------------------------------------------
# OzonParser.search() — protocol и обработка ошибок
# ---------------------------------------------------------------------------

class _FakeBrowserClient:
    """Подменяет BrowserClient.fetch на ин-мемори payload."""

    def __init__(self, *, html: str = _SSR, status: int = 200, raise_exc: Exception | None = None) -> None:
        self.html = html
        self.status = status
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    async def fetch(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        return {
            "html": self.html,
            "status": self.status,
            "url": kwargs["url"],
            "headers": {},
            "cookies": [],
            "elapsed_ms": 3500,
        }


@pytest.mark.asyncio
async def test_search_returns_parsed_products():
    parser = OzonParser(browser_client=_FakeBrowserClient())
    products = await parser.search("Каркассон", limit=5)
    assert len(products) == 3
    assert products[0].title == "Настольная игра Каркассон классическая"


@pytest.mark.asyncio
async def test_search_uses_persistent_profile():
    """profile_id='ozon' должен передаваться в browser-service — иначе
    каждый запрос создаёт новый context и не накапливаются cookies."""
    fake = _FakeBrowserClient()
    parser = OzonParser(browser_client=fake)
    await parser.search("Каркассон", limit=5)
    assert fake.calls[0]["profile_id"] == "ozon"


@pytest.mark.asyncio
async def test_search_targets_boardgames_category_url():
    """С 2026-05-18 поиск идёт внутри категории «Настольные и карточные
    игры» (id=13506), а не глобальный `/search/?text=`. Это исключает
    книги/одежду из выдачи на общих запросах."""
    fake = _FakeBrowserClient()
    parser = OzonParser(browser_client=fake)
    await parser.search("книга", limit=5)
    url = fake.calls[0]["url"]
    assert "/category/nastolnye-i-kartochnye-igry-13506/" in url
    assert "?text=" in url
    # старый sсh-URL не должен дёргаться
    assert "/search/?text=" not in url


@pytest.mark.asyncio
async def test_search_metrics_recorded():
    parser = OzonParser(browser_client=_FakeBrowserClient())
    await parser.search("Каркассон", limit=5)
    m = parser.last_metrics
    assert m is not None
    assert m.http_requests == 1
    assert m.enrich_ms is None  # Ozon — search-only, без enrich
    assert m.result_after_enrich == 3


@pytest.mark.asyncio
async def test_search_raises_without_browser_client():
    """Если browser-service не подключён, парсер должен явно сообщить о причине,
    а не молча падать с TypeError."""
    parser = OzonParser(browser_client=None)
    with pytest.raises(RuntimeError, match="browser-service не подключён"):
        await parser.search("Каркассон", limit=5)


@pytest.mark.asyncio
async def test_search_raises_on_browser_service_error():
    fake = _FakeBrowserClient(raise_exc=BrowserServiceError(503, "browser unavailable"))
    parser = OzonParser(browser_client=fake)
    with pytest.raises(RuntimeError, match="browser-service 503"):
        await parser.search("Каркассон", limit=5)


@pytest.mark.asyncio
async def test_search_raises_on_antibot_challenge_html():
    """Если Camoufox не прошёл challenge — мы получим challenge-page HTML.
    Парсер должен поймать это по характерному <title>, а не возвращать пустой
    список (это бы похоронило ошибку в метриках 'success, но 0 товаров')."""
    challenge_html = (
        "<!DOCTYPE html><html><head>"
        "<title>Antibot Challenge Page</title></head><body></body></html>"
    )
    fake = _FakeBrowserClient(html=challenge_html)
    parser = OzonParser(browser_client=fake)
    with pytest.raises(RuntimeError, match="antibot challenge не пройден"):
        await parser.search("Каркассон", limit=5)


@pytest.mark.asyncio
async def test_search_raises_on_empty_html():
    fake = _FakeBrowserClient(html="")
    parser = OzonParser(browser_client=fake)
    with pytest.raises(RuntimeError, match="пустой HTML"):
        await parser.search("Каркассон", limit=5)
