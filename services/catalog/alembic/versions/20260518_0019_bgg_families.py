"""CAT-8: bgg_families + bgg_family_members + scheduler-job + runtime_flag

Хранилище BGG-семей (Series: Catan, Series: Carcassonne, etc.) для:
1. Cascade-обогащения при enrich_one: после успешного thing-import тянем
   членов всех связанных семей в фоне (fire-and-forget).
2. Еженедельный refresh-job bgg_family_refresh: обходит N самых старых
   по fetched_at families, обновляет members.

`bgg_family_members` хранит (family_id, bgg_id) без жёсткого FK на games —
позволяет записать членов до их thing-импорта. game_id заполняется через
JOIN при чтении в API.

Revision ID: 0019
Revises:     0018
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bgg_families",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("bgg_family_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text()),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "raw",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.UniqueConstraint("bgg_family_id", name="uq_bgg_families_bgg_id"),
    )

    op.create_table(
        "bgg_family_members",
        sa.Column(
            "family_id",
            sa.BigInteger(),
            sa.ForeignKey("bgg_families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("bgg_id", sa.Integer(), nullable=False),
        # `game_id` опционален — могут быть упомянуты члены, ещё не импортированные
        # через /thing. Резолвится через JOIN на games.bgg_id при чтении.
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
        ),
        sa.PrimaryKeyConstraint("family_id", "bgg_id"),
    )
    op.create_index(
        "ix_bgg_family_members_game", "bgg_family_members", ["game_id"]
    )
    op.create_index(
        "ix_bgg_family_members_bgg_id", "bgg_family_members", ["bgg_id"]
    )
    # `fetched_at` индекс — для job'а bgg_family_refresh (ORDER BY fetched_at).
    op.create_index(
        "ix_bgg_families_fetched_at", "bgg_families", ["fetched_at"]
    )

    # Сид scheduler-job'а. cron: воскресенье 05:00 UTC.
    op.execute("""
        INSERT INTO scheduler_configs (job_id, cron_expr, enabled, params)
        VALUES (
            'bgg_family_refresh',
            '0 5 * * 0',
            TRUE,
            '{"max_families": 100, "enrich_rate_limit_sec": 1.0}'::jsonb
        )
        ON CONFLICT (job_id) DO NOTHING
    """)

    # Сид runtime_flag — даёт UI editable toggle для cascade (через
    # PATCH /admin/runtime-flags/bgg_family_cascade_enabled). Default — true,
    # синхронно с Settings.bgg_family_cascade_enabled.
    op.execute("""
        INSERT INTO runtime_flags (key, value_bool, updated_by)
        VALUES ('bgg_family_cascade_enabled', TRUE, 'migration:0019')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM scheduler_configs WHERE job_id = 'bgg_family_refresh'")
    op.execute("DELETE FROM runtime_flags WHERE key = 'bgg_family_cascade_enabled'")
    op.drop_index("ix_bgg_families_fetched_at", table_name="bgg_families")
    op.drop_index("ix_bgg_family_members_bgg_id", table_name="bgg_family_members")
    op.drop_index("ix_bgg_family_members_game", table_name="bgg_family_members")
    op.drop_table("bgg_family_members")
    op.drop_table("bgg_families")
