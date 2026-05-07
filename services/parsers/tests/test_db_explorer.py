"""Тесты Database Explorer (этап 4 расширения dashboard)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parsers.db import PriceDatabase
from parsers.models import ParsedProduct, StoreInfo


class _DBTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = PriceDatabase(Path(self._tmp.name) / "test.sqlite")
        await self.db.init()
        # Регистрируем магазины (FK products.store_slug → stores.slug)
        for slug in ("hobbygames", "gaga"):
            await self.db.upsert_store(StoreInfo(slug=slug, name=slug, base_url="https://example.com"))

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    def _make_product(self, store: str, ext: str, title: str, price: int, **kw) -> ParsedProduct:
        return ParsedProduct(
            store_slug=store, external_id=ext, title=title, price=price,
            url=f"/p/{ext}", **kw,
        )


class TestDbMetadata(_DBTestBase):

    async def test_counts_zero_on_fresh_db(self) -> None:
        meta = await self.db.get_db_metadata()
        self.assertEqual(meta["tables"]["stores"], 2)  # 2 store seeded
        self.assertEqual(meta["tables"]["products"], 0)
        self.assertEqual(meta["tables"]["price_observations"], 0)
        self.assertGreaterEqual(meta["db_size_bytes"], 0)

    async def test_counts_after_insert(self) -> None:
        await self.db.upsert_product(self._make_product("hobbygames", "1", "Каркассон", 199000))
        await self.db.upsert_product(self._make_product("gaga", "2", "Катан", 299000))
        meta = await self.db.get_db_metadata()
        self.assertEqual(meta["tables"]["products"], 2)
        self.assertEqual(meta["tables"]["price_observations"], 2)
        self.assertIsNotNone(meta["oldest_observation"])
        self.assertIsNotNone(meta["newest_observation"])


class TestStoreInventory(_DBTestBase):

    async def test_aggregates_per_store(self) -> None:
        for i, price in enumerate([100_00, 200_00, 300_00]):
            await self.db.upsert_product(self._make_product("hobbygames", f"hg-{i}", f"Игра {i}", price))
        await self.db.upsert_product(self._make_product("gaga", "g-1", "Game", 500_00))

        result = await self.db.get_store_inventory()
        slugs = {r["store_slug"]: r for r in result}
        self.assertEqual(slugs["hobbygames"]["products_count"], 3)
        self.assertEqual(slugs["hobbygames"]["min_price_rub"], 100.0)
        self.assertEqual(slugs["hobbygames"]["max_price_rub"], 300.0)
        self.assertEqual(slugs["hobbygames"]["mean_price_rub"], 200.0)
        self.assertEqual(slugs["gaga"]["products_count"], 1)
        self.assertEqual(slugs["gaga"]["min_price_rub"], 500.0)


class TestListProducts(_DBTestBase):

    async def test_pagination_total(self) -> None:
        for i in range(15):
            await self.db.upsert_product(
                self._make_product("hobbygames", f"id-{i}", f"Game {i}", (i + 1) * 10000),
            )
        page1, total = await self.db.list_products(limit=10, offset=0)
        page2, _ = await self.db.list_products(limit=10, offset=10)
        self.assertEqual(total, 15)
        self.assertEqual(len(page1), 10)
        self.assertEqual(len(page2), 5)

    async def test_filter_by_store(self) -> None:
        await self.db.upsert_product(self._make_product("hobbygames", "h", "Каркассон", 100_00))
        await self.db.upsert_product(self._make_product("gaga", "g", "Каркассон", 200_00))
        items, total = await self.db.list_products(store="gaga")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["store_slug"], "gaga")

    async def test_search_by_query(self) -> None:
        await self.db.upsert_product(self._make_product("hobbygames", "k", "Каркассон Базовая", 100_00))
        await self.db.upsert_product(self._make_product("hobbygames", "c", "Катан", 200_00))
        items, total = await self.db.list_products(query="каркассон")
        self.assertEqual(total, 1)
        self.assertIn("Каркассон", items[0]["title"])

    async def test_sort_price_asc(self) -> None:
        await self.db.upsert_product(self._make_product("hobbygames", "1", "A", 300_00))
        await self.db.upsert_product(self._make_product("hobbygames", "2", "B", 100_00))
        await self.db.upsert_product(self._make_product("hobbygames", "3", "C", 200_00))
        items, _ = await self.db.list_products(sort="price_asc")
        prices = [it["price_rub"] for it in items]
        self.assertEqual(prices, [100.0, 200.0, 300.0])


class TestProductFull(_DBTestBase):

    async def test_returns_none_for_missing(self) -> None:
        self.assertIsNone(await self.db.get_product_full(99999))

    async def test_includes_history(self) -> None:
        # Несколько upsert'ов = несколько price_observations
        for price in [100_00, 110_00, 120_00]:
            await self.db.upsert_product(
                self._make_product("hobbygames", "x", "Game", price,
                                   description="desc", players="2-4"),
            )
        # Найти id товара
        items, _ = await self.db.list_products()
        pid = items[0]["id"]
        full = await self.db.get_product_full(pid)
        self.assertEqual(full["title"], "Game")
        self.assertEqual(full["description"], "desc")
        self.assertEqual(len(full["history"]), 3)
        # История отсортирована по убыванию даты
        self.assertEqual(full["history"][0]["price_rub"], 120.0)
        self.assertEqual(full["history"][-1]["price_rub"], 100.0)


class TestPriceDistribution(_DBTestBase):

    async def test_empty_returns_nones(self) -> None:
        d = await self.db.get_price_distribution()
        self.assertEqual(d["count"], 0)
        self.assertIsNone(d["p50"])

    async def test_quartiles_on_100_values(self) -> None:
        for i in range(1, 101):
            await self.db.upsert_product(
                self._make_product("hobbygames", f"id-{i}", f"G {i}", i * 100),  # 1..100 руб
            )
        d = await self.db.get_price_distribution()
        self.assertEqual(d["count"], 100)
        # nearest-rank: idx = int(p*n)-1
        self.assertEqual(d["min"], 1.0)
        self.assertEqual(d["p25"], 25.0)
        self.assertEqual(d["p50"], 50.0)
        self.assertEqual(d["p75"], 75.0)
        self.assertEqual(d["max"], 100.0)

    async def test_filter_by_store(self) -> None:
        await self.db.upsert_product(self._make_product("hobbygames", "1", "A", 100_00))
        await self.db.upsert_product(self._make_product("gaga", "2", "B", 500_00))
        d = await self.db.get_price_distribution(store_slug="gaga")
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["min"], 500.0)


if __name__ == "__main__":
    unittest.main()
