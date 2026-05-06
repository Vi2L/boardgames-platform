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
