"""dicefest schema refinements: убрать release_year/_month, добавить preorder_price и external_links

Уточнения после live-парсинга 907 записей:

1) release_year/release_month относятся к ВЫХОДУ РУССКОЙ ВЕРСИИ (РФ-релиз),
   что не совпадает с games.year (год оригинала). Убираем оба, чтобы не
   вводить в заблуждение при матчинге. Исходный текст («2 половина 2026»)
   остаётся в raw['release_text'].

2) Новые поля для будущего обогащения canonical БД:
   - preorder_price (BIGINT, копейки) — из «Цена на предзаказе: 1990 руб»
   - external_links (JSONB array) — ссылки на BGG / Tesera / Nastolio /
     магазины, собранные из game-popup-feature__icon--link блоков.
     Shape: [{kind, url, label, external_id?}].

Изменения синхронны для staging (dicefest_raw_games) и satellite (game_dicefest).

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- staging ---
    op.drop_column("dicefest_raw_games", "release_year")
    op.drop_column("dicefest_raw_games", "release_month")
    op.add_column(
        "dicefest_raw_games",
        sa.Column("preorder_price", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "dicefest_raw_games",
        sa.Column(
            "external_links",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # --- satellite ---
    op.drop_column("game_dicefest", "release_year")
    op.drop_column("game_dicefest", "release_month")
    op.add_column(
        "game_dicefest",
        sa.Column("preorder_price", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "game_dicefest",
        sa.Column(
            "external_links",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("game_dicefest", "external_links")
    op.drop_column("game_dicefest", "preorder_price")
    op.add_column("game_dicefest", sa.Column("release_month", sa.Integer(), nullable=True))
    op.add_column("game_dicefest", sa.Column("release_year", sa.Integer(), nullable=True))

    op.drop_column("dicefest_raw_games", "external_links")
    op.drop_column("dicefest_raw_games", "preorder_price")
    op.add_column("dicefest_raw_games", sa.Column("release_month", sa.Integer(), nullable=True))
    op.add_column("dicefest_raw_games", sa.Column("release_year", sa.Integer(), nullable=True))
