"""Batched updates для ImportJob.progress / log_lines.

Зачем: long-running импорты (особенно dicefest на ~900 игр) генерят 3+ строки
лога per item. Если делать UPDATE на каждую — это row-level lock и WAL-bloat
(Postgres перезаписывает row целиком при UPDATE jsonb). На 1000 итераций — 3000
UPDATE'ов одной строки.

Решение: накапливаем строки и progress в памяти задачи, flush'им одной
транзакцией каждые N=20 строк ИЛИ раз в 2 секунды (что наступит раньше).
На 1000 игр получается ~150 UPDATE'ов вместо 3000.

Ring-buffer log_lines: храним только последние RING_SIZE (~200) строк, чтобы
поле не разрасталось до мегабайт на длинных прогонах. Tail в UI всё равно
покажет только последние N строк через `<pre overflow-y-auto>`.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.models import ImportJob

RING_SIZE = 200


class LogBuffer:
    """Буферизатор UPDATE'ов в ImportJob.progress / log_lines.

    Использование:
        buf = LogBuffer(session, job_id=42, flush_every_n=20, flush_every_s=2.0)
        for item in items:
            buf.set_progress(phase="parsing", current=i, total=N, current_title=item.name)
            buf.log(f"[{i+1}/{N}] {item.slug} — ok")
            await buf.maybe_flush()        # flush если threshold достигнут
        await buf.flush()                   # final flush в finally

    Не thread-safe — рассчитан на использование из одного asyncio-task'а
    (типичный паттерн `_run_*_import_job` через asyncio.create_task).
    """

    def __init__(
        self,
        session: AsyncSession,
        job_id: int,
        *,
        flush_every_n: int = 20,
        flush_every_s: float = 2.0,
        ring_size: int = RING_SIZE,
    ) -> None:
        self._session = session
        self._job_id = job_id
        self._flush_every_n = flush_every_n
        self._flush_every_s = flush_every_s
        self._ring_size = ring_size

        self._lines: list[str] = []
        self._progress: dict[str, Any] | None = None
        self._unflushed_lines = 0
        self._last_flush_ts = time.monotonic()

    def log(self, line: str) -> None:
        """Добавить строку в буфер (in-memory). flush — отдельной операцией."""
        self._lines.append(line)
        # Trim до ring_size, чтобы JSONB не разрастался.
        if len(self._lines) > self._ring_size:
            self._lines = self._lines[-self._ring_size :]
        self._unflushed_lines += 1

    def set_progress(
        self,
        *,
        phase: str | None = None,
        current: int | None = None,
        total: int | None = None,
        current_title: str | None = None,
    ) -> None:
        """Обновить прогресс. Поля, переданные None, не меняются (merge-семантика)."""
        if self._progress is None:
            self._progress = {"phase": "", "current": 0, "total": 0, "current_title": None}
        if phase is not None:
            self._progress["phase"] = phase
        if current is not None:
            self._progress["current"] = current
        if total is not None:
            self._progress["total"] = total
        if current_title is not None:
            self._progress["current_title"] = current_title

    async def maybe_flush(self) -> bool:
        """Flush, если накопилось ≥flush_every_n строк ИЛИ прошло flush_every_s сек."""
        elapsed = time.monotonic() - self._last_flush_ts
        if self._unflushed_lines >= self._flush_every_n or elapsed >= self._flush_every_s:
            await self.flush()
            return True
        return False

    async def flush(self) -> None:
        """Безусловный flush. UPDATE одной строкой + commit.

        Ничего не делает, если нечего писать. Сбрасывает счётчики.
        """
        if self._unflushed_lines == 0 and self._progress is None:
            return
        values: dict[str, Any] = {"log_lines": list(self._lines)}
        if self._progress is not None:
            # dict() — SQLAlchemy сериализует через psycopg/asyncpg в JSONB
            values["progress"] = dict(self._progress)
        await self._session.execute(
            update(ImportJob).where(ImportJob.id == self._job_id).values(**values)
        )
        await self._session.commit()
        self._unflushed_lines = 0
        self._last_flush_ts = time.monotonic()
