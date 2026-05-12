"""bgg stats extension — расширенная статистика и polls из BGG XML

Добавляет в `game_bgg` 6 колонок (все NULL — заполняются при следующем
XML-обогащении через `POST /import/bgg/batch`):

- `average_weight FLOAT` — complexity 1.00–5.00 из <statistics><averageweight>.
- `num_weights INTEGER` — сколько пользователей оценили complexity.
- `recommended_players JSONB` — raw подсчёты per player count из
  <poll name="suggested_numplayers">. Структура:
  `{"2": {"best": 100, "recommended": 200, "not_recommended": 50}, "6+": {...}}`.
- `recommended_age INTEGER` — winning value из <poll name="suggested_playerage">.
  Bucket "21 and up" хранится как 21. Tie → min.
- `language_dependence INTEGER` — winning level (1–5) из
  <poll name="language_dependence">. Tie → min (консервативно). Тип Integer
  (а не SmallInteger) — для консистентности с другими числовыми полями game_bgg.
- `bgg_stats_updated_at TIMESTAMPTZ` — timestamp последнего XML-обогащения.
  NULL означает «игра только в CSV». Используется в enrich_batch для
  приоритизации необогащённых игр (отдельно от `fetched_at`, который
  трогает любой upsert).

Связанные изменения вне миграции:
- `import_bgg_ranks.py` исключает `source`, `raw`, `fetched_at` из ON CONFLICT
  set_ — CSV больше не перетирает данные XML-обогащения.
- `upsert_bgg_data` теперь перезаписывает `bayes_average`/`average`/
  `users_rated` (XML — источник истины) и заполняет `raw = {parsed, xml}`.

Revision ID: 0012
Revises:     0011
Create Date: 2026-05-12
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_bgg", sa.Column("average_weight", sa.Float(), nullable=True))
    op.add_column("game_bgg", sa.Column("num_weights", sa.Integer(), nullable=True))
    op.add_column("game_bgg", sa.Column("recommended_players", JSONB(), nullable=True))
    op.add_column("game_bgg", sa.Column("recommended_age", sa.Integer(), nullable=True))
    op.add_column("game_bgg", sa.Column("language_dependence", sa.Integer(), nullable=True))
    op.add_column(
        "game_bgg",
        sa.Column("bgg_stats_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("game_bgg", "bgg_stats_updated_at")
    op.drop_column("game_bgg", "language_dependence")
    op.drop_column("game_bgg", "recommended_age")
    op.drop_column("game_bgg", "recommended_players")
    op.drop_column("game_bgg", "num_weights")
    op.drop_column("game_bgg", "average_weight")
