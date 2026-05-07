"""dicefest staging + ImportJob progress/log_lines

Two changes in one migration (cohesive — обе нужны для PR-1 «парсер dicefest»):

1) ALTER TABLE import_jobs:
   + progress  jsonb   — {phase, current, total, current_title}, обновляется
                         батчами через _log_buffer.LogBuffer (раз в ~20 строк
                         или 2 секунды) — иначе UPDATE на каждую игру даёт
                         row-level lock + WAL-bloat.
   + log_lines jsonb   — array строк, ring-buffer ~200 последних. Tail для
                         debug-портала через polling (БЕЗ SSE — паттерн
                         совместим с ImportWizard.tsx:57-67).

   Полезно не только dicefest, но и BGG/Tesera импортёрам — переход на
   расширенный формат result автоматически.

2) CREATE TABLE dicefest_raw_games — staging для парсера dicefest.ru.

   Двухстадийность по требованию пользователя: парсинг наполняет ТОЛЬКО эту
   таблицу, основная games/game_aliases не трогается. Промоушен — отдельный
   управляемый процесс в PR-2 через UI.

   Колонки:
     - slug UNIQUE — re-run импорта обновляет ту же запись (ON CONFLICT DO UPDATE).
     - raw_html — сырой HTML карточки. Хранится отдельно от raw JSONB, чтобы
       можно было перепарсить при изменении селекторов БЕЗ повторного запроса
       к dicefest. Cleanup/TTL — отдельной задачей при ~10K записей.
     - raw jsonb — структурированный дамп вытащенных полей (страховка от
       потери данных при изменениях парсера).
     - status: new | promoted | skipped | rejected — workflow для промоушена.
     - title_ru/title_en — оба индексированы trigram'ом для pg_trgm matching
       в промоушене (точно так же как games.title_norm).

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1) import_jobs: progress + log_lines ---
    op.add_column(
        "import_jobs",
        sa.Column("progress", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "import_jobs",
        sa.Column("log_lines", postgresql.JSONB(), nullable=True),
    )

    # --- 2) dicefest_raw_games (staging) ---
    op.create_table(
        "dicefest_raw_games",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("title_ru", sa.Text(), nullable=True),
        sa.Column("title_en", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("release_month", sa.Integer(), nullable=True),
        sa.Column("release_status", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column(
            "raw",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_listing", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # workflow для промоушена (PR-2)
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'new'"),
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "promoted_to_game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_dicefest_raw_status",
        "dicefest_raw_games",
        ["status"],
    )
    # Trigram-индексы для матчинга в промоушене. lower() — потому что pg_trgm
    # case-sensitive, а title_ru/_en хранятся в исходном регистре.
    op.execute(
        "CREATE INDEX ix_dicefest_raw_title_ru_trgm "
        "ON dicefest_raw_games USING gin (lower(title_ru) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_dicefest_raw_title_en_trgm "
        "ON dicefest_raw_games USING gin (lower(title_en) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dicefest_raw_title_en_trgm")
    op.execute("DROP INDEX IF EXISTS ix_dicefest_raw_title_ru_trgm")
    op.drop_index("ix_dicefest_raw_status", table_name="dicefest_raw_games")
    op.drop_table("dicefest_raw_games")
    op.drop_column("import_jobs", "log_lines")
    op.drop_column("import_jobs", "progress")
