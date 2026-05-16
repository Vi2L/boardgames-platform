"""auto_recovery_rules — таблица правил автоматического восстановления

Часть UX-улучшений `/matching → Очередь` (handoff §D). Правила реагируют на
события в системе и выполняют действия. Пример из домена:

    {
      "name": "qwen-recovery",
      "condition": {"type": "circuit_state", "model": "qwen2.5:7b-instruct", "becomes": "closed"},
      "action":    {"type": "re_enqueue_skipped", "filters": {"reason": ["llm_unavailable"]}},
      "enabled":   true
    }

При срабатывании condition (raise edge — было open/half_open, стало closed)
runner-job в scheduler выполняет action и пишет timestamp в last_triggered_at.

Этот файл — только schema. Runner и frontend CRUD — в коде сервиса. На
момент миграции таблица пустая — никаких сидов, оператор добавляет правила
вручную через UI.

Revision ID: 0014
Revises:     0013
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_recovery_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        # condition — JSONB-полиморфный объект `{type, ...args}`. Tipi:
        #   - circuit_state: {model: str, becomes: 'closed'|'half_open'|'open'}
        #   - job_completed: {type: str ('warmup-embeddings'|...), status: 'done'}
        # Дополняется по мере добавления потребителей.
        sa.Column("condition", JSONB, nullable=False),
        # action — JSONB. Tipi:
        #   - re_enqueue_skipped: {filters?: {reason?, store_slug?}, offer_ids?}
        #   - trigger_job: {job_id: str}
        sa.Column("action", JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_auto_recovery_rules_enabled",
        "auto_recovery_rules",
        ["enabled"],
        postgresql_where=sa.text("enabled = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_auto_recovery_rules_enabled", table_name="auto_recovery_rules")
    op.drop_table("auto_recovery_rules")
