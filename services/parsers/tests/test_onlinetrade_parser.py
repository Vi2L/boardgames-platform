"""Smoke-тесты OnlineTradeParser + _parse_cards.

Сеть и browser-service не трогаем — подменяем BrowserClient.fetch на
ин-мемори payload. Цель — поймать регрессии в:
  - _parse_cards (3 уникальных карточки из синтетического SSR-фрагмента)
  - _parse_price_kopecks (рубли × 100, с nbsp-разделителем тысяч, поддержка
    и "руб." и "₽")
  - _title_from_slug (fallback при отсутствии русского text-node;
    onlinetrade-специфичный — slug разделён "_" и "-")
  - search() — protocol метрик и обработка ошибок browser-service +
    ServicePipe challenge detection (отличается от Ozon antibot title)
"""
from __future__ import annotations

import pytest

from parsers.browser_client import BrowserServiceError
from parsers.stores.onlinetrade import (
    OnlineTradeParser,
    _parse_cards,
    _parse_price_kopecks,
    _title_from_slug,
)


# ---------------------------------------------------------------------------
# Минимальный SSR-фрагмент с тремя карточками
# ---------------------------------------------------------------------------
# Структура подобрана так, чтобы покрыть три типичных кейса onlinetrade:
#  1) обычная карточка с двумя ценами (price + original_price), brand и title
#  2) карточка с одной ценой (без скидки), title есть, brand есть
#  3) карточка без русского text-node — title восстанавливается из slug
#
# URL'ы товаров onlinetrade обычно вида
#   /<category>/<sub>/<slug_with_underscores>-<numeric-id>.html
# Цены в SSR обычно с подписью «руб.», некоторые виджеты используют «₽».

_SSR = """
<div class="indexGoods">
  <a href="/igrushki/nastolnye_igry/nastolnaya_igra_karkasson_klassicheskaya-1234567.html" class="indexGoods__item__name">
    <img src="https://preview.onlinetrade.ru/static/preview/karkasson.jpg" alt="">
  </a>
  <span class="price__current">1 990 руб.</span>
  <span class="price__old">2 490 руб.</span>
  <span class="indexGoods__item__brand">Hobby World</span>
  <span class="indexGoods__item__title">Настольная игра Каркассон классическая</span>

  <a href="/igrushki/nastolnye_igry/nastolnaya_igra_monopoliya_rossiya-9999991.html" class="indexGoods__item__name">
    <img src="https://preview.onlinetrade.ru/static/preview/monopoliya.jpg" alt="">
  </a>
  <span class="price__current">3 500 руб.</span>
  <span class="indexGoods__item__brand">Hasbro</span>
  <span class="indexGoods__item__title">Настольная игра Монополия Россия большое издание</span>

  <a href="/igrushki/nastolnye_igry/hobby_world_nastolka_bez_titlea-7777777.html" class="indexGoods__item__name">
    <img src="https://preview.onlinetrade.ru/static/preview/notitle.jpg" alt="">
  </a>
  <span class="price__current">500 ₽</span>
  <span class="price__old">800 ₽</span>
</div>
"""


# ---------------------------------------------------------------------------
# Юниты на helpers
# ---------------------------------------------------------------------------

def test_parse_price_basic():
    """«1 990» (с обычным пробелом) → 199000 копеек."""
    assert _parse_price_kopecks("1 990") == 199000


def test_parse_price_with_nbsp():
    """Поддерживаем nbsp (\xa0) как разделитель тысяч — типичный SSR-вывод."""
    assert _parse_price_kopecks("3\xa0500") == 350000


def test_parse_price_no_separator():
    """Маленькие цены без разделителя — «500» → 50000 коп."""
    assert _parse_price_kopecks("500") == 50000


def test_parse_price_invalid():
    """Текст без цифр или с мусором → 0."""
    assert _parse_price_kopecks("N/A") == 0
    assert _parse_price_kopecks("") == 0
    # Защита от ложных срабатываний — буквы в строке
    assert _parse_price_kopecks("1990 abc") == 0


