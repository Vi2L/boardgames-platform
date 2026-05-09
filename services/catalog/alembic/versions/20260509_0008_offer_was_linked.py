"""offer.was_linked — флаг возврата оффера из матчинга

Зачем: оператор может ошибиться при ручном матчинге и позже отвязать оффер
от неверной игры через POST /matching/{id}/unlink. Флаг was_linked=True
позволяет очереди матчинга выдавать такие офферы выше остальных —
чтобы оператор сразу видел, что это «повторный» случай, требующий внимания.

Revision ID: 0008
Revises:     0007
Create Date: 2026-05-09
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offers",
        sa.Column(
            "was_linked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("offers", "was_linked")
