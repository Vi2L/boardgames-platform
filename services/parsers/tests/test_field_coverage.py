"""Тесты Data Quality — покрытие полей и raw keys (этап 5)."""

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
        for slug in ("hobbygames", "gaga"):
            await self.db.upsert_store(StoreInfo(slug=slug, name=slug, base_url="https://example.com"))

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()


class TestFieldCoverage(_DBTestBase):

    async def test_full_coverage_when_all_fields_set(self) -> None:
        for i in range(5):
            await self.db.upsert_product(ParsedProduct(
                store_slug="hobbygames", external_id=f"id-{i}", title=f"Game {i}",
                price=10000, url=f"/p/{i}",
                image_url="https://...", image_url_hd="https://...",
                description="desc", players="2-4", age_min=8, playtime="30 min",
                rules_url="https://.../rules.pdf",
            ))
        result = await self.db.get_field_coverage()
        cov = result[0]["coverage"]
        for field in ("description", "image_url", "image_url_hd", "players",
                      "age_min", "playtime", "rules_url"):
            self.assertEqual(cov[field], 100.0, f"field {field} should be 100%")

    async def test_partial_coverage_per_store(self) -> None:
        # 2 hobbygames с description, 0 без; players не у одного из 2
        await self.db.upsert_product(ParsedProduct(
            store_slug="hobbygames", external_id="1", title="A", price=100, url="/a",
            description="d1", players="2",
        ))
        await self.db.upsert_product(ParsedProduct(
            store_slug="hobbygames", external_id="2", title="B", price=200, url="/b",
            description="d2",  # players=None
        ))
        # 1 gaga — все поля null, кроме обязательных
        await self.db.upsert_product(ParsedProduct(
            store_slug="gaga", external_id="3", title="C", price=300, url="/c",
        ))

        result = await self.db.get_field_coverage()
        slugs = {r["store_slug"]: r for r in result}
        # hobbygames: 2 продукта, оба с description → 100%, players только 1 → 50%
        self.assertEqual(slugs["hobbygames"]["coverage"]["description"], 100.0)
        self.assertEqual(slugs["hobbygames"]["coverage"]["players"], 50.0)
        # gaga: 1 продукт без полей → 0%
        self.assertEqual(slugs["gaga"]["coverage"]["description"], 0.0)
        self.assertEqual(slugs["gaga"]["coverage"]["players"], 0.0)


class TestRawKeysDistribution(_DBTestBase):

    async def test_returns_keys_per_store(self) -> None:
        await self.db.upsert_product(ParsedProduct(
            store_slug="hobbygames", external_id="1", title="A", price=100, url="/a",
            raw={"gallery": ["a"], "rating": "4.8", "tags": ["family"]},
        ))
        await self.db.upsert_product(ParsedProduct(
            store_slug="gaga", external_id="2", title="B", price=200, url="/b",
            raw={"complexity": "easy", "review_count": 12},
        ))
        result = await self.db.get_raw_keys_distribution(top_n=10)
        slugs = {r["store_slug"]: r for r in result}
        hg_keys = {k["key"] for k in slugs["hobbygames"]["keys"]}
        ga_keys = {k["key"] for k in slugs["gaga"]["keys"]}
        self.assertEqual(hg_keys, {"gallery", "rating", "tags"})
        self.assertEqual(ga_keys, {"complexity", "review_count"})

    async def test_picks_only_latest_observation(self) -> None:
        # Первое наблюдение с одним набором, второе — с другим. raw для top_keys
        # должен браться из самого свежего.
        await self.db.upsert_product(ParsedProduct(
            store_slug="hobbygames", external_id="1", title="A", price=100, url="/a",
            raw={"old_key": "x"},
        ))
        await self.db.upsert_product(ParsedProduct(
            store_slug="hobbygames", external_id="1", title="A", price=110, url="/a",
            raw={"new_key": "y"},
        ))
        result = await self.db.get_raw_keys_distribution(top_n=10)
        keys = {k["key"] for k in result[0]["keys"]}
        self.assertEqual(keys, {"new_key"})


if __name__ == "__main__":
    unittest.main()
