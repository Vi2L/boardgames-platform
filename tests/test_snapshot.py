"""Тесты SnapshotRecorder и API snapshot'ов (этап 7)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from parsers.base import SnapshotRecorder
from parsers.db import PriceDatabase


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class _DBTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = PriceDatabase(Path(self._tmp.name) / "test.sqlite")
        await self.db.init()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()


class TestSaveSnapshot(_DBTestBase):

    async def test_persists_body_with_encoding(self) -> None:
        body = "<html>тест</html>".encode("utf-8")
        sid = await self.db.save_snapshot(
            store_slug="hobbygames", query="каркассон",
            url="https://example.com/search?q=karkassone", method="GET",
            status_code=200, encoding="utf-8",
            content_type="text/html; charset=utf-8",
            body=body, duration_ms=120,
            ts=_iso(datetime.now(timezone.utc)), kind="search",
        )
        snap = await self.db.get_snapshot(sid)
        self.assertEqual(snap["status_code"], 200)
        self.assertEqual(snap["body_size"], len(body))
        self.assertIn("тест", snap["body_text"])

    async def test_cp1251_decoded_correctly(self) -> None:
        # GaGa отдаёт cp1251 — body хранится как сырые байты, но при выдаче
        # декодируется по encoding в UTF-8 текст.
        text = "Каркассон"
        body = text.encode("cp1251")
        sid = await self.db.save_snapshot(
            store_slug="gaga", query=text,
            url="https://gaga.ru/search/?word=...", method="GET",
            status_code=200, encoding="windows-1251",
            content_type="text/html; charset=windows-1251",
            body=body, duration_ms=200,
            ts=_iso(datetime.now(timezone.utc)), kind="search",
        )
        snap = await self.db.get_snapshot(sid)
        self.assertIn("Каркассон", snap["body_text"])

    async def test_truncates_large_body(self) -> None:
        big = b"x" * (PriceDatabase._SNAPSHOT_BODY_LIMIT + 100)
        sid = await self.db.save_snapshot(
            store_slug="x", query=None, url="u", method="GET",
            status_code=200, encoding="utf-8", content_type="text/html",
            body=big, duration_ms=10,
            ts=_iso(datetime.now(timezone.utc)), kind="search",
        )
        snap = await self.db.get_snapshot(sid)
        self.assertEqual(snap["truncated"], 1)
        self.assertEqual(snap["body_size"], len(big))  # body_size — оригинальный
        # body_text получен из обрезанных байтов
        self.assertEqual(len(snap["body_text"]), PriceDatabase._SNAPSHOT_BODY_LIMIT)


class TestListAndPrune(_DBTestBase):

    async def test_filters_by_store_and_query(self) -> None:
        ts = _iso(datetime.now(timezone.utc))
        for slug, q in [("hobbygames", "Каркассон"), ("gaga", "Катан"), ("hobbygames", "Катан")]:
            await self.db.save_snapshot(
                store_slug=slug, query=q, url="u", method="GET",
                status_code=200, encoding="utf-8", content_type="text/html",
                body=b"x", duration_ms=10, ts=ts, kind="search",
            )
        only_hg = await self.db.list_snapshots(store_slug="hobbygames")
        self.assertEqual(len(only_hg), 2)
        only_kart = await self.db.list_snapshots(query="Каркассон")
        self.assertEqual(len(only_kart), 1)

    async def test_delete_and_prune(self) -> None:
        ts = _iso(datetime.now(timezone.utc))
        sid = await self.db.save_snapshot(
            store_slug="x", query=None, url="u", method="GET",
            status_code=200, encoding="utf-8", content_type="text/html",
            body=b"x", duration_ms=10, ts=ts, kind="search",
        )
        self.assertTrue(await self.db.delete_snapshot(sid))
        self.assertFalse(await self.db.delete_snapshot(sid))  # повторно


class TestSnapshotRecorder(unittest.TestCase):
    """Юнит-тест: SnapshotRecorder включается только при ENABLE_RAW_SNAPSHOTS=1."""

    def test_disabled_by_default(self):
        rec = SnapshotRecorder("x", "q", db=object())
        self.assertFalse(rec.enabled)
        # event_hooks пуст по сравнению с тем что подаётся
        merged = rec.merged_hooks({"request": [lambda r: None]})
        # response пустой, request — только тот что подали
        self.assertNotIn("response", merged)
        self.assertEqual(len(merged["request"]), 1)

    def test_enabled_with_flag_and_db(self):
        with patch.dict(os.environ, {"ENABLE_RAW_SNAPSHOTS": "1"}):
            rec = SnapshotRecorder("x", "q", db=object())
            self.assertTrue(rec.enabled)
            merged = rec.merged_hooks({"request": [lambda r: None]})
            self.assertEqual(len(merged["response"]), 1)

    def test_disabled_when_no_db_even_with_flag(self):
        """Без _db не может писать в БД — recorder выключен."""
        with patch.dict(os.environ, {"ENABLE_RAW_SNAPSHOTS": "1"}):
            rec = SnapshotRecorder("x", "q", db=None)
            self.assertFalse(rec.enabled)


if __name__ == "__main__":
    unittest.main()
