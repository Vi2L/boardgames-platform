"""scheduler_configs + bgg_geeklists — DB-stored cron + GeekList snapshots

Две таблицы для подсистемы BGG Sync UI ([CAT-3]):

1. **scheduler_configs** — runtime-конфиг APScheduler-job'ов в БД. Раньше cron жил
   в Settings (env-переменные); теперь UI может править его без рестарта сервиса.
   `params` JSONB — provider-специфичные параметры (rank_le, batch_size, ...).
   `last_run_*` — денормализация для UI: чтобы листинг job'ов не делал JOIN с
   import_jobs + MAX по типу. Обновляется из роутера `/scheduler/jobs/{id}/trigger`.

2. **bgg_geeklists** — snapshot'ы кураторских BGG GeekList-ов
   (https://boardgamegeek.com/xmlapi2/geeklist/{id}). Универсальный механизм для
   monthly «BGG Top 50 Most Played» и любых других списков.
   `items` хранится как JSONB-массив (в отличие от `bgg_hotness` где per-item
   строка): GeekList произвольной длины (50–1000), per-item индексация не нужна,
   auto-import делается в момент загрузки.

Revision ID: 0010
Revises:     0009
Create Date: 2026-05-10
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── scheduler_configs ────────────────────────────────────────────────────
    op.create_table(
        "scheduler_configs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("cron_expr", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        # params: provider-специфика (rank_le, skip_recent_days, batch_size, geeklist_id...).
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Денормализация: ссылка на последний ImportJob этого типа.
        # Не FK — job-row может быть удалён ретенцией, тогда last_run_* станет stale.
        sa.Column("last_run_job_id", sa.BigInteger(), nullable=True),
        sa.Column("last_run_status", sa.String(16), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Сид дефолтов: три job'а из текущей конфигурации Settings.
    # ON CONFLICT DO NOTHING — повторный прогон миграции не должен переписывать
    # пользовательские правки cron'а.
    op.execute("""
        INSERT INTO scheduler_configs (job_id, cron_expr, enabled, params)
        VALUES
            ('bgg_top_sync',     '0 3 * * 1', TRUE, '{"rank_le": 1000, "skip_recent_days": 7}'::jsonb),
            ('bgg_hotness_sync', '0 6 * * *', TRUE, '{"auto_import": true}'::jsonb),
            ('bgg_mini_batch',   '0 4 * * *', TRUE, '{"batch_size": 500, "skip_recent_days": 30, "rate_limit_sec": 2.0}'::jsonb)
        ON CONFLICT (job_id) DO NOTHING
    """)

    # ── bgg_geeklists ────────────────────────────────────────────────────────
    op.create_table(
        "bgg_geeklists",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("geeklist_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("username", sa.Text(), nullable=True),  # owner на BGG
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        # items: [{rank, bgg_id, name, year, thumbnail_url, body, game_id?}, ...]
        sa.Column("items", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("geeklist_id", "snapshot_date", name="uq_bgg_geeklist_date"),
    )
    op.create_index("ix_bgg_geeklists_geeklist_id", "bgg_geeklists", ["geeklist_id"])
    op.create_index("ix_bgg_geeklists_snapshot_date", "bgg_geeklists", ["snapshot_date"])


def downgrade() -> None:
    op.drop_index("ix_bgg_geeklists_snapshot_date", table_name="bgg_geeklists")
    op.drop_index("ix_bgg_geeklists_geeklist_id", table_name="bgg_geeklists")
    op.drop_table("bgg_geeklists")
    op.drop_table("scheduler_configs")