def test_title_from_slug_underscore_separator():
    """onlinetrade slug разделён `_` — должно корректно разбираться на слова."""
    title = _title_from_slug(
        "/igrushki/nastolnye_igry/hobby_world_nastolka-7777777.html"
    )
    assert title == "Hobby World Nastolka"


def test_title_from_slug_dash_separator():
    """Дополнительно поддерживаем `-` в slug (для совместимости)."""
    title = _title_from_slug("/cat/sub/some-product-name-1234.html")
    assert title == "Some Product Name"


def test_title_from_slug_skips_numeric_words():
    """Числовые сегменты в slug (например, год) отбрасываются."""
    title = _title_from_slug(
        "/cat/sub/nastolka_2023_edition-99999.html"
    )
    assert title == "Nastolka Edition"


def test_title_from_slug_invalid_path():
    assert _title_from_slug("/category/foo/") is None
    assert _title_from_slug("") is None
    # Не .html в конце — не наш формат
    assert _title_from_slug("/category/foo/bar-123") is None


# ---------------------------------------------------------------------------
# Парсинг карточек
# ---------------------------------------------------------------------------

def test_parse_cards_extracts_all_three():
    products = _parse_cards(_SSR, limit=10)
    assert len(products) == 3
    assert [p.external_id for p in products] == ["1234567", "9999991", "7777777"]


def test_parse_cards_price_and_original_price():
    """Первая цена → price, вторая (большая) → raw['original_price']."""
    products = _parse_cards(_SSR, limit=10)
    first = products[0]
    assert first.price == 199000  # 1990 руб. в копейках
    assert first.raw["original_price"] == 249000  # 2490 руб.


def test_parse_cards_skips_original_price_when_single():
    """Если в карточке одна цена — original_price отсутствует в raw."""
    products = _parse_cards(_SSR, limit=10)
    second = products[1]  # Монополия — одна цена 3500
    assert second.price == 350000
    assert "original_price" not in second.raw


def test_parse_cards_supports_ruble_symbol():
    """Третья карточка использует «₽» вместо «руб.»."""
    products = _parse_cards(_SSR, limit=10)
    third = products[2]
    assert third.price == 50000  # 500 ₽
    assert third.raw["original_price"] == 80000  # 800 ₽


def test_parse_cards_title_fallback_to_slug():
    """Третья карточка без русского text-node → title из slug."""
    products = _parse_cards(_SSR, limit=10)
    third = products[2]
    # slug: hobby_world_nastolka_bez_titlea
    assert third.title == "Hobby World Nastolka Bez Titlea"


def test_parse_cards_image_url():
    products = _parse_cards(_SSR, limit=10)
    assert products[0].image_url == "https://preview.onlinetrade.ru/static/preview/karkasson.jpg"


def test_parse_cards_url_normalized_to_absolute():
    """Относительные URL'ы должны нормализоваться в абсолютные с _BASE."""
    products = _parse_cards(_SSR, limit=10)
    assert products[0].url.startswith("https://www.onlinetrade.ru/igrushki/")


def test_parse_cards_brand_when_present():
    """Brand попадает в raw, когда найден латинский text-node."""
    products = _parse_cards(_SSR, limit=10)
    assert products[0].raw["brand"] == "Hobby World"


def test_parse_cards_in_stock_always_true():
    """OnlineTrade не показывает out-of-stock в search-выдаче — кладём True."""
    products = _parse_cards(_SSR, limit=10)
    assert all(p.raw["in_stock"] is True for p in products)


def test_parse_cards_dedupes_repeated_links():
    """Если в HTML встречается одна и та же карточка несколько раз — берём
    только первую (как делает Ozon-парсер)."""
    html = _SSR + (
        '<a href="/igrushki/nastolnye_igry/'
        'nastolnaya_igra_karkasson_klassicheskaya-1234567.html">repeat</a>'
    )
    products = _parse_cards(html, limit=10)
    ids = [p.external_id for p in products]
    assert ids.count("1234567") == 1


def test_parse_cards_respects_limit():
    products = _parse_cards(_SSR, limit=2)
    assert len(products) == 2


