"""Тесты ParserMetrics, миграции parser_log и breakdown-аналитики (этап 6)."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from parsers.base import ParserMetrics, StoreParser
from parsers.db import PriceDatabase
from parsers.models import ParsedProduct, StoreInfo
from parsers.service import PriceService


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class TestMigration(unittest.IsolatedAsyncioTestCase):

    async def test_adds_search_ms_column_to_existing_db(self) -> None:
        """Старая БД без новых колонок должна получить их при db.init()."""
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "old.sqlite"
        # Создаём parser_log в старой схеме (без search_ms etc.)
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE parser_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    store_slug TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    result_count INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER,
                    error_msg TEXT,
                    ts TEXT NOT NULL
                );
                INSERT INTO parser_log (store_slug, success, result_count, duration_ms, ts)
                VALUES ('hobbygames', 1, 5, 300, '2026-01-01T00:00:00');
            """)

        db = PriceDatabase(path)
        await db.init()

        # Колонки должны быть добавлены
        with sqlite3.connect(path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(parser_log)").fetchall()]
        for new_col in ("search_ms", "enrich_ms", "http_requests", "result_after_enrich"):
            self.assertIn(new_col, cols)

        # Старая запись жива и читается с NULL в новых колонках
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT search_ms, enrich_ms FROM parser_log WHERE id=1").fetchone()
        self.assertEqual(row, (None, None))

        tmp.cleanup()


class _DBTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = PriceDatabase(Path(self._tmp.name) / "test.sqlite")
        await self.db.init()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()


class TestLogParserExtended(_DBTestBase):

    async def test_persists_search_and_enrich_ms(self) -> None:
        await self.db.log_parser(
            store_slug="hobbygames", success=True, result_count=5,
            duration_ms=2200, error_msg=None,
            ts=_iso(datetime.now(timezone.utc)),
            search_ms=300, enrich_ms=1900, http_requests=11, result_after_enrich=5,
        )
        breakdown = await self.db.get_parser_breakdown(hours=24)
        self.assertEqual(len(breakdown), 1)
        b = breakdown[0]
        self.assertEqual(b["avg_search_ms"], 300)
        self.assertEqual(b["avg_enrich_ms"], 1900)
        self.assertEqual(b["avg_http_requests"], 11.0)

    async def test_breakdown_skips_failed_calls_in_avg(self) -> None:
        ts = _iso(datetime.now(timezone.utc))
        # Один success с метриками
        await self.db.log_parser(
            store_slug="gaga", success=True, result_count=3,
            duration_ms=500, error_msg=None, ts=ts,
            search_ms=100, enrich_ms=400, http_requests=4, result_after_enrich=3,
        )
        # Один fail без метрик — должен быть посчитан в calls, но не в avg
        await self.db.log_parser(
            store_slug="gaga", success=False, result_count=0,
            duration_ms=2000, error_msg="boom", ts=ts,
        )
        b = (await self.db.get_parser_breakdown(hours=24))[0]
        self.assertEqual(b["calls"], 2)
        self.assertEqual(b["successes"], 1)
        self.assertEqual(b["avg_search_ms"], 100)  # только success
        self.assertEqual(b["avg_enrich_ms"], 400)


# ---------------------------------------------------------------------------
# Mock-парсер для проверки интеграции metrics в PriceService
# ---------------------------------------------------------------------------

MOCK_STORE = StoreInfo(slug="mock", name="Mock", base_url="https://mock.example.com")


class MetricsAwareParser(StoreParser):
    store = MOCK_STORE

    def __init__(self, search_ms: int, enrich_ms: int, http: int) -> None:
        super().__init__()
        self._search_ms = search_ms
        self._enrich_ms = enrich_ms
        self._http = http

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        # Фейковый замер: просто проставляем метрики
        self.last_metrics = ParserMetrics(
            search_ms=self._search_ms,
            enrich_ms=self._enrich_ms,
            http_requests=self._http,
            result_after_enrich=2,
        )
        return [
            ParsedProduct(store_slug="mock", external_id="1", title="A", price=100, url="/a"),
            ParsedProduct(store_slug="mock", external_id="2", title="B", price=200, url="/b"),
        ]


class TestServicePersistsMetrics(_DBTestBase):

    async def test_service_writes_parser_metrics(self) -> None:
        await self.db.upsert_store(MOCK_STORE)
        parser = MetricsAwareParser(search_ms=120, enrich_ms=500, http=4)
        service = PriceService(self.db, [parser], cache_ttl_hours=4)

        await service.search("A", limit=5)
        # log_parser выполняется как create_task — даём ему завершиться
        import asyncio
        await asyncio.sleep(0.05)

        breakdown = await self.db.get_parser_breakdown(hours=24)
        self.assertEqual(len(breakdown), 1)
        self.assertEqual(breakdown[0]["avg_search_ms"], 120)
        self.assertEqual(breakdown[0]["avg_enrich_ms"], 500)
        self.assertEqual(breakdown[0]["avg_http_requests"], 4.0)


if __name__ == "__main__":
    unittest.main()
