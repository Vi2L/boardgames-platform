"""initial schema

Создаёт всю схему каталога: games, game_aliases, offers, offer_prices,
import_jobs, api_keys. Плюс инфраструктуру для fuzzy-search:

- IMMUTABLE-обёртка `immutable_unaccent` над `unaccent` — публичная функция
  unaccent помечена как STABLE, а в generated column можно ссылаться только
  на IMMUTABLE-функции. Стандартный обходной путь: declare custom wrapper.
- Generated stored columns `*_norm` поверх `lower(immutable_unaccent(...))`.
- GIN-индексы по триграммам (`gin_trgm_ops`) на `*_norm` для оператора `%`
  и similarity().

Расширения `pg_trgm` и `unaccent` уже включены init.sql'ом infra-репо при
первом старте контейнера, так что CREATE EXTENSION IF NOT EXISTS — на всякий случай.

Эта миграция написана **вручную**, не через autogenerate: alembic revision
--autogenerate не видит generated columns, custom-функции и GIN-индексы
с opclass'ами.

Revision ID: 0001
Revises:
Create Date: 2026-05-07
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширения — на случай чистой БД без init.sql.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    # IMMUTABLE-обёртка. unaccent('public.unaccent', text) детерминирован,
    # потому что мы передаём словарь явно.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION immutable_unaccent(text)
        RETURNS text AS $$
            SELECT public.unaccent('public.unaccent', $1)
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE
        """
    )

    # --- games ---
    op.create_table(
        "games",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "title_norm",
            sa.Text(),
            sa.Computed("lower(immutable_unaccent(title))", persisted=True),
        ),
        sa.Column("year", sa.Integer()),
        sa.Column("designers", postgresql.ARRAY(sa.Text())),
        sa.Column("publishers", postgresql.ARRAY(sa.Text())),
        sa.Column("players_min", sa.Integer()),
        sa.Column("players_max", sa.Integer()),
        sa.Column("age_min", sa.Integer()),
        sa.Column("playtime_min", sa.Integer()),
        sa.Column("playtime_max", sa.Integer()),
        sa.Column("bgg_id", sa.Integer()),
        sa.Column("tesera_id", sa.Integer()),
        sa.Column("cover_url", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("meta", postgresql.JSONB()),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint("uq_games_slug", "games", ["slug"])
    op.create_unique_constraint("uq_games_bgg_id", "games", ["bgg_id"])
    op.create_unique_constraint("uq_games_tesera_id", "games", ["tesera_id"])
    op.create_index("ix_games_status", "games", ["status"])
    op.execute(
        "CREATE INDEX ix_games_title_norm_trgm ON games "
        "USING gin (title_norm gin_trgm_ops)"
    )

    # --- game_aliases ---
    op.create_table(
        "game_aliases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column(
            "alias_norm",
            sa.Text(),
            sa.Computed("lower(immutable_unaccent(alias))", persisted=True),
        ),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_game_aliases_game_id", "game_aliases", ["game_id"])
    op.create_unique_constraint(
        "uq_alias_per_game", "game_aliases", ["game_id", "alias_norm"]
    )
    op.execute(
        "CREATE INDEX ix_game_aliases_alias_norm_trgm ON game_aliases "
        "USING gin (alias_norm gin_trgm_ops)"
    )

    # --- offers ---
    op.create_table(
        "offers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
        ),
        sa.Column("store_slug", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title_raw", sa.Text(), nullable=False),
        sa.Column(
            "title_raw_norm",
            sa.Text(),
            sa.Computed("lower(immutable_unaccent(title_raw))", persisted=True),
        ),
        sa.Column("image_url", sa.Text()),
        sa.Column("last_price", sa.BigInteger()),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "match_status", sa.String(16), nullable=False, server_default="unmatched"
        ),
        sa.Column("match_score", sa.Float()),
        sa.Column("raw_extra", postgresql.JSONB()),
    )
    op.create_unique_constraint(
        "uq_offer_store_external", "offers", ["store_slug", "external_id"]
    )
    op.create_index("ix_offers_game_id", "offers", ["game_id"])
    op.create_index("ix_offers_store_slug", "offers", ["store_slug"])
    op.create_index("ix_offers_match_status", "offers", ["match_status"])
    op.execute(
        "CREATE INDEX ix_offers_title_raw_norm_trgm ON offers "
        "USING gin (title_raw_norm gin_trgm_ops)"
    )

    # --- offer_prices ---
    op.create_table(
        "offer_prices",
        sa.Column(
            "offer_id",
            sa.BigInteger(),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            primary_key=True,
            server_default=sa.func.now(),
        ),
        sa.Column("price", sa.BigInteger(), nullable=False),
    )

    # --- import_jobs ---
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("result", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_import_jobs_type", "import_jobs", ["type"])
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"])

    # --- api_keys ---
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_unique_constraint("uq_api_keys_key_hash", "api_keys", ["key_hash"])


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("import_jobs")
    op.drop_table("offer_prices")
    op.execute("DROP INDEX IF EXISTS ix_offers_title_raw_norm_trgm")
    op.drop_table("offers")
    op.execute("DROP INDEX IF EXISTS ix_game_aliases_alias_norm_trgm")
    op.drop_table("game_aliases")
    op.execute("DROP INDEX IF EXISTS ix_games_title_norm_trgm")
    op.drop_table("games")
    op.execute("DROP FUNCTION IF EXISTS immutable_unaccent(text)")
    # pg_trgm и unaccent не дропаем — они общие для БД.
