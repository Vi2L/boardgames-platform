"""scheduler_configs сид для auto_recovery_runner (CAT-4.5)

Регистрирует новый interval-job `auto_recovery_runner` в
`scheduler_configs`. Job читает enabled rules из `auto_recovery_rules`
(миграция 0014) каждые 60 секунд и выполняет actions.

`cron_expr` не используется для interval-jobs (resolver в
`catalog/scheduler.py` смотрит на `params.interval_sec`), но колонка
NOT NULL — кладём placeholder.

Revision ID: 0017
Revises:     0016
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO scheduler_configs (job_id, cron_expr, enabled, params)
        VALUES (
            'auto_recovery_runner',
            '* * * * *',
            TRUE,
            '{"interval_sec": 60}'::jsonb
        )
        ON CONFLICT (job_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM scheduler_configs WHERE job_id = 'auto_recovery_runner'"
    )
