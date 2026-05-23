"""CAT-17.3: games.title_lemma + GIN trgm индекс.

Денормализованная колонка с лемматизированным названием — закрывает кейс
«Каркассона» (родительный) vs «Каркассон» в pg_trgm. Лемматизация делается
Python'ом через pymorphy3 в:
  - backfill CLI (`catalog/scripts/backfill_title_lemma.py`) — единократный
    прогон для существующих ~162K игр;
  - импортёрах BGG/Wikidata — для новых игр сразу при upsert'е.

В этой миграции **только** ALTER TABLE + индекс. Backfill вынесен в CLI
потому что pymorphy3 на 162K строк = ~10-15 минут, что неприемлемо
блокировать `alembic upgrade head` в Docker startup.

Колонка nullable — graceful degradation: пока backfill не закончен, T1 SQL
просто игнорирует `from_title_lemma` CTE на тех играх где `title_lemma IS NULL`.

Revision ID: 0021
Revises:     0020
Create Date: 2026-05-22
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column("title_lemma", sa.Text(), nullable=True),
    )
    # GIN trgm индекс — точно такой же, как для `title_norm` (миграция 0001),
    # но WHERE title_lemma IS NOT NULL — пока backfill идёт, индекс не
    # содержит мусорных строк.
    op.execute(
        """
        CREATE INDEX ix_games_title_lemma_trgm
        ON games USING GIN (title_lemma gin_trgm_ops)
        WHERE title_lemma IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_games_title_lemma_trgm")
    op.drop_column("games", "title_lemma")
