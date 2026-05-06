"""Тесты PriceService и парсеров (без сети и реальной БД)."""

import asyncio
import tempfile
import unittest

from parsers.base import StoreParser
from parsers.db import PriceDatabase
from parsers.models import ParsedProduct, StoreInfo
from parsers.service import PriceService


# ---------------------------------------------------------------------------
# Mock-парсер
# ---------------------------------------------------------------------------

MOCK_STORE = StoreInfo(slug="mock", name="Mock Store", base_url="https://mock.example.com")


class MockParser(StoreParser):
    store = MOCK_STORE

    def __init__(self, products: list[ParsedProduct] | None = None, fail: bool = False) -> None:
        self._products = products or _default_products()
        self._fail = fail
        self.call_count = 0

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Mock network error")
        return [p for p in self._products if query.lower() in p.title.lower()][:limit]


def _default_products() -> list[ParsedProduct]:
    return [
        ParsedProduct(
            store_slug="mock",
            external_id="karkassone-base",
            title="Каркассон (базовая)",
            price=199000,
            url="/karkassone-base",
            players="2-5",
            age_min=8,
            playtime="30-45 мин",
        ),
        ParsedProduct(
            store_slug="mock",
            external_id="karkassone-ext",
            title="Каркассон: Река",
            price=49900,
            url="/karkassone-ext",
        ),
        ParsedProduct(
            store_slug="mock",
            external_id="catan",
            title="Колонизаторы Катан",
            price=299000,
            url="/catan",
        ),
    ]


def _make_service(parser: StoreParser, ttl: float = 4.0) -> tuple[PriceDatabase, PriceService]:
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    db = PriceDatabase(db_path)
    service = PriceService(db, [parser], cache_ttl_hours=ttl)
    return db, service


# ---------------------------------------------------------------------------
# Тесты PriceService (логика кеша)
# ---------------------------------------------------------------------------

