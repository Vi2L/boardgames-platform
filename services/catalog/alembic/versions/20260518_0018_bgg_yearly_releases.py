"""scheduler_configs сид для bgg_yearly_releases (CAT-10)

Регистрирует новый cron-job `bgg_yearly_releases`. Job скрейпит HTML-страницы
`boardgamegeek.com/browse/boardgame?yearpublished=YYYY&sort=numvoters`, для
отсутствующих в catalog bgg_id запускает enrich_one.

Дефолт: 1-е число каждого месяца, 02:00 UTC. `year` в params не задан —
runtime резолвится в текущий UTC-год.

Revision ID: 0018
Revises:     0017
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `year: null` оставляет job'у возможность резолвить runtime UTC год —
    # один раз сеяли, а Январь 2027 не требует ручной правки params.
    op.execute("""
        INSERT INTO scheduler_configs (job_id, cron_expr, enabled, params)
        VALUES (
            'bgg_yearly_releases',
            '0 2 1 * *',
            TRUE,
            '{"year": null, "max_pages": 5}'::jsonb
        )
        ON CONFLICT (job_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM scheduler_configs WHERE job_id = 'bgg_yearly_releases'"
    )
