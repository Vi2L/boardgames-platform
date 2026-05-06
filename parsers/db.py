from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from .models import ParsedProduct, PricePoint, ProductRecord, StoreInfo

_DDL = """
CREATE TABLE IF NOT EXISTS stores (
    slug     TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    base_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    store_slug       TEXT NOT NULL REFERENCES stores(slug),
    external_id      TEXT NOT NULL,
    title            TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    url              TEXT NOT NULL,
    image_url        TEXT,
    image_url_hd     TEXT,
    description      TEXT,
    players          TEXT,
    age_min          INTEGER,
    playtime         TEXT,
    rules_url        TEXT,
    UNIQUE (store_slug, external_id)
);

CREATE INDEX IF NOT EXISTS idx_products_normalized_title ON products (normalized_title);

CREATE TABLE IF NOT EXISTS price_observations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    price      INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_obs_product ON price_observations (product_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS request_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    error_count  INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER,
    errors_json  TEXT    NOT NULL DEFAULT '{}',
    ts           TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_log_ts ON request_log (ts DESC);

CREATE TABLE IF NOT EXISTS parser_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    store_slug   TEXT    NOT NULL,
    success      INTEGER NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER,
    error_msg    TEXT,
    ts           TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parser_log_ts ON parser_log (store_slug, ts DESC);
"""

