"""satellite schema: game_bgg, game_wikidata + game_aliases extension

Phase 1 плана `~/.claude/plans/woolly-wobbling-simon.md`. Применяем
satellite-pattern по образцу board_game_db: каждый внешний источник
живёт в своей таблице с «жёсткими» полями + raw jsonb + fetched_at.

- game_bgg (1:1 с games через game_id) — BGG ranks/scores и поля XML API.
- game_wikidata (1:1) — SPARQL labels/aliases/descriptions.
- game_aliases.language + verified — расширение для отслеживания локалей и
  ручных подтверждений.

Миграция чисто схемная; данные из games.meta.bgg_ranks → game_bgg переезжают
отдельным скриптом catalog.scripts.migrate_meta_to_satellites (Phase 2).

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- game_bgg ---
    op.create_table(
        "game_bgg",
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("bgg_id", sa.Integer(), nullable=False),
        # ranks-выгрузка
        sa.Column("rank", sa.Integer()),
        sa.Column("bayes_average", sa.Float()),
        sa.Column("average", sa.Float()),
        sa.Column("users_rated", sa.Integer()),
        sa.Column("is_expansion", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subtype_ranks", postgresql.JSONB()),
        # XML API
        sa.Column("description", sa.Text()),
        sa.Column("designers", postgresql.ARRAY(sa.Text())),
        sa.Column("artists", postgresql.ARRAY(sa.Text())),
        sa.Column("publishers", postgresql.ARRAY(sa.Text())),
        sa.Column("mechanics", postgresql.ARRAY(sa.Text())),
        sa.Column("categories", postgresql.ARRAY(sa.Text())),
        sa.Column("min_players", sa.Integer()),
        sa.Column("max_players", sa.Integer()),
        sa.Column("min_age", sa.Integer()),
        sa.Column("playtime_min", sa.Integer()),
        sa.Column("playtime_max", sa.Integer()),
        sa.Column("image_url", sa.Text()),
        sa.Column("thumbnail_url", sa.Text()),
        # аудит
        sa.Column(
            "raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("source", sa.String(32)),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint("uq_game_bgg_bgg_id", "game_bgg", ["bgg_id"])
    op.execute(
        "CREATE INDEX ix_game_bgg_rank ON game_bgg(rank) WHERE rank IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_game_bgg_bayes ON game_bgg(bayes_average) "
        "WHERE bayes_average IS NOT NULL"
    )

    # --- game_wikidata ---
    op.create_table(
        "game_wikidata",
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("bgg_id", sa.Integer()),
        sa.Column("entity_id", sa.String(32)),
        sa.Column("found", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "labels",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "aliases",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "descriptions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("matched_entities", postgresql.ARRAY(sa.Text())),
        sa.Column(
            "raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint("uq_game_wikidata_bgg_id", "game_wikidata", ["bgg_id"])
    op.create_index("ix_game_wikidata_entity", "game_wikidata", ["entity_id"])
    op.create_index("ix_game_wikidata_fetched", "game_wikidata", ["fetched_at"])
    # GIN на ru-aliases — для быстрых @> / ? operator-запросов вида
    # `aliases->'ru' ? 'Каркассон'`. Делаем expression-индекс по конкретному ключу,
    # чтобы не тянуть весь jsonb.
    op.execute(
        "CREATE INDEX ix_game_wikidata_aliases_ru_gin ON game_wikidata "
        "USING gin ((aliases->'ru'))"
    )

    # --- game_aliases extension ---
    op.add_column("game_aliases", sa.Column("language", sa.String(8), nullable=True))
    op.add_column(
        "game_aliases",
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("game_aliases", "verified")
    op.drop_column("game_aliases", "language")
    op.execute("DROP INDEX IF EXISTS ix_game_wikidata_aliases_ru_gin")
    op.drop_index("ix_game_wikidata_fetched", table_name="game_wikidata")
    op.drop_index("ix_game_wikidata_entity", table_name="game_wikidata")
    op.drop_table("game_wikidata")
    op.execute("DROP INDEX IF EXISTS ix_game_bgg_bayes")
    op.execute("DROP INDEX IF EXISTS ix_game_bgg_rank")
    op.drop_table("game_bgg")