class TestPriceService(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.parser = MockParser()
        self.db, self.service = _make_service(self.parser)
        await self.db.init()
        await self.db.upsert_store(MOCK_STORE)

    async def test_cold_cache_hits_parser(self) -> None:
        """При пустой БД сервис должен вызвать парсер и вернуть результаты."""
        result = await self.service.search("Каркассон")

        self.assertEqual(self.parser.call_count, 1)
        self.assertEqual(result.source, "network")
        self.assertEqual(len(result.products), 2)

    async def test_warm_cache_skips_parser(self) -> None:
        """Если кеш свежий, парсер не вызывается."""
        await self.service.search("Каркассон")
        call_after_first = self.parser.call_count

        result = await self.service.search("Каркассон")

        self.assertEqual(self.parser.call_count, call_after_first)
        self.assertEqual(result.source, "cache")

    async def test_force_refresh_bypasses_cache(self) -> None:
        """force_refresh=True всегда идёт в сеть."""
        await self.service.search("Каркассон")
        await self.service.search("Каркассон", force_refresh=True)

        self.assertEqual(self.parser.call_count, 2)

    async def test_parser_failure_returns_partial_cache(self) -> None:
        """Если парсер упал, но в кеше есть данные — возвращаем source="partial-cache"."""
        await self.service.search("Каркассон")

        failing_parser = MockParser(fail=True)
        failing_parser.store = MOCK_STORE
        service_broken = PriceService(self.db, [failing_parser], cache_ttl_hours=0)

        result = await service_broken.search("Каркассон")

        self.assertEqual(result.source, "partial-cache")
        self.assertIn("mock", result.errors)
        self.assertGreater(len(result.products), 0)

    async def test_price_stored_in_kopecks(self) -> None:
        """Цена хранится в копейках и корректно возвращается."""
        await self.service.search("Каркассон")
        result = await self.service.search("Каркассон")
        prices = {p.title: p.price for p in result.products}

        self.assertEqual(prices["Каркассон (базовая)"], 199000)

    async def test_extra_fields_persisted(self) -> None:
        """Новые поля (players, age_min, playtime) сохраняются и читаются из БД."""
        await self.service.search("Каркассон")
        result = await self.service.search("Каркассон")
        base = next(p for p in result.products if p.external_id == "karkassone-base")

        self.assertEqual(base.players, "2-5")
        self.assertEqual(base.age_min, 8)
        self.assertEqual(base.playtime, "30-45 мин")

    async def test_history_recorded_on_update(self) -> None:
        """Каждый force_refresh добавляет точку в историю цен."""
        await self.service.search("Каркассон")
        await self.service.search("Каркассон", force_refresh=True)

        result = await self.service.search("Каркассон")
        history = await self.service.get_history(result.products[0].id)

        self.assertGreaterEqual(len(history), 2)

    async def test_store_filter(self) -> None:
        """Фильтрация по store_slugs ограничивает набор парсеров."""
        with self.assertRaises(RuntimeError):
            await self.service.search("Каркассон", store_slugs=["nonexistent"])

        result = await self.service.search("Каркассон", store_slugs=["mock"])
        self.assertGreater(len(result.products), 0)


# ---------------------------------------------------------------------------
# Тесты парсера HobbyGames (поисковая страница, без сети)
# ---------------------------------------------------------------------------

class TestHobbyGamesParser(unittest.TestCase):
    """Тесты _SearchPageParser HobbyGames на статичном HTML."""

    def _make_html(self, products: list[dict]) -> str:
        cards = "".join(f"""
        <div class="product-card">
            <a href="{p['url']}" title="{p['title']}">
                <img src="{p.get('image_url', '/image/cache/test.jpg')}">
            </a>
            <h4 class="name"><a href="{p['url']}">{p['title']}</a></h4>
            <span class="price">{p['price_str']}</span>
        </div>
        """ for p in products)
        return f"<html><body>{cards}</body></html>"

    def test_parses_products(self) -> None:
        from parsers.stores.hobbygames import _SearchPageParser

        parser = _SearchPageParser()
        parser.feed(self._make_html([
            {"url": "/karkassone", "title": "Каркассон", "price_str": "1 490 ₽"},
            {"url": "/catan",      "title": "Катан",      "price_str": "2 990 ₽"},
        ]))

        self.assertEqual(len(parser.products), 2)
        self.assertEqual(parser.products[0].title, "Каркассон")
        self.assertEqual(parser.products[0].price, 149000)
        self.assertEqual(parser.products[1].price, 299000)

    def test_skips_cards_without_price(self) -> None:
        from parsers.stores.hobbygames import _SearchPageParser

        parser = _SearchPageParser()
        parser.feed(self._make_html([
            {"url": "/no-price", "title": "Без цены", "price_str": ""},
        ]))
        self.assertEqual(len(parser.products), 0)


class TestHobbyGamesEnrich(unittest.IsolatedAsyncioTestCase):
    """Тесты _enrich HobbyGames на статичном HTML страницы товара."""

    _DETAIL_HTML = (
        '<html><head>'
        '<meta property="og:image" content="https://hobbygames.ru/image/hd/kark.jpg">'
        '<meta property="og:description" content="Классика евростратегий">'
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Каркассон",'
        '"description":"Проверенная временем классика",'
        '"image":"https://hobbygames.ru/image/full/kark.jpg",'
        '"additionalProperty":['
        '{"name":"Количество игроков","value":"2-5"},'
        '{"name":"Возраст","value":"от 8 лет"},'
        '{"name":"Время партии","value":"30-45 мин"}'
        ']}</script>'
        '</head><body>'
        '<a href="/rules/karkassone_rules.pdf">Правила</a>'
        '</body></html>'
    )

    async def test_enrich_from_json_ld(self) -> None:
        from parsers.stores.hobbygames import HobbyGamesParser

        parser = HobbyGamesParser()
        product = ParsedProduct(
            store_slug="hobbygames", external_id="karkassone",
            title="Каркассон", price=199000,
            url="https://hobbygames.ru/karkassone",
        )

        class FakeResp:
            is_success = True
            text = self._DETAIL_HTML

        class FakeClient:
            async def get(self, url):
                return FakeResp()

        extra = await parser._enrich(FakeClient(), product)

        # JSON-LD имеет приоритет над og:image
        self.assertEqual(extra.get("image_url_hd"), "https://hobbygames.ru/image/full/kark.jpg")
        self.assertEqual(extra.get("description"), "Проверенная временем классика")
        self.assertEqual(extra.get("players"), "2-5")
        self.assertEqual(extra.get("age_min"), 8)
        self.assertEqual(extra.get("playtime"), "30-45 мин")
        self.assertIn("rules_url", extra)


# ---------------------------------------------------------------------------
# Тесты парсера Лавки Игр
# ---------------------------------------------------------------------------

class TestLavkaIgrParser(unittest.TestCase):
    """Тесты _SearchPageParser Лавки Игр на статичном HTML."""

    _HTML_TEMPLATE = """
    <html><body>
    <div class="product-list row">{blocks}</div>
    </body></html>
    """
    _BLOCK_TEMPLATE = """
    <div class="block"><div>
        <div class="photo-block" data-id="{ext_id}">
            <a href="{url}" class="photo">
                <img class="unveil" data-src="{img}">
            </a>
        </div>
        <h3><a class="game-name" href="{url}">{title}</a></h3>
        <p class="price">{price_rub} руб.</p>
        <a href="#" data-id="{ext_id}" data-price="{price_rub}" class="btn buy-mini">Купить</a>
    </div></div>
    """

    def _make_html(self, products: list[dict]) -> str:
        blocks = "".join(self._BLOCK_TEMPLATE.format(
            ext_id=p["ext_id"], url=p["url"],
            img=p.get("img", "https://media.lavkaigr.ru/test.png"),
            title=p["title"], price_rub=p["price_rub"],
        ) for p in products)
        return self._HTML_TEMPLATE.format(blocks=blocks)

    def test_parses_products(self) -> None:
        from parsers.stores.lavkaigr import _SearchPageParser

        parser = _SearchPageParser()
        parser.feed(self._make_html([
            {"ext_id": "5965", "url": "/shop/family/karkasson-2019/",
             "title": "Каркассон (2019)", "price_rub": 1990},
            {"ext_id": "3411", "url": "/shop/family/karkasson-holmy/",
             "title": "Каркассон 9: Холмы и овцы", "price_rub": 1490},
        ]))

        self.assertEqual(len(parser.products), 2)
        first = parser.products[0]
        self.assertEqual(first.title, "Каркассон (2019)")
        self.assertEqual(first.external_id, "5965")
        self.assertEqual(first.price, 199000)
        self.assertTrue(first.url.startswith("https://"))
        self.assertIsNotNone(first.image_url)

    def test_price_in_kopecks(self) -> None:
        from parsers.stores.lavkaigr import _SearchPageParser

        parser = _SearchPageParser()
        parser.feed(self._make_html([
            {"ext_id": "1", "url": "/shop/x/y/", "title": "Катан", "price_rub": 2990},
        ]))
        self.assertEqual(parser.products[0].price, 299000)

    def test_skips_cards_without_price(self) -> None:
        from parsers.stores.lavkaigr import _SearchPageParser

        html = self._HTML_TEMPLATE.format(blocks="""
        <div class="block"><div>
            <div class="photo-block" data-id="999">
                <a href="/shop/a/b/" class="photo">
                    <img class="unveil" data-src="https://img.ru/x.png">
                </a>
            </div>
            <h3><a class="game-name" href="/shop/a/b/">Без цены</a></h3>
        </div></div>
        """)
        parser = _SearchPageParser()
        parser.feed(html)
        self.assertEqual(len(parser.products), 0)

    def test_ignores_products_outside_list(self) -> None:
        from parsers.stores.lavkaigr import _SearchPageParser

        html = """<html><body>
        <div class="block"><div>
            <div class="photo-block" data-id="777">
                <a href="/shop/x/" class="photo"><img data-src="https://img.ru/x.png"></a>
            </div>
            <h3><a class="game-name" href="/shop/x/">Вне списка</a></h3>
            <a data-id="777" data-price="999" class="btn buy-mini">Купить</a>
        </div></div>
        </body></html>"""
        parser = _SearchPageParser()
        parser.feed(html)
        self.assertEqual(len(parser.products), 0)


class TestLavkaIgrEnrich(unittest.IsolatedAsyncioTestCase):
    """Тесты _enrich Лавки Игр на статичном HTML страницы товара."""

    _DETAIL_HTML = """
    <html>
    <head>
        <meta property="og:image" content="https://media.lavkaigr.ru/catalog/karkasson.jpg">
        <meta property="og:description" content="Средневековая стратегия">
    </head>
    <body>
        <div>
            <div><i class="fa fa-male"></i>Кол-во игроков:</div>
            <div><strong>2-5</strong> (рекомендуем 3-5)</div>
        </div>
        <div>
            <div><i class="fa fa-clock-o"></i>Время партии:</div>
            <div><strong>30-45 мин.</strong></div>
        </div>
        <div>
            <div><i class="fa fa-child"></i>Возраст:</div>
            <div><strong>от 8 лет</strong></div>
        </div>
        <div>
            <div><i class="fa fa-language"></i>Язык:</div>
            <div><strong>Русский</strong></div>
        </div>
        <a href="/shop/tag/strateg/">стратегия</a>
        <a href="/shop/tag/eurogame/">евро</a>
        <a href="https://media.lavkaigr.ru/uploads/kark_rules.pdf">Правила</a>
        <img class="unveil" data-src="https://media.lavkaigr.ru/cache/img1.png">
        <img class="unveil" data-src="https://media.lavkaigr.ru/cache/img2.png">
        <ul><li>72 квадрата местности;</li><li>40 фишек подданных;</li></ul>
    </body>
    </html>
    """

    async def test_enrich_extracts_all_fields(self) -> None:
        from parsers.stores.lavkaigr import LavkaIgrParser

        parser = LavkaIgrParser()
        product = ParsedProduct(
            store_slug="lavkaigr", external_id="5965",
            title="Каркассон (2019)", price=199000,
            url="https://www.lavkaigr.ru/shop/family/karkasson-2019/",
        )

        class FakeResp:
            is_success = True
            text = self._DETAIL_HTML

        class FakeClient:
            async def get(self, url):
                return FakeResp()

        extra = await parser._enrich(FakeClient(), product)

        self.assertEqual(extra.get("image_url_hd"),
                         "https://media.lavkaigr.ru/catalog/karkasson.jpg")
        self.assertEqual(extra.get("players"), "2-5")
        self.assertEqual(extra.get("age_min"), 8)
        self.assertEqual(extra.get("playtime"), "30-45 мин.")
        self.assertEqual(extra.get("rules_url"),
                         "https://media.lavkaigr.ru/uploads/kark_rules.pdf")
        raw = extra.get("raw", {})
        self.assertEqual(raw.get("language"), "Русский")
        self.assertIn("стратегия", raw.get("tags", []))
        self.assertGreater(len(raw.get("gallery", [])), 0)
        self.assertGreater(len(raw.get("composition", [])), 0)
        self.assertEqual(raw.get("category"), "family")


# ---------------------------------------------------------------------------
# Тесты парсера GaGa.ru
# ---------------------------------------------------------------------------

class TestGagaParser(unittest.TestCase):
    """Тесты _SearchPageParser GaGa.ru на статичном HTML."""

    _CARD_TEMPLATE = """
    <div class="preview-card">
        <p class="preview-card__title">
            <a href="{url}" title="{title}">{title}</a>
        </p>
        <figure class="preview-card__img preview-card__img--small">
            <img src="{img}" alt="{title}">
        </figure>
        <div class="preview-card__purchase" itemprop="offers" itemscope
             itemtype="http://schema.org/Offer">
            <meta itemprop="priceCurrency" content="RUB"/>
            <div class="price">
                <span class="price__value">
                    <span itemprop="price">{price_rub}</span> руб.
                </span>
            </div>
            <div class="card-btns">
                <button type="button" class="btn btn--basket add_to_cart"
                        data-gid="{gid}" data-price="{price_rub}"
                        data-name="{title}">В корзину</button>
            </div>
        </div>
    </div>
    """

    def _make_html(self, products: list[dict]) -> str:
        cards = "".join(self._CARD_TEMPLATE.format(
            gid=p["gid"], url=p["url"], title=p["title"],
            img=p.get("img", "/gaga/files/images/main/1.png"),
            price_rub=p["price_rub"],
        ) for p in products)
        return f"<html><body>{cards}</body></html>"

    def test_parses_products(self) -> None:
        from parsers.stores.gaga import _SearchPageParser

        parser = _SearchPageParser()
        parser.feed(self._make_html([
            {"gid": "4814", "url": "/game/carcassonne/",
             "title": "Каркассон. Средневековье", "price_rub": 1990,
             "img": "/gaga/files/images/main/4814.png"},
            {"gid": "5719", "url": "/game/carcassonne-big-box/",
             "title": "Каркассон: Big Box", "price_rub": 6990},
        ]))

        self.assertEqual(len(parser.products), 2)
        first = parser.products[0]
        self.assertEqual(first.title, "Каркассон. Средневековье")
        self.assertEqual(first.external_id, "4814")
        self.assertEqual(first.price, 199000)
        self.assertTrue(first.url.endswith("/game/carcassonne/"))
        self.assertIsNotNone(first.image_url)

    def test_price_in_kopecks(self) -> None:
        from parsers.stores.gaga import _SearchPageParser

        parser = _SearchPageParser()
        parser.feed(self._make_html([
            {"gid": "1", "url": "/game/x/", "title": "Катан", "price_rub": 3490},
        ]))
        self.assertEqual(parser.products[0].price, 349000)

    def test_skips_cards_without_price(self) -> None:
        from parsers.stores.gaga import _SearchPageParser

        html = """<html><body>
        <div class="preview-card">
            <p class="preview-card__title"><a href="/game/x/" title="Без цены">Без цены</a></p>
            <button class="btn btn--basket add_to_cart" data-gid="99">В корзину</button>
        </div>
        </body></html>"""
        parser = _SearchPageParser()
        parser.feed(html)
        self.assertEqual(len(parser.products), 0)

    def test_skips_cards_without_buy_button(self) -> None:
        from parsers.stores.gaga import _SearchPageParser

        html = """<html><body>
        <div class="preview-card">
            <p class="preview-card__title"><a href="/game/y/" title="Игра">Игра</a></p>
            <span itemprop="price">1000</span>
        </div>
        </body></html>"""
        parser = _SearchPageParser()
        parser.feed(html)
        self.assertEqual(len(parser.products), 0)


class TestGagaEnrich(unittest.IsolatedAsyncioTestCase):
    """Тесты _enrich GaGa.ru на статичном HTML страницы товара."""

    _DETAIL_HTML = """
    <html>
    <head>
        <meta property="og:image" content="https://gaga.ru/gaga/files/images/fullsize/4814/1.jpg">
    </head>
    <body>
        <div class="hreview-aggregate">
            <span itemprop="ratingValue">4.8</span>
            <span itemprop="reviewCount">12</span>
        </div>
        <div class="card-features__ranking">
            <a href="/rating/#game4814">3 место</a>
        </div>
        <ul class="card-features__list">
            <li>правила средние</li>
            <li>2-5<br> игроков</li>
            <li>от 8&thinsp;лет</li>
            <li>0.5 - 1.5 ч.</li>
        </ul>
        <div class="offline-price">
            <span class="offline-price__value">2340 руб.</span>
        </div>
        <a href="/gaga/files/pdf/rules/ru/4814.pdf">Правила на русском</a>
        <img src="/gaga/files/images/fullsize/4814/1.jpg">
        <img src="/gaga/files/images/fullsize/4814/2.jpg">
        <p>Размеры: Высота х Ширина х Глубина:27.7см x 19.4см x 6.7см</p>
        <p>Вес: 900 гр.</p>
        <p>Состав: 72 квадрата местности • 40 фишек подданных</p>
        <div class="game-description">Классика евростратегий для всей семьи.</div>
    </body>
    </html>
    """

    async def test_enrich_extracts_all_fields(self) -> None:
        from parsers.stores.gaga import GagaParser

        parser = GagaParser()
        product = ParsedProduct(
            store_slug="gaga", external_id="4814",
            title="Каркассон. Средневековье", price=199000,
            url="https://gaga.ru/game/carcassonne/",
        )

        class FakeResp:
            is_success = True
            text = self._DETAIL_HTML

        class FakeClient:
            async def get(self, url):
                return FakeResp()

        extra = await parser._enrich(FakeClient(), product)

        self.assertEqual(extra.get("players"), "2-5")
        self.assertEqual(extra.get("age_min"), 8)
        self.assertEqual(extra.get("playtime"), "0.5 - 1.5 ч.")
        self.assertIn("rules_url", extra)
        raw = extra.get("raw", {})
        self.assertEqual(raw.get("rating"), "4.8")
        self.assertEqual(raw.get("review_count"), "12")
        self.assertEqual(raw.get("ranking"), "3 место")
        self.assertEqual(raw.get("offline_price"), 234000)  # 2340 руб → копейки
        self.assertGreater(len(raw.get("gallery", [])), 0)
        self.assertIn("dimensions", raw)
        self.assertIn("composition", raw)
        self.assertEqual(extra.get("description"), "Классика евростратегий для всей семьи.")


if __name__ == "__main__":
    unittest.main()
