"""Тесты аналитических методов PriceDatabase (этап 1 расширения dashboard).

Все тесты используют изолированную SQLite-базу во временной директории.
Сетевых вызовов и реальных парсеров нет — наполняем request_log и parser_log
напрямую через log_request/log_parser.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from parsers.db import PriceDatabase


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class _DBTestBase(unittest.IsolatedAsyncioTestCase):
    """Создаёт временную БД на каждый тест и инициализирует схему."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = PriceDatabase(Path(self._tmp.name) / "test.sqlite")
        await self.db.init()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()


class TestTopQueries(_DBTestBase):

    async def test_returns_empty_when_no_logs(self) -> None:
        result = await self.db.get_top_queries(hours=24, limit=10)
        self.assertEqual(result, [])

    async def test_groups_by_query_and_orders_by_count(self) -> None:
        now = datetime.now(timezone.utc)
        # 3 запроса "Каркассон", 2 запроса "Катан", 1 — "Манчкин"
        for q, n in [("Каркассон", 3), ("Катан", 2), ("Манчкин", 1)]:
            for i in range(n):
                await self.db.log_request(
                    query=q, source="cache" if i % 2 == 0 else "network",
                    result_count=5, error_count=0, duration_ms=100 + i * 10,
                    errors={}, ts=_iso(now - timedelta(minutes=i)),
                )

        result = await self.db.get_top_queries(hours=24, limit=10)
        self.assertEqual([r["query"] for r in result], ["Каркассон", "Катан", "Манчкин"])
        self.assertEqual(result[0]["count"], 3)
        self.assertEqual(result[1]["count"], 2)
        self.assertEqual(result[2]["count"], 1)

    async def test_cache_hit_rate_calculation(self) -> None:
        now = datetime.now(timezone.utc)
        # 4 запроса: 3 cache, 1 network → 75%
        for src in ["cache", "cache", "cache", "network"]:
            await self.db.log_request(
                query="Каркассон", source=src, result_count=2, error_count=0,
                duration_ms=200, errors={}, ts=_iso(now),
            )
        result = await self.db.get_top_queries(hours=24, limit=10)
        self.assertEqual(result[0]["cache_hit_rate"], 75.0)

    async def test_respects_hours_window(self) -> None:
        now = datetime.now(timezone.utc)
        await self.db.log_request(
            query="Каркассон", source="cache", result_count=1, error_count=0,
            duration_ms=100, errors={}, ts=_iso(now - timedelta(hours=48)),
        )
        # Окно 24ч не должно захватывать запрос 48ч назад
        result = await self.db.get_top_queries(hours=24, limit=10)
        self.assertEqual(result, [])


class TestLatencyPercentiles(_DBTestBase):

    async def test_returns_nulls_for_empty_log(self) -> None:
        result = await self.db.get_latency_percentiles(hours=24)
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["p50"])
        self.assertIsNone(result["p95"])
        self.assertIsNone(result["p99"])

    async def test_single_value(self) -> None:
        now = datetime.now(timezone.utc)
        await self.db.log_request(
            query="x", source="network", result_count=1, error_count=0,
            duration_ms=500, errors={}, ts=_iso(now),
        )
        result = await self.db.get_latency_percentiles(hours=24)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["p50"], 500)
        self.assertEqual(result["p95"], 500)
        self.assertEqual(result["p99"], 500)
        self.assertEqual(result["max"], 500)
        self.assertEqual(result["avg"], 500)

    async def test_percentiles_on_100_values(self) -> None:
        """100 значений 1..100. p50≈50, p95≈95, p99≈99, max=100."""
        now = datetime.now(timezone.utc)
        for i in range(1, 101):
            await self.db.log_request(
                query="x", source="network", result_count=1, error_count=0,
                duration_ms=i, errors={}, ts=_iso(now),
            )
        r = await self.db.get_latency_percentiles(hours=24)
        self.assertEqual(r["count"], 100)
        # nearest-rank: index = max(0, min(n-1, int(p*n) - 1)). durations отсортированы 1..100,
        # т.е. durations[i] == i+1.
        self.assertEqual(r["p50"], 50)  # int(0.50*100)-1 = 49 → durations[49] = 50
        self.assertEqual(r["p95"], 95)  # int(0.95*100)-1 = 94 → durations[94] = 95
        self.assertEqual(r["p99"], 99)  # int(0.99*100)-1 = 98 → durations[98] = 99
        self.assertEqual(r["max"], 100)
        self.assertGreaterEqual(r["avg"], 50)


