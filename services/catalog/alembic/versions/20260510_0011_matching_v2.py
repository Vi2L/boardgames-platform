"""matching v2 — pgvector + outbox + audit log + decisions cache + title_ru

Базовая схема для нового матчера:

1. **pgvector extension**: `CREATE EXTENSION IF NOT EXISTS vector` для cosine
   similarity поиска. Дублируется в `infra/postgres/init.sql` для свежих volumes.

2. **games.title_ru** — first-class колонка вместо вычисляемой на лету.
   Денормализуется из лучшего ru-alias скриптом backfill_title_ru.py и при
   ingest промоушене/manual link. Включается в text для embedding'а.

3. **offers.{predicted_kind, match_tier, match_reason}** — диагностические
   поля нового матчера. tier (0..3) показывает какой tier дал результат;
   reason — текстовое объяснение для UI («cache_hit», «vec_confident», ...).
   predicted_kind заполняется LLM-арбитром (T3) для классификации товара.

4. **match_decisions** — Tier-0 кэш «нормализованный title → game_id».
   Хранит TTL per source: manual=∞, t1=30 дней, t2=14, t3=7. Tier 0 проверяет
   только записи в TTL. Удаляется при unlink/reject/revert через FK CASCADE.

5. **match_log** — аудит каждого изменения offers.game_id. Запись через
   service-слой (engine/router), не триггер — это даёт нам performed_by,
   action, prev/new pair. Поддержка bulk-revert через batch_id (UUID).

6. **match_queue** — outbox для async tier'ов (T2/T3). Hочему отдельная
   таблица а не флаг в offers: retry с exponential backoff, priority,
   observability через SQL, естественное масштабирование worker'ов.
   FOR UPDATE SKIP LOCKED — стандартный паттерн PG-очереди.

7. **game_embeddings** — vector(1024) от bge-m3. Отдельная таблица (а не
   колонка в games), потому что 4KB/строка × 162K = 650MB heap bloat
   неприемлем для основной таблицы. HNSW индекс с m=16, ef_construction=128.
   text_used хранит точную строку, поданную в модель — для отладки и
   реиндексации после смены модели.

Revision ID: 0011
Revises:     0010
Create Date: 2026-05-10
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pgvector extension (idempotent для существующих volumes) ──────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── games.title_ru ────────────────────────────────────────────────────────
    op.add_column("games", sa.Column("title_ru", sa.Text(), nullable=True))
    # Индекс для поиска по русскому названию (UI search)
    op.execute(
        "CREATE INDEX ix_games_title_ru_trgm "
        "ON games USING gin (lower(immutable_unaccent(title_ru)) gin_trgm_ops) "
        "WHERE title_ru IS NOT NULL"
    )

    # ── offers новые поля ─────────────────────────────────────────────────────
    op.add_column("offers", sa.Column("predicted_kind", sa.String(16), nullable=True))
    op.add_column("offers", sa.Column("match_tier", sa.SmallInteger(), nullable=True))
    op.add_column("offers", sa.Column("match_reason", sa.Text(), nullable=True))

    # ── match_decisions: Tier-0 кэш ────────────────────────────────────────────
    op.create_table(
        "match_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title_norm", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=True,  # NULL = "это не игра" (negative cache)
        ),
        sa.Column("source", sa.String(16), nullable=False),  # 'manual'|'auto_t1'|'auto_t2'|'auto_t3'
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("tier", sa.SmallInteger(), nullable=True),
        # NULL = бессрочно (manual). Иначе age проверяется в SELECT.
        sa.Column("ttl_days", sa.Integer(), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_match_decisions_game_id", "match_decisions", ["game_id"])

    # ── match_log: аудит изменений offers.game_id/match_status ─────────────────
    op.create_table(
        "match_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "offer_id",
            sa.BigInteger(),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prev_game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "new_game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prev_status", sa.String(16), nullable=True),
        sa.Column("new_status", sa.String(16), nullable=False),
        # 'auto_t0'|'auto_t1'|'auto_t2'|'auto_t3'|'manual'|'reject'|'unlink'|'reassess'|'revert'
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        # Группировка для bulk-revert: все офферы одного reassess получают общий UUID.
        # NULL для индивидуальных операций (manual link, single reassess).
        sa.Column("batch_id", UUID(as_uuid=True), nullable=True),
        # Связанный alias, добавленный при auto/manual matching. NULL если алиас
        # не создавался. При revert с delete_alias=True — удаляем эту строку.
        sa.Column(
            "alias_created_id",
            sa.BigInteger(),
            sa.ForeignKey("game_aliases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("performed_by", sa.Text(), nullable=True),
        sa.Column(
            "performed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by", sa.Text(), nullable=True),
    )
    op.create_index("ix_match_log_offer_id", "match_log", ["offer_id"])
    op.create_index(
        "ix_match_log_batch_id",
        "match_log",
        ["batch_id"],
        postgresql_where=sa.text("batch_id IS NOT NULL"),
    )
    op.create_index(
        "ix_match_log_performed_at",
        "match_log",
        [sa.text("performed_at DESC")],
    )

    # ── match_queue: outbox для async-tier'ов ──────────────────────────────────
    op.create_table(
        "match_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "offer_id",
            sa.BigInteger(),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Денормализация для фильтрации без JOIN с offers.
        sa.Column("store_slug", sa.String(64), nullable=False),
        sa.Column("title_raw", sa.Text(), nullable=False),
        sa.Column("title_norm", sa.Text(), nullable=False),
        # 'pending'|'processing'|'done'|'failed'|'skipped'
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="pending",
        ),
        # priority>0 — первым (manual reassess от оператора), default=0.
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        # Заполняется при успехе для аудита, до match_log INSERT.
        sa.Column(
            "result_game_id",
            sa.BigInteger(),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("result_score", sa.Float(), nullable=True),
        sa.Column("result_tier", sa.SmallInteger(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        # Один offer в очереди — один раз. ON CONFLICT skip при повторной постановке.
        sa.UniqueConstraint("offer_id", name="uq_match_queue_offer"),
    )
    # Partial-индекс для воркера: только pending/processing записи нужны.
    op.create_index(
        "ix_match_queue_pending",
        "match_queue",
        [sa.text("priority DESC"), sa.text("created_at ASC")],
        postgresql_where=sa.text(
            "status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= now())"
        ),
    )

    # ── game_embeddings: pgvector с HNSW ───────────────────────────────────────
    # Каждая строка = один embedded text (либо title, либо alias).
    # game_id + alias_id (nullable) — UNIQUE: одна game может иметь N embeddings.
    # Создаём через raw SQL потому что alembic не имеет нативной поддержки
    # vector(N) типа — приходится либо ALTER после CREATE (хак), либо чистый DDL.
    op.execute("""
        CREATE TABLE game_embeddings (
            id BIGSERIAL PRIMARY KEY,
            game_id BIGINT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            alias_id BIGINT REFERENCES game_aliases(id) ON DELETE CASCADE,
            text_used TEXT NOT NULL,
            embedding vector(1024) NOT NULL,
            model VARCHAR(64) NOT NULL DEFAULT 'bge-m3',
            embedded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_game_embeddings_pair UNIQUE (game_id, alias_id)
        )
    """)

    # HNSW индекс для cosine similarity. m=16, ef_construction=128 — стандарт для 1024-dim.
    # Стоимость построения: ~5-10 мс/строка при batch warmup; 360K строк → ~30-60 минут.
    # Cosine операторы pgvector: <=> distance; (1 - score) для similarity.
    op.execute(
        "CREATE INDEX ix_game_embeddings_hnsw "
        "ON game_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    )
    op.create_index("ix_game_embeddings_game_id", "game_embeddings", ["game_id"])

    # ── scheduler_configs сид: ml_health_check + match_worker ──────────────────
    # Не cron (interval-based). Используем cron-выражения для совместимости с
    # существующим scheduler.py — переход на IntervalTrigger делается в shеduler.py
    # отдельно через специальную обработку.
    op.execute("""
        INSERT INTO scheduler_configs (job_id, cron_expr, enabled, params)
        VALUES
            ('ml_health_check', '*/1 * * * *', TRUE, '{"interval_sec": 30}'::jsonb),
            ('match_worker',    '*/1 * * * *', TRUE, '{"interval_sec": 10, "batch_size": 32}'::jsonb)
        ON CONFLICT (job_id) DO NOTHING
    """)


def downgrade() -> None:
    # Снимаем сид scheduler_configs.
    op.execute("DELETE FROM scheduler_configs WHERE job_id IN ('ml_health_check', 'match_worker')")

    op.drop_index("ix_game_embeddings_game_id", table_name="game_embeddings")
    op.execute("DROP INDEX IF EXISTS ix_game_embeddings_hnsw")
    op.drop_table("game_embeddings")

    op.drop_index("ix_match_queue_pending", table_name="match_queue")
    op.drop_table("match_queue")

    op.drop_index("ix_match_log_performed_at", table_name="match_log")
    op.drop_index("ix_match_log_batch_id", table_name="match_log")
    op.drop_index("ix_match_log_offer_id", table_name="match_log")
    op.drop_table("match_log")

    op.drop_index("ix_match_decisions_game_id", table_name="match_decisions")
    op.drop_table("match_decisions")

    op.drop_column("offers", "match_reason")
    op.drop_column("offers", "match_tier")
    op.drop_column("offers", "predicted_kind")

    op.execute("DROP INDEX IF EXISTS ix_games_title_ru_trgm")
    op.drop_column("games", "title_ru")

    # pgvector extension не дропаем — могут быть другие пользователи.