# Колонки добавлены после начального деплоя — применяем как миграцию
_MIGRATIONS = [
    "ALTER TABLE products ADD COLUMN image_url_hd TEXT",
    "ALTER TABLE products ADD COLUMN description TEXT",
    "ALTER TABLE products ADD COLUMN players TEXT",
    "ALTER TABLE products ADD COLUMN age_min INTEGER",
    "ALTER TABLE products ADD COLUMN playtime TEXT",
    "ALTER TABLE products ADD COLUMN rules_url TEXT",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PriceDatabase:
    def __init__(self, path: str | Path = "data/prices.sqlite") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        """Создать таблицы и применить миграции при первом запуске."""
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_DDL)
            for stmt in _MIGRATIONS:
                try:
                    await db.execute(stmt)
                except Exception:
                    pass  # колонка уже существует
            await db.commit()

    # ------------------------------------------------------------------
    # Магазины
    # ------------------------------------------------------------------

    async def upsert_store(self, store: StoreInfo) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO stores (slug, name, base_url)
                VALUES (?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET name=excluded.name, base_url=excluded.base_url
                """,
                (store.slug, store.name, store.base_url),
            )
            await db.commit()

    async def list_stores(self) -> list[StoreInfo]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT slug, name, base_url FROM stores") as cur:
                rows = await cur.fetchall()
        return [StoreInfo(r["slug"], r["name"], r["base_url"]) for r in rows]

    # ------------------------------------------------------------------
    # Сохранение товара + наблюдения цены
    # ------------------------------------------------------------------

    async def upsert_product(self, p: ParsedProduct) -> None:
        """Сохранить товар и зафиксировать наблюдение цены.

        Если товар уже есть (store_slug, external_id) — обновляем все поля,
        затем добавляем строку в price_observations (история не затирается).
        """
        now_iso = _utcnow().isoformat()
        normalized = p.title.lower()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO products
                    (store_slug, external_id, title, normalized_title, url,
                     image_url, image_url_hd, description, players, age_min,
                     playtime, rules_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(store_slug, external_id) DO UPDATE SET
                    title=excluded.title,
                    normalized_title=excluded.normalized_title,
                    url=excluded.url,
                    image_url=excluded.image_url,
                    image_url_hd=COALESCE(excluded.image_url_hd, image_url_hd),
                    description=COALESCE(excluded.description, description),
                    players=COALESCE(excluded.players, players),
                    age_min=COALESCE(excluded.age_min, age_min),
                    playtime=COALESCE(excluded.playtime, playtime),
                    rules_url=COALESCE(excluded.rules_url, rules_url)
                """,
                (
                    p.store_slug, p.external_id, p.title, normalized, p.url,
                    p.image_url, p.image_url_hd, p.description,
                    p.players, p.age_min, p.playtime, p.rules_url,
                ),
            )
            async with db.execute(
                "SELECT id FROM products WHERE store_slug=? AND external_id=?",
                (p.store_slug, p.external_id),
            ) as cur:
                row = await cur.fetchone()
            product_id = row[0]

            await db.execute(
                "INSERT INTO price_observations (product_id, price, fetched_at, raw_json) VALUES (?, ?, ?, ?)",
                (product_id, p.price, now_iso, json.dumps(p.raw, ensure_ascii=False)),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Чтение кеша
    # ------------------------------------------------------------------

    async def search_cached(
        self,
        query: str,
        store_slugs: list[str] | None = None,
        max_age_hours: float = 4.0,
    ) -> list[ProductRecord]:
        """Найти товары в БД, у которых есть свежее наблюдение цены."""
        if max_age_hours == float("inf"):
            cutoff = "0001-01-01T00:00:00+00:00"
        else:
            cutoff = (_utcnow() - timedelta(hours=max_age_hours)).isoformat()
        like = f"%{query.lower()}%"

        sql = """
        WITH latest AS (
            SELECT product_id, price, fetched_at, raw_json,
                   ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY fetched_at DESC) AS rn
            FROM price_observations
            WHERE fetched_at >= ?
        )
        SELECT p.id, p.store_slug, p.external_id, p.title, p.url,
               p.image_url, p.image_url_hd, p.description,
               p.players, p.age_min, p.playtime, p.rules_url,
               l.price, l.fetched_at, l.raw_json
        FROM products p
        JOIN latest l ON l.product_id = p.id AND l.rn = 1
        WHERE p.normalized_title LIKE ?
        """
        params: list = [cutoff, like]

        if store_slugs:
            placeholders = ",".join("?" * len(store_slugs))
            sql += f" AND p.store_slug IN ({placeholders})"
            params.extend(store_slugs)

        sql += " ORDER BY l.fetched_at DESC"

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()

        return [_row_to_record(r) for r in rows]

    async def get_fresh_store_slugs(
        self,
        query: str,
        store_slugs: list[str],
        max_age_hours: float = 4.0,
    ) -> set[str]:
        """Вернуть slugs магазинов, у которых есть хоть один свежий результат по запросу."""
        cutoff = (_utcnow() - timedelta(hours=max_age_hours)).isoformat()
        like = f"%{query.lower()}%"
        placeholders = ",".join("?" * len(store_slugs))

        sql = f"""
        SELECT DISTINCT p.store_slug
        FROM products p
        JOIN price_observations o ON o.product_id = p.id
        WHERE o.fetched_at >= ?
          AND p.normalized_title LIKE ?
          AND p.store_slug IN ({placeholders})
        """
        params = [cutoff, like, *store_slugs]

        async with aiosqlite.connect(self._path) as db:
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()

        return {r[0] for r in rows}

    # ------------------------------------------------------------------
    # Мониторинг — запись
    # ------------------------------------------------------------------

    async def log_request(
        self,
        query: str,
        source: str,
        result_count: int,
        error_count: int,
        duration_ms: int | None,
        errors: dict,
        ts: str,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO request_log
                    (query, source, result_count, error_count, duration_ms, errors_json, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (query, source, result_count, error_count, duration_ms,
                 json.dumps(errors, ensure_ascii=False), ts),
            )
            await db.commit()

    async def log_parser(
        self,
        store_slug: str,
        success: bool,
        result_count: int,
        duration_ms: int | None,
        error_msg: str | None,
        ts: str,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO parser_log
                    (store_slug, success, result_count, duration_ms, error_msg, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (store_slug, 1 if success else 0, result_count, duration_ms, error_msg, ts),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Мониторинг — чтение
    # ------------------------------------------------------------------

    async def get_stats(self, hours: int = 24) -> dict:
        """Сводная статистика запросов за последние N часов."""
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT
                    COUNT(*)                                      AS total,
                    SUM(CASE WHEN source='cache'         THEN 1 ELSE 0 END) AS cache_hits,
                    SUM(CASE WHEN source='network'       THEN 1 ELSE 0 END) AS network_hits,
                    SUM(CASE WHEN source='partial-cache' THEN 1 ELSE 0 END) AS partial_hits,
                    SUM(error_count)                              AS total_errors,
                    AVG(duration_ms)                              AS avg_ms,
                    MAX(duration_ms)                              AS max_ms
                FROM request_log
                WHERE ts >= ?
                """,
                (cutoff,),
            ) as cur:
                row = await cur.fetchone()
        total = row["total"] or 0
        return {
            "period_hours": hours,
            "total_requests": total,
            "cache_hits": row["cache_hits"] or 0,
            "network_hits": row["network_hits"] or 0,
            "partial_hits": row["partial_hits"] or 0,
            "cache_hit_rate": round((row["cache_hits"] or 0) / total * 100, 1) if total else 0,
            "total_errors": row["total_errors"] or 0,
            "avg_response_ms": round(row["avg_ms"]) if row["avg_ms"] else None,
            "max_response_ms": row["max_ms"],
        }

    async def get_store_stats(self) -> list[dict]:
        """Здоровье каждого парсера: last 24h success rate, среднее время, последняя ошибка."""
        cutoff_24h = (_utcnow() - timedelta(hours=24)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row

            # Статистика за 24ч
            async with db.execute(
                """
                SELECT
                    store_slug,
                    COUNT(*)                                    AS total,
                    SUM(success)                                AS successes,
                    AVG(CASE WHEN success=1 THEN duration_ms END) AS avg_ms,
                    MAX(ts)                                     AS last_seen,
                    MAX(CASE WHEN success=1 THEN ts END)        AS last_success
                FROM parser_log
                WHERE ts >= ?
                GROUP BY store_slug
                """,
                (cutoff_24h,),
            ) as cur:
                stats_rows = await cur.fetchall()

            # Последняя ошибка по каждому магазину (за всё время)
            async with db.execute(
                """
                SELECT store_slug, error_msg, ts
                FROM parser_log
                WHERE success=0
                  AND ts IN (
                      SELECT MAX(ts) FROM parser_log WHERE success=0 GROUP BY store_slug
                  )
                """,
            ) as cur:
                error_rows = await cur.fetchall()

        last_errors = {r["store_slug"]: {"msg": r["error_msg"], "ts": r["ts"]} for r in error_rows}

        result = []
        for r in stats_rows:
            slug = r["store_slug"]
            total = r["total"] or 0
            succ = r["successes"] or 0
            result.append({
                "store_slug": slug,
                "total_calls_24h": total,
                "success_count_24h": succ,
                "success_rate_24h": round(succ / total * 100, 1) if total else 0,
                "avg_response_ms": round(r["avg_ms"]) if r["avg_ms"] else None,
                "last_seen": r["last_seen"],
                "last_success": r["last_success"],
                "last_error": last_errors.get(slug),
            })
        return result

    async def get_recent_errors(self, limit: int = 20) -> list[dict]:
        """Последние N ошибок парсеров."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT store_slug, error_msg, duration_ms, ts
                FROM parser_log
                WHERE success=0
                ORDER BY ts DESC
                LIMIT ?
                """,
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {"store_slug": r["store_slug"], "error": r["error_msg"],
             "duration_ms": r["duration_ms"], "ts": r["ts"]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Аналитика — расширенные метрики
    # ------------------------------------------------------------------

    async def get_top_queries(self, hours: int = 168, limit: int = 20) -> list[dict]:
        """Топ запросов за период с метриками cache hit rate и avg latency.

        Полезно для понимания, какие игры пользователи ищут чаще всего и насколько
        эффективно работает кеш для популярных запросов.
        """
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT
                    query,
                    COUNT(*)                                                AS count,
                    SUM(CASE WHEN source='cache' THEN 1 ELSE 0 END)         AS cache_hits,
                    AVG(duration_ms)                                        AS avg_ms,
                    SUM(error_count)                                        AS errors,
                    MAX(ts)                                                 AS last_seen
                FROM request_log
                WHERE ts >= ?
                GROUP BY query
                ORDER BY count DESC, last_seen DESC
                LIMIT ?
                """,
                (cutoff, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "query": r["query"],
                "count": r["count"],
                "cache_hits": r["cache_hits"] or 0,
                "cache_hit_rate": round((r["cache_hits"] or 0) / r["count"] * 100, 1) if r["count"] else 0,
                "avg_ms": round(r["avg_ms"]) if r["avg_ms"] else None,
                "errors": r["errors"] or 0,
                "last_seen": r["last_seen"],
            }
            for r in rows
        ]

    async def get_latency_percentiles(self, hours: int = 24) -> dict:
        """p50/p95/p99 latency запросов /search.

        SQLite не имеет встроенного PERCENTILE_CONT, поэтому вытаскиваем упорядоченный
        массив duration_ms и считаем индексы в Python — для разумных N (десятки тысяч)
        это быстрее, чем CTE-трюки с ROW_NUMBER().
        """
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(
                """
                SELECT duration_ms FROM request_log
                WHERE ts >= ? AND duration_ms IS NOT NULL
                ORDER BY duration_ms
                """,
                (cutoff,),
            ) as cur:
                rows = await cur.fetchall()

        durations = [r[0] for r in rows]
        n = len(durations)
        if n == 0:
            return {"period_hours": hours, "count": 0, "p50": None, "p95": None,
                    "p99": None, "max": None, "avg": None}

        # nearest-rank метод: индекс i для перцентиля p — ceil(p * n) - 1
        def _percentile(p: float) -> int:
            idx = max(0, min(n - 1, int(p * n) - 1 if int(p * n) > 0 else 0))
            return durations[idx]

        return {
            "period_hours": hours,
            "count": n,
            "p50": _percentile(0.50),
            "p95": _percentile(0.95),
            "p99": _percentile(0.99),
            "max": durations[-1],
            "avg": round(sum(durations) / n),
        }

    async def get_requests_timeline(self, hours: int = 24, bucket: str = "hour") -> list[dict]:
        """Распределение запросов по времени с разбивкой по source.

        bucket: 'hour' (по часам, формат YYYY-MM-DDTHH:00:00) или 'day' (YYYY-MM-DD).
        """
        if bucket == "day":
            fmt = "%Y-%m-%d"
        elif bucket == "hour":
            fmt = "%Y-%m-%dT%H:00:00"
        else:
            raise ValueError(f"unsupported bucket: {bucket}")

        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT
                    strftime('{fmt}', ts) AS ts_bucket,
                    COUNT(*)              AS total,
                    SUM(CASE WHEN source='cache'         THEN 1 ELSE 0 END) AS cache,
                    SUM(CASE WHEN source='network'       THEN 1 ELSE 0 END) AS network,
                    SUM(CASE WHEN source='partial-cache' THEN 1 ELSE 0 END) AS partial,
                    SUM(error_count)      AS errors,
                    AVG(duration_ms)      AS avg_ms
                FROM request_log
                WHERE ts >= ?
                GROUP BY ts_bucket
                ORDER BY ts_bucket
                """,
                (cutoff,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "ts": r["ts_bucket"],
                "total": r["total"],
                "cache": r["cache"] or 0,
                "network": r["network"] or 0,
                "partial": r["partial"] or 0,
                "errors": r["errors"] or 0,
                "avg_ms": round(r["avg_ms"]) if r["avg_ms"] else None,
            }
            for r in rows
        ]

    async def get_cache_rate_timeline(self, hours: int = 168, bucket: str = "hour") -> list[dict]:
        """Динамика cache hit rate во времени — показывает, насколько эффективен кеш.

        Возвращает [{ts, cache_hit_rate, total}], удобно строить line chart.
        """
        timeline = await self.get_requests_timeline(hours, bucket)
        return [
            {
                "ts": p["ts"],
                "total": p["total"],
                "cache_hit_rate": round(p["cache"] / p["total"] * 100, 1) if p["total"] else 0,
            }
            for p in timeline
        ]

    async def get_store_distribution(self, hours: int = 24) -> list[dict]:
        """Распределение вызовов парсеров по магазинам — для pie/bar chart."""
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT
                    store_slug,
                    COUNT(*)              AS calls,
                    SUM(success)          AS successes,
                    AVG(result_count)     AS avg_results,
                    AVG(CASE WHEN success=1 THEN duration_ms END) AS avg_ms
                FROM parser_log
                WHERE ts >= ?
                GROUP BY store_slug
                ORDER BY calls DESC
                """,
                (cutoff,),
            ) as cur:
                rows = await cur.fetchall()

        rows_data = [dict(r) for r in rows]
        total_calls = sum(r["calls"] for r in rows_data) or 1
        return [
            {
                "store_slug": r["store_slug"],
                "calls": r["calls"],
                "successes": r["successes"] or 0,
                "success_rate": round((r["successes"] or 0) / r["calls"] * 100, 1) if r["calls"] else 0,
                "avg_results": round(r["avg_results"], 2) if r["avg_results"] is not None else 0,
                "avg_ms": round(r["avg_ms"]) if r["avg_ms"] else None,
                "share_pct": round(r["calls"] / total_calls * 100, 1),
            }
            for r in rows_data
        ]

    async def get_latency_histogram(self, hours: int = 24) -> list[dict]:
        """Гистограмма распределения latency для bar chart.

        Фиксированные бины: 0-100, 100-300, 300-1000, 1000-3000, 3000+ мс.
        Распределение по этим границам помогает увидеть форму latency без сжатия в percentile.
        """
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT
                    SUM(CASE WHEN duration_ms <  100 THEN 1 ELSE 0 END) AS b0,
                    SUM(CASE WHEN duration_ms >= 100  AND duration_ms <  300 THEN 1 ELSE 0 END) AS b1,
                    SUM(CASE WHEN duration_ms >= 300  AND duration_ms < 1000 THEN 1 ELSE 0 END) AS b2,
                    SUM(CASE WHEN duration_ms >= 1000 AND duration_ms < 3000 THEN 1 ELSE 0 END) AS b3,
                    SUM(CASE WHEN duration_ms >= 3000 THEN 1 ELSE 0 END) AS b4
                FROM request_log
                WHERE ts >= ? AND duration_ms IS NOT NULL
                """,
                (cutoff,),
            ) as cur:
                row = await cur.fetchone()
        labels = ["<100мс", "100-300мс", "300мс-1с", "1-3с", ">3с"]
        keys = ["b0", "b1", "b2", "b3", "b4"]
        return [{"bin": labels[i], "count": (row[keys[i]] or 0)} for i in range(5)]

    async def get_empty_responses(self, hours: int = 24, limit: int = 50) -> list[dict]:
        """Успешные вызовы парсеров с пустым результатом — потенциально 'тихие' сбои.

        Парсер не упал, но и не вернул товаров: возможно, изменилась структура страницы
        или сменился URL поиска без явной ошибки.
        """
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT store_slug, duration_ms, ts
                FROM parser_log
                WHERE ts >= ? AND success=1 AND result_count=0
                ORDER BY ts DESC
                LIMIT ?
                """,
                (cutoff, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {"store_slug": r["store_slug"], "duration_ms": r["duration_ms"], "ts": r["ts"]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Database Explorer — метаданные и обозреватель товаров
    # ------------------------------------------------------------------

    async def get_db_metadata(self) -> dict:
        """Сводка по содержимому БД: размер, кол-во записей, диапазон наблюдений."""
        size_bytes = self._path.stat().st_size if self._path.exists() else 0

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            counts: dict[str, int] = {}
            for tbl in ("stores", "products", "price_observations", "request_log", "parser_log"):
                async with db.execute(f"SELECT COUNT(*) AS n FROM {tbl}") as cur:
                    row = await cur.fetchone()
                counts[tbl] = row["n"] if row else 0

            async with db.execute(
                "SELECT MIN(fetched_at) AS oldest, MAX(fetched_at) AS newest FROM price_observations"
            ) as cur:
                obs = await cur.fetchone()

        return {
            "db_size_bytes": size_bytes,
            "db_size_mb": round(size_bytes / 1024 / 1024, 2),
            "tables": counts,
            "oldest_observation": obs["oldest"] if obs else None,
            "newest_observation": obs["newest"] if obs else None,
        }

    async def get_store_inventory(self) -> list[dict]:
        """Per-store инвентарь: число товаров, наблюдений, диапазон цен и дат.

        Делаем три отдельных запроса вместо мульти-JOIN — иначе картезианское произведение
        `products × price_observations × latest` ломает COUNT и AVG.

        Цены конвертируются в рубли (price/100.0) — UI слой получает уже готовые рубли.
        """
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row

            # 1. Кол-во товаров и наблюдений per store
            async with db.execute(
                """
                SELECT p.store_slug,
                       COUNT(DISTINCT p.id) AS products_count,
                       COUNT(o.id)          AS observations_count,
                       MIN(o.fetched_at)    AS oldest_obs,
                       MAX(o.fetched_at)    AS newest_obs
                FROM products p
                LEFT JOIN price_observations o ON o.product_id = p.id
                GROUP BY p.store_slug
                """,
            ) as cur:
                base_rows = {r["store_slug"]: dict(r) for r in await cur.fetchall()}

            # 2. Перцентили последней цены (min/avg/max) per store
            async with db.execute(
                """
                WITH latest AS (
                  SELECT p.store_slug, p.id AS product_id, l.price
                  FROM products p
                  JOIN (
                    SELECT product_id, price,
                           ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY fetched_at DESC) AS rn
                    FROM price_observations
                  ) l ON l.product_id = p.id AND l.rn = 1
                )
                SELECT store_slug,
                       MIN(price) / 100.0 AS min_p,
                       MAX(price) / 100.0 AS max_p,
                       AVG(price) / 100.0 AS mean_p
                FROM latest
                GROUP BY store_slug
                """,
            ) as cur:
                price_rows = {r["store_slug"]: dict(r) for r in await cur.fetchall()}

        slugs = sorted(base_rows.keys(), key=lambda s: -base_rows[s]["products_count"])
        return [
            {
                "store_slug": slug,
                "products_count": base_rows[slug]["products_count"] or 0,
                "observations_count": base_rows[slug]["observations_count"] or 0,
                "oldest_obs": base_rows[slug]["oldest_obs"],
                "newest_obs": base_rows[slug]["newest_obs"],
                "min_price_rub": round(price_rows[slug]["min_p"], 2)
                    if slug in price_rows and price_rows[slug]["min_p"] is not None else None,
                "max_price_rub": round(price_rows[slug]["max_p"], 2)
                    if slug in price_rows and price_rows[slug]["max_p"] is not None else None,
                "mean_price_rub": round(price_rows[slug]["mean_p"], 2)
                    if slug in price_rows and price_rows[slug]["mean_p"] is not None else None,
            }
            for slug in slugs
        ]

    async def list_products(
        self,
        store: str | None = None,
        query: str | None = None,
        sort: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Список товаров с пагинацией. Возвращает (rows, total_count).

        sort: 'newest' | 'oldest' | 'price_asc' | 'price_desc' | 'title'.
        Поиск по normalized_title (lower-case кириллица — см. db.py:upsert_product).
        """
        sort_map = {
            "newest":     "l.fetched_at DESC",
            "oldest":     "l.fetched_at ASC",
            "price_asc":  "l.price ASC",
            "price_desc": "l.price DESC",
            "title":      "p.title ASC",
        }
        order_by = sort_map.get(sort, sort_map["newest"])

        where_clauses: list[str] = []
        params: list = []
        if store:
            where_clauses.append("p.store_slug = ?")
            params.append(store)
        if query:
            where_clauses.append("p.normalized_title LIKE ?")
            params.append(f"%{query.lower()}%")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            # Сначала total — нужно для UI пагинации (отдельный запрос проще, чем COUNT() OVER())
            async with db.execute(
                f"SELECT COUNT(*) AS n FROM products p {where_sql}", params,
            ) as cur:
                total = (await cur.fetchone())["n"]

            sql = f"""
            WITH latest AS (
              SELECT product_id, price, fetched_at,
                     ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY fetched_at DESC) AS rn
              FROM price_observations
            )
            SELECT
              p.id, p.store_slug, p.title, p.url, p.image_url,
              l.price, l.fetched_at,
              (SELECT COUNT(*) FROM price_observations WHERE product_id = p.id) AS history_len
            FROM products p
            LEFT JOIN latest l ON l.product_id = p.id AND l.rn = 1
            {where_sql}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """
            async with db.execute(sql, [*params, limit, offset]) as cur:
                rows = await cur.fetchall()

        items = [
            {
                "id": r["id"],
                "store_slug": r["store_slug"],
                "title": r["title"],
                "url": r["url"],
                "image_url": r["image_url"],
                "price_rub": round(r["price"] / 100, 2) if r["price"] is not None else None,
                "fetched_at": r["fetched_at"],
                "history_len": r["history_len"],
            }
            for r in rows
        ]
        return items, total

    async def get_product_full(self, product_id: int) -> dict | None:
        """Полные данные товара + последние 50 точек истории цен."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, store_slug, external_id, title, url,
                       image_url, image_url_hd, description,
                       players, age_min, playtime, rules_url
                FROM products WHERE id = ?
                """,
                (product_id,),
            ) as cur:
                p = await cur.fetchone()
            if not p:
                return None

            async with db.execute(
                """
                SELECT price, fetched_at, raw_json
                FROM price_observations
                WHERE product_id = ?
                ORDER BY fetched_at DESC
                LIMIT 50
                """,
                (product_id,),
            ) as cur:
                obs_rows = await cur.fetchall()

        history = [
            {
                "price_rub": round(r["price"] / 100, 2),
                "price_kopecks": r["price"],
                "fetched_at": r["fetched_at"],
                "raw": json.loads(r["raw_json"]) if r["raw_json"] else {},
            }
            for r in obs_rows
        ]
        return {
            "id": p["id"],
            "store_slug": p["store_slug"],
            "external_id": p["external_id"],
            "title": p["title"],
            "url": p["url"],
            "image_url": p["image_url"],
            "image_url_hd": p["image_url_hd"],
            "description": p["description"],
            "players": p["players"],
            "age_min": p["age_min"],
            "playtime": p["playtime"],
            "rules_url": p["rules_url"],
            "history": history,
        }

    async def get_price_distribution(self, store_slug: str | None = None) -> dict:
        """Перцентили цены по последним наблюдениям (рубли)."""
        async with aiosqlite.connect(self._path) as db:
            params: list = []
            where = ""
            if store_slug:
                where = "WHERE p.store_slug = ?"
                params.append(store_slug)
            async with db.execute(
                f"""
                WITH latest AS (
                  SELECT product_id, price,
                         ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY fetched_at DESC) AS rn
                  FROM price_observations
                )
                SELECT l.price AS price
                FROM products p
                JOIN latest l ON l.product_id = p.id AND l.rn = 1
                {where}
                ORDER BY l.price
                """,
                params,
            ) as cur:
                rows = await cur.fetchall()

        prices = [r[0] / 100 for r in rows]
        n = len(prices)
        if n == 0:
            return {"count": 0, "min": None, "p25": None, "p50": None,
                    "p75": None, "max": None}

        def _p(p: float) -> float:
            idx = max(0, min(n - 1, int(p * n) - 1 if int(p * n) > 0 else 0))
            return round(prices[idx], 2)

        return {
            "count": n,
            "min": round(prices[0], 2),
            "p25": _p(0.25),
            "p50": _p(0.50),
            "p75": _p(0.75),
            "max": round(prices[-1], 2),
        }

    # ------------------------------------------------------------------
    # История цен
    # ------------------------------------------------------------------

    async def get_history(self, product_id: int) -> list[PricePoint]:
        sql = """
        SELECT price, fetched_at FROM price_observations
        WHERE product_id = ?
        ORDER BY fetched_at ASC
        """
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(sql, (product_id,)) as cur:
                rows = await cur.fetchall()

        return [
            PricePoint(price=r[0], fetched_at=datetime.fromisoformat(r[1]))
            for r in rows
        ]


def _row_to_record(r: aiosqlite.Row) -> ProductRecord:
    return ProductRecord(
        id=r["id"],
        store_slug=r["store_slug"],
        external_id=r["external_id"],
        title=r["title"],
        url=r["url"],
        image_url=r["image_url"],
        image_url_hd=r["image_url_hd"],
        description=r["description"],
        players=r["players"],
        age_min=r["age_min"],
        playtime=r["playtime"],
        rules_url=r["rules_url"],
        price=r["price"],
        fetched_at=datetime.fromisoformat(r["fetched_at"]),
        raw=json.loads(r["raw_json"]),
    )
