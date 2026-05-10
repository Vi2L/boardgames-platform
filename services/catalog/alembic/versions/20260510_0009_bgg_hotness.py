"""bgg_hotness — история BGG Hotness-снимков

Таблица для хранения ежедневных снимков BGG Hotness-списка (до 50 позиций).
Один снимок в день на игру (UNIQUE snapshot_date + bgg_id) — идемпотентный
upsert при повторных прогонах.

game_id — nullable FK на games (SET NULL при удалении/merge игры), денормализация
для быстрого JOIN без поиска по bgg_id.

Revision ID: 0009
Revises:     0008
Create Date: 2026-05-10
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bgg_hotness",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("bgg_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("snapshot_date", "bgg_id", name="uq_bgg_hotness_date_bgg"),
    )
    op.create_index("ix_bgg_hotness_snapshot_date", "bgg_hotness", ["snapshot_date"])
    op.create_index("ix_bgg_hotness_bgg_id", "bgg_hotness", ["bgg_id"])
    op.create_index(
        "ix_bgg_hotness_game_id",
        "bgg_hotness",
        ["game_id"],
        postgresql_where=sa.text("game_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_bgg_hotness_game_id", table_name="bgg_hotness")
    op.drop_index("ix_bgg_hotness_bgg_id", table_name="bgg_hotness")
    op.drop_index("ix_bgg_hotness_snapshot_date", table_name="bgg_hotness")
    op.drop_table("bgg_hotness")
