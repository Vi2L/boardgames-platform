"""games extensions: kind/parent_game_id/ru-локализация/external IDs + offers.sku/in_stock/...

Расширение каталога:

games:
  - kind                 — тип игры (base / expansion / promo / accessory).
                           Default 'base'. is_expansion из game_bgg → 'expansion'
                           при backfill.
  - parent_game_id       — self-FK на базовую игру. Заполняется вручную через
                           админку (автоматизация — отдельная задача).
  - ru_publisher         — российский локализатор (Hobby World, Crowd Games, ...).
                           Backfill из game_dicefest.publisher.
  - ru_release_year      — год релиза в РФ (≠ year оригинала).
  - is_localized_ru      — флаг наличия русской локализации.
                           True для всех с promoted dicefest или ru_publisher.
  - preorder_price       — цена предзаказа (копейки). Backfill из game_dicefest.
  - dicefest_id          — id из dicefest_raw_games (без жёсткого FK — staging
                           может быть очищен). Partial UNIQUE WHERE NOT NULL.
  - nastolio_id          — slug nastolio.ru. Backfill из
                           game_dicefest.external_links[kind='nastolio'].
                           Partial UNIQUE WHERE NOT NULL.

offers:
  - sku                  — внутренний артикул магазина. Backfill из
                           raw_extra->>'sku' (HobbyGames пишет туда).
  - in_stock             — нормализованный флаг наличия. Backfill из
                           raw_extra->>'availability' (HobbyGames bool) и
                           raw_extra->>'in_stock' (Crowd Games bool).
  - original_price       — цена до скидки в копейках. Backfill из
                           raw_extra->>'original_price' (HobbyGames).
  - is_preorder          — флаг предзаказа. Пока null до соответствующих
                           обновлений парсеров.

Все backfill'ы делаются под одним server_default или через UPDATE ... FROM
до ALTER ... SET NOT NULL — чтобы существующие строки не падали с
NOT NULL constraint violation.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ──── games: новые колонки ────────────────────────────────────────────
    # kind и is_localized_ru с server_default — существующие строки сразу
    # получают валидное значение, поэтому NOT NULL ставим сразу.
    op.add_column(
        "games",
        sa.Column(
            "kind",
            sa.String(16),
            nullable=False,
            server_default="base",
        ),
    )
    op.add_column(
        "games",
        sa.Column(
            "parent_game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("games", sa.Column("ru_publisher", sa.Text(), nullable=True))
    op.add_column("games", sa.Column("ru_release_year", sa.Integer(), nullable=True))
    op.add_column(
        "games",
        sa.Column(
            "is_localized_ru",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("games", sa.Column("preorder_price", sa.BigInteger(), nullable=True))
    op.add_column("games", sa.Column("dicefest_id", sa.BigInteger(), nullable=True))
    op.add_column("games", sa.Column("nastolio_id", sa.Text(), nullable=True))

    # ──── games: индексы ──────────────────────────────────────────────────
    op.create_index("ix_games_kind", "games", ["kind"])
    op.create_index("ix_games_parent_game_id", "games", ["parent_game_id"])
    # Partial-UNIQUE: NULL-значений много, indexer не должен на них
    # ругаться. WHERE ... IS NOT NULL поддерживается только сырым SQL.
    op.execute(
        "CREATE UNIQUE INDEX ix_games_dicefest_id ON games (dicefest_id) "
        "WHERE dicefest_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_games_nastolio_id ON games (nastolio_id) "
        "WHERE nastolio_id IS NOT NULL"
    )

    # ──── offers: новые колонки ───────────────────────────────────────────
    op.add_column("offers", sa.Column("sku", sa.String(64), nullable=True))
    op.add_column("offers", sa.Column("in_stock", sa.Boolean(), nullable=True))
    op.add_column("offers", sa.Column("original_price", sa.BigInteger(), nullable=True))
    op.add_column("offers", sa.Column("is_preorder", sa.Boolean(), nullable=True))

    op.execute(
        "CREATE INDEX ix_offers_in_stock ON offers (in_stock) "
        "WHERE in_stock IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_offers_is_preorder ON offers (is_preorder) "
        "WHERE is_preorder = true"
    )

    # ──── BACKFILL ────────────────────────────────────────────────────────

    # 1) games.kind ← 'expansion' для всех с game_bgg.is_expansion = true.
    #    Пока единственная не-base категория, которую мы знаем.
    op.execute(
        """
        UPDATE games g
        SET kind = 'expansion'
        FROM game_bgg b
        WHERE b.game_id = g.id AND b.is_expansion = true
        """
    )

    # 2) games.{ru_publisher, preorder_price, dicefest_id, is_localized_ru}
    #    ← из game_dicefest. Если у игры несколько satellite-записей
    #    (переиздания), берём самую свежую по fetched_at.
    op.execute(
        """
        UPDATE games g
        SET ru_publisher = sub.publisher,
            preorder_price = sub.preorder_price,
            dicefest_id = sub.raw_id,
            is_localized_ru = true
        FROM (
            SELECT DISTINCT ON (game_id)
                game_id, publisher, preorder_price, raw_id, fetched_at
            FROM game_dicefest
            ORDER BY game_id, fetched_at DESC
        ) sub
        WHERE g.id = sub.game_id
          AND (sub.publisher IS NOT NULL OR sub.preorder_price IS NOT NULL)
        """
    )

    # 3) games.nastolio_id ← из game_dicefest.external_links[kind='nastolio'].
    #    JSONB с массивом — раскрываем через jsonb_array_elements.
    #    Берём первую найденную ссылку на nastolio. external_id может быть
    #    null (парсер не всегда выделяет slug) — тогда фолбэк на сам URL.
    op.execute(
        """
        UPDATE games g
        SET nastolio_id = sub.nastolio_id
        FROM (
            SELECT DISTINCT ON (gd.game_id)
                gd.game_id,
                COALESCE(link->>'external_id', link->>'url') AS nastolio_id
            FROM game_dicefest gd,
                 jsonb_array_elements(gd.external_links) AS link
            WHERE link->>'kind' = 'nastolio'
              AND COALESCE(link->>'external_id', link->>'url') IS NOT NULL
            ORDER BY gd.game_id, gd.fetched_at DESC
        ) sub
        WHERE g.id = sub.game_id AND g.nastolio_id IS NULL
        """
    )

    # 4) offers.sku ← raw_extra->>'sku' (только HobbyGames пишет это поле).
    op.execute(
        """
        UPDATE offers
        SET sku = raw_extra->>'sku'
        WHERE raw_extra ? 'sku' AND raw_extra->>'sku' IS NOT NULL
        """
    )

    # 5) offers.in_stock ← raw_extra. HobbyGames кладёт под ключом
    #    'availability' (boolean), Crowd Games — 'in_stock' (boolean).
    #    JSONB ->> возвращает text, поэтому сравниваем со строкой.
    op.execute(
        """
        UPDATE offers
        SET in_stock = CASE
            WHEN raw_extra->>'availability' = 'true' THEN true
            WHEN raw_extra->>'availability' = 'false' THEN false
            WHEN raw_extra->>'in_stock' = 'true' THEN true
            WHEN raw_extra->>'in_stock' = 'false' THEN false
            ELSE NULL
        END
        WHERE raw_extra ? 'availability' OR raw_extra ? 'in_stock'
        """
    )

    # 6) offers.original_price ← raw_extra->>'original_price'.
    #    Числовой → CAST. Защищаемся try-cast: если кривое значение, NULL.
    op.execute(
        """
        UPDATE offers
        SET original_price = NULLIF(raw_extra->>'original_price', '')::bigint
        WHERE raw_extra ? 'original_price'
          AND raw_extra->>'original_price' ~ '^[0-9]+$'
        """
    )


def downgrade() -> None:
    # ── offers ──
    op.drop_index("ix_offers_is_preorder", table_name="offers")
    op.drop_index("ix_offers_in_stock", table_name="offers")
    op.drop_column("offers", "is_preorder")
    op.drop_column("offers", "original_price")
    op.drop_column("offers", "in_stock")
    op.drop_column("offers", "sku")

    # ── games ──
    op.drop_index("ix_games_nastolio_id", table_name="games")
    op.drop_index("ix_games_dicefest_id", table_name="games")
    op.drop_index("ix_games_parent_game_id", table_name="games")
    op.drop_index("ix_games_kind", table_name="games")
    op.drop_column("games", "nastolio_id")
    op.drop_column("games", "dicefest_id")
    op.drop_column("games", "preorder_price")
    op.drop_column("games", "is_localized_ru")
    op.drop_column("games", "ru_release_year")
    op.drop_column("games", "ru_publisher")
    op.drop_column("games", "parent_game_id")
    op.drop_column("games", "kind")
