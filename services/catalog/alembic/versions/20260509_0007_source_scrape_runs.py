"""source_scrape_runs/items + match_profiles + dicefest_raw_games.content_hash

Сервис актуализации источников (ручной detection + dry-run + apply).

Зачем нужны новые таблицы:

- `source_scrape_runs` — изолированные «сухие прогоны» скрапа. Парсер пишет
  СЮДА, а не в `dicefest_raw_games`. Только при явном Apply пользователь
  переносит выбранные items в staging. Если что-то сломалось — отбрасываем
  run целиком (`discard`), не задев основной staging.

- `source_scrape_items` — items run'а: сырой payload + content_hash + change_type
  (`new` / `updated` / `unchanged`) + field_diffs (что именно поменялось).
  Это то, что пользователь видит в RunDiffDrawer.

- `match_profiles` — сохранённые конфигурации матчинга (threshold,
  prefer_external_id, per-field weights). Чтобы оператор не настраивал ползунки
  каждый раз. Уникальный partial-индекс по `(provider) WHERE is_default = true`
  гарантирует ровно один дефолтный профиль на провайдера.

- `dicefest_raw_games.content_hash` — нужна для detection: при следующем
  прогоне сравниваем хеш и сразу видим, изменилась ли карточка. NULLable,
  потому что у уже импортированных записей хеша нет — заполнится при первом
  apply из run'а или одноразовым backfill-скриптом.

Универсальность: таблицы спроектированы провайдер-агностично (`provider`
как varchar). Сейчас наполняется только `dicefest`, в будущем подключим
`bga`, `dicebreaker`, `wikidata` без новых миграций.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ──── source_scrape_runs ──────────────────────────────────────────────
    # Один прогон скрапа. Изолирован от staging-таблиц — переносится в них
    # только через явный apply.
    #
    # status:
    #   running   — фоновая задача всё ещё крутится
    #   ready     — все items записаны, ждёт решения оператора
    #   applied   — выбранные items перенесены в провайдер-специфичный staging
    #   discarded — оператор выкинул прогон (items остаются для аналитики)
    #   failed    — фоновая задача упала, error_message заполнен
    #
    # totals — JSONB с агрегатами: {new, updated, unchanged, total_slugs,
    # errors, applied?}. Раздельные счётчики, чтобы UI не делал N запросов.
    #
    # log_lines — ring-buffer строк прогресса (как в import_jobs.log_lines).
    # Обновляется батчами через LogBuffer.
    op.create_table(
        "source_scrape_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "params",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "totals",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "log_lines",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("performed_by", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_source_scrape_runs_provider_started",
        "source_scrape_runs",
        ["provider", sa.text("started_at DESC")],
    )
    # Точечный индекс для UI «что сейчас крутится / готово к apply».
    # Partial → почти всегда крошечный, не загромождает план.
    op.execute(
        "CREATE INDEX ix_source_scrape_runs_active "
        "ON source_scrape_runs (provider, status) "
        "WHERE status IN ('running', 'ready')"
    )

    # ──── source_scrape_items ─────────────────────────────────────────────
    # payload — DicefestGame как dict (title_ru, title_en, publisher, ...,
    # external_links). raw_html вынесен в отдельную колонку: он крупный
    # (десятки KB на карточку), не нужен для отображения diff'а в UI и
    # тащить его в каждом GET items было бы расточительно.
    #
    # content_hash — sha256 (hex 64 символа) от canonical-JSON значимых
    # полей. Используется для классификации change_type.
    # prev_hash — что было записано в staging до этого прогона (NULL для
    # change_type='new').
    #
    # field_diffs — `{field: {before, after}}` для UI. NULL для change_type
    # in ('new', 'unchanged') — экономим место.
    op.create_table(
        "source_scrape_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("source_scrape_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("prev_hash", sa.CHAR(64), nullable=True),
        sa.Column("change_type", sa.String(16), nullable=False),
        sa.Column("field_diffs", pg.JSONB(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Главный паттерн доступа в UI: «items конкретного run'а с фильтром по
    # change_type» (показываем new+updated, прячем unchanged по дефолту).
    op.create_index(
        "ix_source_scrape_items_run_change",
        "source_scrape_items",
        ["run_id", "change_type"],
    )
    # Поиск по slug внутри run'а — для текстового фильтра в UI.
    op.create_index(
        "ix_source_scrape_items_run_slug",
        "source_scrape_items",
        ["run_id", "slug"],
    )

    # ──── match_profiles ──────────────────────────────────────────────────
    # Сохранённые наборы параметров матчинга для UI. Конфиг хранится одним
    # JSONB, чтобы добавлять параметры без миграций.
    #
    # Структура params:
    #   {
    #     "threshold": 0.6,
    #     "prefer_external_id": true,
    #     "weights": {"ru": 1.0, "en": 1.0, "alias": 1.0}
    #   }
    #
    # is_default — отметка «дефолтный профиль провайдера». Partial UNIQUE
    # гарантирует ровно одного дефолта на провайдера. Без partial обычный
    # UNIQUE падал бы, потому что false дублируется во всех остальных строках.
    op.create_table(
        "match_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("params", pg.JSONB(), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("provider", "name", name="uq_match_profiles_provider_name"),
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_match_profiles_default "
        "ON match_profiles (provider) WHERE is_default = true"
    )

    # ──── dicefest_raw_games.content_hash ─────────────────────────────────
    # NULL у уже существующих записей — заполнится при первом apply
    # содержащем эту запись или одноразовым скриптом
    # `catalog.scripts.backfill_dicefest_hash`.
    op.add_column(
        "dicefest_raw_games",
        sa.Column("content_hash", sa.CHAR(64), nullable=True),
    )
    op.create_index(
        "ix_dicefest_raw_content_hash",
        "dicefest_raw_games",
        ["content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_dicefest_raw_content_hash", table_name="dicefest_raw_games")
    op.drop_column("dicefest_raw_games", "content_hash")

    op.execute("DROP INDEX IF EXISTS ix_match_profiles_default")
    op.drop_table("match_profiles")

    op.drop_index("ix_source_scrape_items_run_slug", table_name="source_scrape_items")
    op.drop_index("ix_source_scrape_items_run_change", table_name="source_scrape_items")
    op.drop_table("source_scrape_items")

    op.execute("DROP INDEX IF EXISTS ix_source_scrape_runs_active")
    op.drop_index(
        "ix_source_scrape_runs_provider_started",
        table_name="source_scrape_runs",
    )
    op.drop_table("source_scrape_runs")
