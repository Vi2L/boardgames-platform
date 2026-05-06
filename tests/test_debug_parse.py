"""Тесты Live Test endpoint /api/debug/parse (этап 8).

Проверяем главное инвариантное свойство: Live Test НЕ загрязняет
production-данные — products, price_observations и request_log
остаются нетронутыми, а в parser_log запись попадает с is_test=1
и игнорируется аналитикой.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from parsers.base import StoreParser
from parsers.db import PriceDatabase
from parsers.models import ParsedProduct, StoreInfo


MOCK_STORE = StoreInfo(slug="mock", name="Mock", base_url="https://mock.example.com")


class _MockParser(StoreParser):
    store = MOCK_STORE

    def __init__(self, products=None, fail=False) -> None:
        super().__init__()
        self._products = products or [
            ParsedProduct(
                store_slug="mock", external_id="1", title="Каркассон",
                price=199_000, url="/p/1", players="2-5",
            ),
        ]
        self._fail = fail

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        if self._fail:
            raise RuntimeError("Mocked failure")
        return [p for p in self._products if query.lower() in p.title.lower()][:limit]


class TestDebugParseInvariants(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.sqlite"

        # Подменяем глобальные _db и _service в parsers.api на свои
        import parsers.api as api_mod
        from parsers.service import PriceService

        self.db = PriceDatabase(self.db_path)
        await self.db.init()
        await self.db.upsert_store(MOCK_STORE)

        self.parser = _MockParser()
        self.service = PriceService(self.db, [self.parser], cache_ttl_hours=4)

        api_mod._db = self.db
        api_mod._service = self.service
        from parsers import stats_api
        stats_api.set_db(self.db)

        # FastAPI lifespan не выполнится для тестового клиента — так что
        # просто используем app с уже подменёнными глобалами
        self.client = TestClient(api_mod.app)

    async def asyncTearDown(self) -> None:
        self.client.close()
        self._tmp.cleanup()

    async def _wait_for_log_writes(self):
        """log_parser в /api/debug/parse выполняется через create_task."""
        await asyncio.sleep(0.1)

    async def test_does_not_persist_products(self) -> None:
        meta_before = await self.db.get_db_metadata()
        before = meta_before["tables"]["products"]

        resp = self.client.get("/api/debug/parse?q=Каркассон&stores=mock")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["results"]["mock"]["count"], 1)

        meta_after = await self.db.get_db_metadata()
        self.assertEqual(meta_after["tables"]["products"], before,
                         "Live Test не должен сохранять товары в products")
        self.assertEqual(meta_after["tables"]["price_observations"],
                         meta_before["tables"]["price_observations"])

    async def test_does_not_write_request_log(self) -> None:
        meta_before = await self.db.get_db_metadata()
        self.client.get("/api/debug/parse?q=Каркассон&stores=mock")
        meta_after = await self.db.get_db_metadata()
        self.assertEqual(meta_after["tables"]["request_log"], meta_before["tables"]["request_log"])

    async def test_writes_parser_log_with_is_test_flag(self) -> None:
        self.client.get("/api/debug/parse?q=Каркассон&stores=mock")
        await self._wait_for_log_writes()

        # Аналитика игнорирует is_test=1
        breakdown = await self.db.get_parser_breakdown(hours=24)
        self.assertEqual(breakdown, [])  # как будто запуска не было

        # Но запись в parser_log есть — для будущей debug-аналитики при необходимости
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT store_slug, is_test, success FROM parser_log WHERE is_test = 1"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "mock")
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], 1)

    async def test_returns_full_product_with_both_price_formats(self) -> None:
        resp = self.client.get("/api/debug/parse?q=Каркассон&stores=mock")
        prod = resp.json()["results"]["mock"]["products"][0]
        # И копейки, и рубли — для удобства отладки
        self.assertEqual(prod["price"], 199_000)
        self.assertEqual(prod["price_rub"], 1990.0)
        self.assertEqual(prod["players"], "2-5")

    async def test_handles_parser_failure(self) -> None:
        self.parser._fail = True
        resp = self.client.get("/api/debug/parse?q=Каркассон&stores=mock")
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["results"]["mock"]
        self.assertEqual(result["count"], 0)
        self.assertIn("Mocked failure", result["error"])


if __name__ == "__main__":
    unittest.main()
