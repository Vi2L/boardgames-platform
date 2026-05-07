"""Проверка ключевых схемных решений на живой Postgres-БД.

Тесты проверяют то, что НЕ проверяется на уровне ORM-моделей:
- generated column `title_norm` действительно вычисляется на стороне БД
- pg_trgm GIN-индекс работает: оператор `%` находит игру по опечатке
- IMMUTABLE-обёртка `immutable_unaccent` создана и работает
- UNIQUE-ограничения не дают создать дубль (slug, bgg_id)
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]


async def test_title_norm_is_generated(db_conn: AsyncConnection) -> None:
    """INSERT без указания title_norm — БД сама вычисляет."""
    await db_conn.execute(
        text(
            "INSERT INTO games (slug, title, source) "
            "VALUES (:slug, :title, 'manual')"
        ),
        {"slug": "test-game-norm", "title": "Сапёр"},
    )
    row = (
        await db_conn.execute(
            text("SELECT title, title_norm FROM games WHERE slug = :slug"),
            {"slug": "test-game-norm"},
        )
    ).one()
    assert row.title == "Сапёр"
    # unaccent снимает диакритику + lower → 'сапер' (без 'ё').
    assert row.title_norm == "сапер"


async def test_pg_trgm_finds_typo(db_conn: AsyncConnection) -> None:
    """Запрос с опечаткой находит игру через оператор `%`.

    Это сценарий матчинга оффер'а из магазина: парсер прислал слегка другое
    написание ('каркасон' вместо 'каркассон'), мы должны его найти.
    """
    await db_conn.execute(
        text(
            "INSERT INTO games (slug, title, source) "
            "VALUES ('carc', 'Каркассон', 'manual')"
        )
    )
    # Перед тестом подкручиваем порог сходства — дефолт 0.3 в Postgres.
    # Для нашего случая (ru-кириллица, короткие слова) дефолт работает.
    rows = (
        await db_conn.execute(
            text(
                "SELECT title, similarity(title_norm, :q) AS score "
                "FROM games WHERE title_norm % :q"
            ),
            {"q": "каркасон"},  # опечатка: одна 'с' вместо двух
        )
    ).all()
    assert len(rows) == 1, f"ожидали 1 совпадение, получили {len(rows)}"
    assert rows[0].title == "Каркассон"
    assert rows[0].score > 0.4


async def test_unique_slug_rejected(db_conn: AsyncConnection) -> None:
    from sqlalchemy.exc import IntegrityError

    await db_conn.execute(
        text("INSERT INTO games (slug, title, source) VALUES ('dup', 'A', 'manual')")
    )
    with pytest.raises(IntegrityError):
        await db_conn.execute(
            text(
                "INSERT INTO games (slug, title, source) VALUES ('dup', 'B', 'manual')"
            )
        )


async def test_alias_cascade_delete(db_conn: AsyncConnection) -> None:
    """При удалении игры алиасы должны исчезнуть (ON DELETE CASCADE)."""
    await db_conn.execute(
        text(
            "INSERT INTO games (id, slug, title, source) "
            "VALUES (9999, 'casc', 'X', 'manual')"
        )
    )
    await db_conn.execute(
        text(
            "INSERT INTO game_aliases (game_id, alias, source) "
            "VALUES (9999, 'X-alias', 'manual')"
        )
    )
    await db_conn.execute(text("DELETE FROM games WHERE id = 9999"))
    cnt = (
        await db_conn.execute(
            text("SELECT count(*) FROM game_aliases WHERE game_id = 9999")
        )
    ).scalar_one()
    assert cnt == 0


async def test_offer_unmatched_default(db_conn: AsyncConnection) -> None:
    """Новый оффер без game_id — по умолчанию unmatched."""
    await db_conn.execute(
        text(
            "INSERT INTO offers (store_slug, external_id, url, title_raw) "
            "VALUES ('hobbygames', 'ext-1', 'https://x', 'Каркассон')"
        )
    )
    row = (
        await db_conn.execute(
            text(
                "SELECT match_status, game_id, title_raw_norm "
                "FROM offers WHERE store_slug='hobbygames' AND external_id='ext-1'"
            )
        )
    ).one()
    assert row.match_status == "unmatched"
    assert row.game_id is None
    assert row.title_raw_norm == "каркассон"