class TestRequestsTimeline(_DBTestBase):

    async def test_buckets_by_hour(self) -> None:
        now = datetime.now(timezone.utc).replace(minute=15, second=0, microsecond=0)
        # 3 запроса в один час, 2 в другой
        for _ in range(3):
            await self.db.log_request(
                query="x", source="cache", result_count=1, error_count=0,
                duration_ms=100, errors={}, ts=_iso(now),
            )
        for _ in range(2):
            await self.db.log_request(
                query="x", source="network", result_count=1, error_count=0,
                duration_ms=200, errors={}, ts=_iso(now - timedelta(hours=1)),
            )
        result = await self.db.get_requests_timeline(hours=24, bucket="hour")
        self.assertEqual(len(result), 2)
        # Сортировка по ts_bucket asc
        self.assertEqual(result[0]["total"], 2)
        self.assertEqual(result[0]["network"], 2)
        self.assertEqual(result[1]["total"], 3)
        self.assertEqual(result[1]["cache"], 3)

    async def test_invalid_bucket_raises(self) -> None:
        with self.assertRaises(ValueError):
            await self.db.get_requests_timeline(bucket="weekly")


class TestStoreDistribution(_DBTestBase):

    async def test_share_pct_sums_to_100(self) -> None:
        now = datetime.now(timezone.utc)
        # 6 hobbygames + 4 gaga + 2 lavkaigr → 50/33.3/16.7
        for _ in range(6):
            await self.db.log_parser(
                store_slug="hobbygames", success=True, result_count=3,
                duration_ms=300, error_msg=None, ts=_iso(now),
            )
        for _ in range(4):
            await self.db.log_parser(
                store_slug="gaga", success=True, result_count=2,
                duration_ms=400, error_msg=None, ts=_iso(now),
            )
        for _ in range(2):
            await self.db.log_parser(
                store_slug="lavkaigr", success=False, result_count=0,
                duration_ms=500, error_msg="boom", ts=_iso(now),
            )
        result = await self.db.get_store_distribution(hours=24)
        slugs = {r["store_slug"]: r for r in result}
        self.assertEqual(slugs["hobbygames"]["calls"], 6)
        self.assertEqual(slugs["hobbygames"]["share_pct"], 50.0)
        self.assertEqual(slugs["gaga"]["share_pct"], 33.3)
        self.assertEqual(slugs["lavkaigr"]["share_pct"], 16.7)
        self.assertEqual(slugs["lavkaigr"]["success_rate"], 0)


class TestEmptyResponses(_DBTestBase):

    async def test_lists_only_success_with_zero_results(self) -> None:
        now = datetime.now(timezone.utc)
        # Только этот должен попасть
        await self.db.log_parser(
            store_slug="hobbygames", success=True, result_count=0,
            duration_ms=300, error_msg=None, ts=_iso(now),
        )
        # Не должны попасть: success=False (это ошибка), result_count>0
        await self.db.log_parser(
            store_slug="gaga", success=False, result_count=0,
            duration_ms=400, error_msg="net", ts=_iso(now),
        )
        await self.db.log_parser(
            store_slug="lavkaigr", success=True, result_count=5,
            duration_ms=500, error_msg=None, ts=_iso(now),
        )
        result = await self.db.get_empty_responses(hours=24, limit=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["store_slug"], "hobbygames")


class TestCacheRateTimeline(_DBTestBase):

    async def test_computes_rate_per_bucket(self) -> None:
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        # 4 cache, 1 network в одном часе → 80%
        for _ in range(4):
            await self.db.log_request(
                query="x", source="cache", result_count=1, error_count=0,
                duration_ms=100, errors={}, ts=_iso(now),
            )
        await self.db.log_request(
            query="x", source="network", result_count=1, error_count=0,
            duration_ms=200, errors={}, ts=_iso(now),
        )
        result = await self.db.get_cache_rate_timeline(hours=24, bucket="hour")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["total"], 5)
        self.assertEqual(result[0]["cache_hit_rate"], 80.0)


if __name__ == "__main__":
    unittest.main()
