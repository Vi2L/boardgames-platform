"""matching v2 hardening — claimed_at + runtime_flags

Усиливает реализацию [CAT-4] после ревью (см. roadmap):

1. **`match_queue.claimed_at`** — таймстемп когда воркер забрал запись через
   `claim_batch`. До этой миграции `recover_stuck` использовал `created_at` —
   время создания записи в очереди, а не время claim'а. При горячем рестарте
   сервиса запись, давно лежавшая в pending и только что переведённая в
   processing, ошибочно возвращалась в pending → запись могла обработаться
   дважды разными воркерами после рестарта. FOR UPDATE SKIP LOCKED тут не
   защищает — это разные транзакции/процессы.

2. **`runtime_flags`** — таблица для значений, которые должны меняться без
   рестарта сервиса. Сейчас единственный пользователь — `ml_enabled`
   kill-switch (план [CAT-4] обещал hot-reload, но `Settings` был обёрнут
   в `@lru_cache`). Семантика: одна строка на флаг, read через короткий
   in-memory TTL-кэш (~5 сек), write через `PATCH /admin/runtime-flags/{key}`.

Revision ID: 0013
Revises:     0012
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── match_queue.claimed_at ────────────────────────────────────────────────
    # NULL для существующих строк — recover_stuck в этом случае должен НЕ
    # трогать запись (поведение "не знаем когда заклеймили, ждём ручного
    # вмешательства"). Это безопаснее чем legacy fallback на created_at.
    op.add_column(
        "match_queue",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── runtime_flags ─────────────────────────────────────────────────────────
    # Минимальная схема: key + value_bool + updated_at. Если в будущем
    # понадобятся string/int-флаги — добавим колонки value_str/value_int
    # и тонкое чтение в RuntimeFlags.get_*().
    op.create_table(
        "runtime_flags",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text(), nullable=True),
    )

    # Сидим `ml_enabled = true` — значение по умолчанию совпадает с
    # Settings.ml_enabled (Field default=True). Без этой строки kill-switch
    # вернёт fallback из Settings (что не сломает работу, но и не позволит
    # выключить без рестарта).
    op.execute(
        "INSERT INTO runtime_flags (key, value_bool, updated_by) "
        "VALUES ('ml_enabled', true, 'migration_0013') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("runtime_flags")
    op.drop_column("match_queue", "claimed_at")