def test_parse_cards_empty_html():
    assert _parse_cards("", limit=10) == []
    assert _parse_cards("<html><body>nothing</body></html>", limit=10) == []


# ---------------------------------------------------------------------------
# OnlineTradeParser.search() — protocol и обработка ошибок
# ---------------------------------------------------------------------------

class _FakeBrowserClient:
    """Подменяет BrowserClient.fetch на ин-мемори payload."""

    def __init__(
        self,
        *,
        html: str = _SSR,
        status: int = 200,
        raise_exc: Exception | None = None,
    ) -> None:
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
    parser = OnlineTradeParser(browser_client=_FakeBrowserClient())
    products = await parser.search("Каркассон", limit=5)
    assert len(products) == 3
    assert products[0].title == "Настольная игра Каркассон классическая"


@pytest.mark.asyncio
async def test_search_uses_persistent_profile():
    """profile_id='onlinetrade' должен передаваться в browser-service —
    иначе каждый запрос создаёт новый context и не накапливаются cookies."""
    fake = _FakeBrowserClient()
    parser = OnlineTradeParser(browser_client=fake)
    await parser.search("Каркассон", limit=5)
    assert fake.calls[0]["profile_id"] == "onlinetrade"


@pytest.mark.asyncio
async def test_search_builds_correct_url():
    """С 2026-05-18 URL поиска — `/catalogue/board_games/?search=<q>`
    вместо глобального `/search.html`. Раздел сужает выдачу до настолок."""
    fake = _FakeBrowserClient()
    parser = OnlineTradeParser(browser_client=fake)
    await parser.search("Каркассон", limit=5)
    called_url = fake.calls[0]["url"]
    assert "/catalogue/board_games/" in called_url
    assert "?search=" in called_url
    assert "onlinetrade.ru" in called_url
    # старый глобальный URL не должен дёргаться
    assert "/search.html" not in called_url


@pytest.mark.asyncio
async def test_search_metrics_recorded():
    parser = OnlineTradeParser(browser_client=_FakeBrowserClient())
    await parser.search("Каркассон", limit=5)
    m = parser.last_metrics
    assert m is not None
    assert m.http_requests == 1
    assert m.enrich_ms is None  # search-only, без enrich
    assert m.result_after_enrich == 3


@pytest.mark.asyncio
async def test_search_raises_without_browser_client():
    """Если browser-service не подключён, парсер должен явно сообщить о причине,
    а не молча падать с TypeError."""
    parser = OnlineTradeParser(browser_client=None)
    with pytest.raises(RuntimeError, match="browser-service не подключён"):
        await parser.search("Каркассон", limit=5)


@pytest.mark.asyncio
async def test_search_raises_on_browser_service_error():
    fake = _FakeBrowserClient(raise_exc=BrowserServiceError(503, "browser unavailable"))
    parser = OnlineTradeParser(browser_client=fake)
    with pytest.raises(RuntimeError, match="browser-service 503"):
        await parser.search("Каркассон", limit=5)


@pytest.mark.asyncio
async def test_search_raises_on_servicepipe_challenge_html():
    """Если Camoufox не прошёл challenge — мы получим ServicePipe-загрузчик.
    Парсер должен поймать это по характерным маркерам challenge-страницы
    (servicepipe.ru/static/fp* JS-bundle), иначе ошибка похоронится
    в метриках 'success, но 0 товаров'."""
    challenge_html = (
        "<!DOCTYPE html><html><head></head><body>"
        '<script src="https://servicepipe.ru/static/fp.min.js"></script>'
        '<div id="id_captcha_frame_div"></div>'
        "</body></html>"
    )
    fake = _FakeBrowserClient(html=challenge_html)
    parser = OnlineTradeParser(browser_client=fake)
    with pytest.raises(RuntimeError, match="ServicePipe challenge не пройден"):
        await parser.search("Каркассон", limit=5)


@pytest.mark.asyncio
async def test_search_raises_on_empty_html():
    fake = _FakeBrowserClient(html="")
    parser = OnlineTradeParser(browser_client=fake)
    with pytest.raises(RuntimeError, match="пустой HTML"):
        await parser.search("Каркассон", limit=5)
