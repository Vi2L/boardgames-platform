"""Локальная SQLite-БД портала.

Накапливает результаты поиска и журнал запросов на стороне дебаг-портала,
не дублируя БД parsers. Используется для:

- DatabasePage (фаза 3) — список просмотренных товаров с фильтрами;
- ProductPage с deep-link (`/products/:id`) — стабильный источник, даже
  если результат поиска скроллится;
- Snapshots/Suites (фаза 4) — снимки прогонов, тест-сьюты, watch-runs;
- Журнал searches, прошедших через сам портал.

ВАЖНО: эта БД НЕ подменяет parsers — там полный кеш всех клиентов. Здесь
только то, что прошло через дебаг-портал. Если в будущем parsers
получит /products эндпоинт (см. parsers-wishlist.md п. 2), эта БД
останется как локальный лог activity-портала.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from app.schemas import ProductOut

# Все миграции хранятся в одном модуле — простой список SQL,
# применяемый по порядку. Версионирование через PRAGMA user_version.
_MIGRATIONS: list[str] = [
    # v1: базовые таблицы
    """
    CREATE TABLE IF NOT EXISTS local_products (
        id               INTEGER PRIMARY KEY,
        store_slug       TEXT NOT NULL,
        external_id      TEXT,
        title            TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        price_rub        REAL NOT NULL,
        url              TEXT NOT NULL,
        image_url        TEXT,
        image_url_hd     TEXT,
        description      TEXT,
        players          TEXT,
        age_min          INTEGER,
        playtime         TEXT,
        rules_url        TEXT,
        extra_json       TEXT NOT NULL DEFAULT '{}',
        fetched_at       TEXT NOT NULL,
        last_seen_at     TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_local_products_norm ON local_products(normalized_title);",
    "CREATE INDEX IF NOT EXISTS idx_local_products_store ON local_products(store_slug);",
    """
    CREATE TABLE IF NOT EXISTS local_searches (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        query           TEXT NOT NULL,
        stores          TEXT,
        source          TEXT,
        total_ms        INTEGER,
        products_count  INTEGER NOT NULL DEFAULT 0,
        error_count     INTEGER NOT NULL DEFAULT 0,
        errors_json     TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_local_searches_ts ON local_searches(created_at DESC);",
]


def _normalize_title(title: str) -> str:
    """Lower-case + collapse whitespace для idx_local_products_norm."""
    return " ".join(title.lower().split())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PortalDB:
    """Async SQLite-обёртка с одним shared connection.

    Один connection — норма для SQLite в asyncio: aiosqlite сериализует
    операции, а наш профиль нагрузки (десятки операций в минуту) не
    требует пула. Connection живёт всё время приложения, закрывается в
    lifespan-shutdown.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        # Возвращаем dict-like Row для удобства доступа по именам колонок.
        self._conn.row_factory = aiosqlite.Row
        await self._apply_migrations()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("PortalDB not initialized — call init() first")
        return self._conn

    async def _apply_migrations(self) -> None:
        """Применяет миграции по списку через PRAGMA user_version."""
        cur = await self.conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        version = int(row[0]) if row else 0

        for idx, sql in enumerate(_MIGRATIONS, start=1):
            if idx <= version:
                continue
            await self.conn.executescript(sql)
            await self.conn.execute(f"PRAGMA user_version = {idx}")
            await self.conn.commit()

    # ── Products ───────────────────────────────────────────────────────────

    async def upsert_products(self, products: Iterable[ProductOut]) -> int:
        """Записывает/обновляет товары. Возвращает количество строк.

        last_seen_at обновляется всегда (используется в DatabasePage для
        сортировки по «свежести»). Поля могут быть None — DB nullable.
        """
        now = _utc_now_iso()
        count = 0
        for p in products:
            extra_json = json.dumps(p.extra, ensure_ascii=False, sort_keys=True)
            external_id = p.extra.get("external_id") if isinstance(p.extra, dict) else None
            external_id = external_id if isinstance(external_id, str) else None

            await self.conn.execute(
                """
                INSERT INTO local_products (
                    id, store_slug, external_id, title, normalized_title, price_rub, url,
                    image_url, image_url_hd, description, players, age_min,
                    playtime, rules_url, extra_json, fetched_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    normalized_title=excluded.normalized_title,
                    price_rub=excluded.price_rub,
                    url=excluded.url,
                    image_url=COALESCE(excluded.image_url, image_url),
                    image_url_hd=COALESCE(excluded.image_url_hd, image_url_hd),
                    description=COALESCE(excluded.description, description),
                    players=COALESCE(excluded.players, players),
                    age_min=COALESCE(excluded.age_min, age_min),
                    playtime=COALESCE(excluded.playtime, playtime),
                    rules_url=COALESCE(excluded.rules_url, rules_url),
                    extra_json=excluded.extra_json,
                    fetched_at=excluded.fetched_at,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    p.id, p.store_slug, external_id, p.title, _normalize_title(p.title),
                    p.price_rub, p.url,
                    p.image_url, p.image_url_hd, p.description, p.players, p.age_min,
                    p.playtime, p.rules_url, extra_json, p.fetched_at or now, now,
                ),
            )
            count += 1
        await self.conn.commit()
        return count

    async def list_products(
        self, *, q: str | None = None, store: str | None = None,
        page: int = 1, page_size: int = 50,
        sort: str = "fetched_desc",
    ) -> dict[str, Any]:
        """Пагинированный список с фильтрами. Возвращает {items, total, page, page_size}."""
        where: list[str] = []
        params: list[Any] = []
        if q:
            where.append("normalized_title LIKE ?")
            params.append(f"%{_normalize_title(q)}%")
        if store:
            where.append("store_slug = ?")
            params.append(store)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        order_map = {
            "fetched_desc": "last_seen_at DESC",
            "price_asc":    "price_rub ASC",
            "price_desc":   "price_rub DESC",
            "title_asc":    "title ASC",
        }
        order_sql = order_map.get(sort, order_map["fetched_desc"])

        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        offset = (page - 1) * page_size

        cur = await self.conn.execute(
            f"SELECT COUNT(*) FROM local_products {where_sql}", params,
        )
        row = await cur.fetchone()
        total = int(row[0]) if row else 0

        cur = await self.conn.execute(
            f"""
            SELECT * FROM local_products
            {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        )
        rows = await cur.fetchall()

        return {
            "items": [_row_to_product(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_product(self, product_id: int) -> ProductOut | None:
        cur = await self.conn.execute(
            "SELECT * FROM local_products WHERE id = ?", (product_id,),
        )
        row = await cur.fetchone()
        return _row_to_product(row) if row else None

    async def delete_product(self, product_id: int) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM local_products WHERE id = ?", (product_id,),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # ── Searches ───────────────────────────────────────────────────────────

    async def log_search(
        self, *, query: str, stores: list[str] | None,
        source: str | None, total_ms: int | None,
        products_count: int, error_count: int,
        errors: dict[str, str] | None = None,
    ) -> int:
        """Записывает в журнал прошедших через портал поисков."""
        cur = await self.conn.execute(
            """
            INSERT INTO local_searches (
                query, stores, source, total_ms,
                products_count, error_count, errors_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query,
                ",".join(stores) if stores else None,
                source,
                total_ms,
                products_count,
                error_count,
                json.dumps(errors or {}, ensure_ascii=False),
                _utc_now_iso(),
            ),
        )
        await self.conn.commit()
        return int(cur.lastrowid or 0)

    async def list_searches(
        self, *, page: int = 1, page_size: int = 50, query: str | None = None,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        offset = (page - 1) * page_size

        where_sql, params = "", []
        if query:
            where_sql = "WHERE query LIKE ?"
            params.append(f"%{query.lower()}%")

        cur = await self.conn.execute(
            f"SELECT COUNT(*) FROM local_searches {where_sql}", params,
        )
        row = await cur.fetchone()
        total = int(row[0]) if row else 0

        # Дополнительная сортировка по id DESC нужна для случая равных
        # created_at (тесты делают две вставки в одну секунду — без id-порядка
        # SQLite может вернуть в произвольном порядке).
        cur = await self.conn.execute(
            f"""
            SELECT * FROM local_searches
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        )
        rows = await cur.fetchall()

        return {
            "items": [
                {
                    "id": r["id"],
                    "query": r["query"],
                    "stores": r["stores"],
                    "source": r["source"],
                    "total_ms": r["total_ms"],
                    "products_count": r["products_count"],
                    "error_count": r["error_count"],
                    "errors_json": r["errors_json"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


def _row_to_product(row: aiosqlite.Row | None) -> ProductOut:
    """Маппинг row → ProductOut. extra_json парсится обратно в dict."""
    assert row is not None
    try:
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
    except json.JSONDecodeError:
        extra = {}
    return ProductOut(
        id=row["id"],
        store_slug=row["store_slug"],
        title=row["title"],
        price_rub=row["price_rub"],
        url=row["url"],
        image_url=row["image_url"],
        image_url_hd=row["image_url_hd"],
        description=row["description"],
        players=row["players"],
        age_min=row["age_min"],
        playtime=row["playtime"],
        rules_url=row["rules_url"],
        fetched_at=row["fetched_at"],
        extra=extra,
    )


# ── Singleton ──────────────────────────────────────────────────────────────

_db: PortalDB | None = None


def get_portal_db() -> PortalDB:
    if _db is None:
        raise RuntimeError("PortalDB not initialized — call init_portal_db() first")
    return _db


async def init_portal_db() -> PortalDB:
    """Инициализация singletonа. Вызывается из app.deps.init_services()."""
    global _db
    db_path = os.getenv("PORTAL_DB_PATH", "data/portal.sqlite")
    _db = PortalDB(db_path)
    await _db.init()
    return _db


async def close_portal_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
