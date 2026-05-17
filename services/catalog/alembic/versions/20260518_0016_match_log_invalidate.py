"""match_log.offer_id → nullable + добавлена action='invalidate'

Контекст: action `invalidate` (CAT-12) описывает операцию инвалидации
Tier 0 кэша `match_decisions`. Она не привязана к конкретному оферу —
работает на уровне `title_norm` (или фильтра). Существующий
`offer_id NOT NULL` не подходит, делаем nullable.

Existing actions (`auto_t0..auto_t3`, `manual`, `reject`, `unlink`,
`reassess`, `revert`, `t2_progress`, `t3_progress`) всегда имеют
offer_id — null остаётся аномалией, валидируемой на app-слое.

Revision ID: 0016
Revises:     0015
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("match_log", "offer_id", nullable=True)


def downgrade() -> None:
    # Безопасный rollback: сначала почистим строки с NULL offer_id (это
    # invalidate-аудит, который downgrade'у не нужен), потом вернём NOT NULL.
    op.execute("DELETE FROM match_log WHERE offer_id IS NULL")
    op.alter_column("match_log", "offer_id", nullable=False)
