"""CAT-17.2: match_publisher_prefixes — таблица prefix'ов издателей.

Используется `catalog/matching/title_pipeline.py:strip_publisher_prefix()`
для чистки сырых названий из WB/Avito/Ozon перед T1 trgm-матчингом.

Seed-данные — ~25 префиксов из реальных WB/Avito title'ов. Список не
закрытый — оператор может добавлять через `POST /matching/publisher-prefixes`
без миграции. Сортировка по длине DESC реализована в `load_pipeline()`
(в SQL через `ORDER BY length(prefix) DESC`).

Revision ID: 0020
Revises:     0019
Create Date: 2026-05-22
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels = None
depends_on = None


# Seed: реальные префиксы из WB/Avito/Ozon. После выкатки оператор пополняет
# через UI/API. Не делаем эти префиксы full-list — лучше иметь немного и
# дополнять по факту, чем держать огромный список с false-positive'ами
# («АСТ» — слишком короткий, рискует обрезать имена игр со слова «АСТ»).
_SEED_PREFIXES: tuple[str, ...] = (
    # Hobby World — главный российский локализатор
    "Hobby World",
    "Hobby World:",
    "Hobby World -",
    "HW:",
    # GaGa Games
    "GaGa Games",
    "GaGa Games:",
    "GaGa Games -",
    "GaGa Games |",
    # Лавка Игр
    "Лавка Игр",
    "Лавка Игр:",
    # Звезда
    "Звезда",
    "Звезда:",
    # Crowd Games / CrowdGames
    "Crowd Games",
    "Crowd Games:",
    "CrowdGames:",
    # Стиль Жизни
    "Стиль Жизни",
    "Стиль Жизни:",
    # Мосигра
    "Мосигра",
    "Мосигра:",
    # Cosmodrome Games
    "Cosmodrome Games",
    "Cosmodrome Games:",
    # Мир Хобби
    "Мир Хобби",
    "Мир Хобби:",
    # Игромаг (магазин-агрегатор, но иногда префикс в названии)
    "Игромаг:",
    # Правильные игры
    "Правильные игры",
    "Правильные игры:",
)


def upgrade() -> None:
    op.create_table(
        "match_publisher_prefixes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        # prefix хранится как есть (с пунктуацией) — strip_publisher_prefix
        # сравнивает case-insensitive, но сохраняет регистр для UI display.
        sa.Column("prefix", sa.Text(), nullable=False, unique=True),
        # normalized — что остаётся после стрипа (опционально, для UI preview).
        # NULL означает «полностью убрать префикс + следующий разделитель».
        sa.Column("normalized", sa.Text()),
        # source: 'seed' (миграция), 'manual' (через UI), 'discovered' (если в
        # будущем сделаем авто-обнаружение через анализ unmatched).
        sa.Column(
            "source", sa.String(32), nullable=False, server_default="manual",
        ),
        sa.Column(
            "is_active", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    # Партиал-индекс по active — typical query `WHERE is_active = TRUE`.
    op.create_index(
        "ix_match_publisher_prefixes_active",
        "match_publisher_prefixes",
        ["is_active"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # Seed-данные. Используем bulk_insert для типобезопасности через SQLAlchemy.
    table = sa.table(
        "match_publisher_prefixes",
        sa.column("prefix", sa.Text()),
        sa.column("source", sa.String(32)),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        table,
        [
            {"prefix": p, "source": "seed", "is_active": True}
            for p in _SEED_PREFIXES
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_match_publisher_prefixes_active",
        table_name="match_publisher_prefixes",
    )
    op.drop_table("match_publisher_prefixes")
