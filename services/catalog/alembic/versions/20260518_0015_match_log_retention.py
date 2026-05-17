"""scheduler_configs сид для match_log_retention job

Добавляет cron-задачу retention для match_log. Действующая логика —
в `catalog/matching/v2/auditor.py:evict_older_than`, scheduler-handler —
в `catalog/scheduler.py`. По умолчанию запускается ежедневно в 02:00 UTC
и удаляет записи match_log старше MATCH_LOG_RETENTION_DAYS=90 дней,
сохраняя не-реверченные (`reverted_at IS NULL AND action != 'revert'`).

ON CONFLICT DO NOTHING — повторный прогон или ручная правка cron'а
не перезатираются миграцией.

Revision ID: 0015
Revises:     0014
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Сид: ежедневно в 02:00 UTC, retention_days = 90 (override через
    # Settings.match_log_retention_days, scheduler-handler читает env).
    op.execute("""
        INSERT INTO scheduler_configs (job_id, cron_expr, enabled, params)
        VALUES (
            'match_log_retention',
            '0 2 * * *',
            TRUE,
            '{"retention_days": 90}'::jsonb
        )
        ON CONFLICT (job_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM scheduler_configs WHERE job_id = 'match_log_retention'"
    )
