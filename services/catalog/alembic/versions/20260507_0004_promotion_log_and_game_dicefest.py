"""promotion_log + game_dicefest satellite

PR-2 двухстадийной схемы. После того как dicefest_raw_games (миграция 0003)
наполнен парсером, промоушен переносит данные в canonical БД через UI с
матчингом и журналом для отката.

1) import_promotion_log — УНИВЕРСАЛЬНЫЙ аудит-журнал на все будущие источники
   (BGG/Tesera/Dicefest/BGA/...). Provider — колонка, raw_id — без FK
   (per-provider staging-таблицы). При revert пишется новая строка action='revert'
   и помечается reverted_at у исходной.

2) game_dicefest — satellite-таблица per-source (по образцу game_bgg/game_wikidata).
   PK на id (НЕ на game_id) + UNIQUE (game_id, slug) — одна canonical-игра
   может иметь несколько dicefest-записей при переизданиях (две страницы
   "Каркассон 1-е изд" и "Каркассон 2-е изд" мапятся на один canonical Game).

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- import_promotion_log (общий для всех источников) ---
    op.create_table(
        "import_promotion_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        # raw_id — намеренно без FK, потому что raw живёт в per-provider
        # таблицах (dicefest_raw_games, в будущем bga_raw_games и т.д.).
        sa.Column("raw_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),  # link|create|skip|reject|revert
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "alias_id",
            sa.BigInteger(),
            sa.ForeignKey("game_aliases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "satellite_created",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("performed_by", sa.Text(), nullable=True),
        sa.Column(
            "performed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_import_promotion_log_provider_raw",
        "import_promotion_log",
        ["provider", "raw_id"],
    )
    op.create_index(
        "ix_import_promotion_log_perf_at",
        "import_promotion_log",
        [sa.text("performed_at DESC")],
    )

    # --- game_dicefest (satellite per-source) ---
    op.create_table(
        "game_dicefest",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raw_id",
            sa.BigInteger(),
            sa.ForeignKey("dicefest_raw_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("title_ru", sa.Text(), nullable=True),
        sa.Column("title_en", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("release_month", sa.Integer(), nullable=True),
        sa.Column("release_status", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        # Несколько dicefest-страниц могут мапиться на одну canonical Game
        # (переиздания) — но в рамках одной game каждый slug уникален.
        sa.UniqueConstraint("game_id", "slug", name="uq_game_dicefest_game_slug"),
    )
    op.create_index("ix_game_dicefest_game_id", "game_dicefest", ["game_id"])


def downgrade() -> None:
    op.drop_index("ix_game_dicefest_game_id", table_name="game_dicefest")
    op.drop_table("game_dicefest")
    op.drop_index("ix_import_promotion_log_perf_at", table_name="import_promotion_log")
    op.drop_index("ix_import_promotion_log_provider_raw", table_name="import_promotion_log")
    op.drop_table("import_promotion_log")
