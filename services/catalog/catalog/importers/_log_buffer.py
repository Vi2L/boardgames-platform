"""Batched updates для ImportJob.progress / log_lines + BufLogger.

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

import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.models import ImportJob

RING_SIZE = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class BufLogger:
    """Адаптер `logging.Logger`-API → `LogBuffer` + Python logger.

    Принимает logger-style вызовы (`info(msg, *args)`, `warning(...)`,
    `exception(...)`) и параллельно пишет в LogBuffer (для UI-polling'а)
    и в обычный Python logger (для stdout/файлового лога).

    Пользоваться: `buf_log = BufLogger(buf, logger)`, передавать в любую
    функцию ожидающую logging.Logger-like объект.

    Зачем общий класс: бойлерплейт «прокинуть логи в LogBuffer» дублировался
    в bgg_hotness.py / dicefest.py / etc.
    """

    def __init__(self, buf: LogBuffer, logger: logging.Logger) -> None:
        self._buf = buf
        self._logger = logger

    def info(self, msg: str, *args: object) -> None:
        self._buf.log(msg % args if args else msg)
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args: object) -> None:
        self._buf.log("[WARN] " + (msg % args if args else msg))
        self._logger.warning(msg, *args)

    def exception(self, msg: str, *args: object) -> None:
        self._buf.log("[ERR] " + (msg % args if args else msg))
        self._logger.exception(msg, *args)


# Сигнатура body-функции для run_import_job_skeleton.
# Принимает (buf, buf_log, session_factory) и возвращает result-dict для записи в ImportJob.result.
# session_factory нужен ядрам run_*_sync которые открывают свои сессии для разных
# stage'ов (например, auto_import делается в отдельной сессии per-item).
ImportJobBody = Callable[
    [LogBuffer, BufLogger, "async_sessionmaker[AsyncSession]"],
    Awaitable[dict[str, Any]],
]


async def run_import_job_skeleton(
    job_id: int,
    *,
    init_log: str,
    body: ImportJobBody,
    session_factory: "async_sessionmaker[AsyncSession]",
    summary_fn: Callable[[dict[str, Any]], str] | None = None,
    flush_every_n: int = 5,
    flush_every_s: float = 2.0,
    logger_inst: logging.Logger | None = None,
) -> None:
    """Унифицированный скелет ImportJob: pending → running → body() → done/failed.

    Удаляет 55-строчный дублирующий блок try/except + LogBuffer wiring между
    importers (`bgg_hotness.py`, `bgg_geeklist.py`).

    Жизненный цикл:
    1. Открываем session, помечаем job как `running` + `started_at`.
    2. Создаём LogBuffer и BufLogger в этой же сессии.
    3. Логируем `init_log` и flush'им (UI получает первое обновление).
    4. Вызываем `body(buf, buf_log, session_factory)`. Body сам решает где
       делать flush'ы; внешняя session открыта на всё время вызова.
    5. По возврату — пишем итоговый summary, ставим status='done' + result.
    6. На исключение — buf.log(FAILED), status='failed', error=str(exc).

    Контракт body:
      - НЕ должен сам делать UPDATE ImportJob (status/started_at/finished_at) —
        это делает обёртка.
      - МОЖЕТ использовать переданный session_factory для отдельных сессий внутри
        (например, per-item commit'ы для auto-import).
      - Должен вернуть dict с результатом (что попадёт в `ImportJob.result`).

    Args:
        job_id: PK ImportJob (уже создан endpoint'ом).
        init_log: первая строка лога (например, "BGG Hotness sync запущен").
        body: async callable, ядро задачи. См. контракт выше.
        session_factory: фабрика сессий (передаётся в body для under-task сессий).
        summary_fn: result-dict → одна строка для финального лога.
                    Default: f"Done: {result!r}".
        flush_every_n / flush_every_s: пороги LogBuffer (см. LogBuffer.maybe_flush).
        logger_inst: Python-логгер для дублирования сообщений в stdout.
                     Default: логгер модуля.
    """
    log = logger_inst or logging.getLogger(__name__)

    async with session_factory() as session:
        job = (
            await session.execute(select(ImportJob).where(ImportJob.id == job_id))
        ).scalar_one()
        job.status = "running"
        job.started_at = _utcnow()
        await session.commit()

        buf = LogBuffer(
            session,
            job_id=job_id,
            flush_every_n=flush_every_n,
            flush_every_s=flush_every_s,
        )
        buf.set_progress(phase="starting", current=0, total=0)
        buf.log(init_log)
        await buf.flush()

        buf_log = BufLogger(buf, log)

        try:
            result = await body(buf, buf_log, session_factory)

            summary = summary_fn(result) if summary_fn else f"Done: {result!r}"
            buf.log(summary)
            buf.set_progress(phase="done")
            await buf.flush()

            await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id)
                .values(status="done", finished_at=_utcnow(), result=result)
            )
            await session.commit()

        except Exception as exc:  # noqa: BLE001
            log.exception("ImportJob %d (%s) failed", job_id, init_log)
            buf.log(f"FAILED: {exc!r}")
            await buf.flush()
            await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id)
                .values(status="failed", finished_at=_utcnow(), error=str(exc))
            )
            await session.commit()
