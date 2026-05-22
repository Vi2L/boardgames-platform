"""Tracking «голых» fire-and-forget asyncio-тасок, чтобы их можно было
дождаться на graceful shutdown.

Зачем: `asyncio.create_task(...)` внутри HTTP-хэндлера без хранения ссылки
живёт, пока coroutine не завершится, но при остановке loop'а (SIGTERM →
uvicorn graceful shutdown) такая таска получает `CancelledError` на полпути.
Если внутри был `session.commit()` или другая транзакция — она оборвётся.

Паттерн взят из официальной документации `asyncio.create_task`: держим
ссылку в `set`, удаляем по завершении через `add_done_callback`. Set
живёт в `app.state.background_tasks`, чтобы lifespan мог дождаться его
на shutdown.

Применять только к таскам, потеря которых на shutdown даёт некорректное
состояние (несохранённый commit, оборванный rollback). Для чисто
read-only тасок (health-ping) tracking не нужен.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def init_background_state(app: FastAPI) -> None:
    """Вызвать один раз при startup до первого `track_task`."""
    app.state.background_tasks = set()


def track_task(
    app: FastAPI,
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
) -> asyncio.Task[Any]:
    """Создать tracked task. Совместим по API с `asyncio.create_task`."""
    task = asyncio.create_task(coro, name=name)
    app.state.background_tasks.add(task)
    # discard, а не remove — на случай, если callback срабатывает дважды
    # (теоретически невозможно, но idempotent безопаснее).
    task.add_done_callback(app.state.background_tasks.discard)
    return task


async def wait_background_tasks(app: FastAPI, timeout: float = 10.0) -> None:
    """Дождаться завершения всех зарегистрированных тасок.

    Зависшие после `timeout` секунд — отменяются. Любая ошибка таски
    (включая `CancelledError`) проглатывается через `return_exceptions=True`:
    наша цель — отдать им шанс на чистое завершение, а не репортить.
    """
    pending = list(app.state.background_tasks)
    if not pending:
        return
    logger.info("shutdown: waiting for %d background task(s)", len(pending))
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # Таймаут вышел — отменяем недожившие. После cancel ещё один short
        # gather, чтобы `CancelledError` доехал до coroutine и она успела
        # хотя бы выйти из текущего `await`.
        stuck = [t for t in pending if not t.done()]
        logger.warning(
            "shutdown: %d background task(s) exceeded %.1fs timeout, cancelling",
            len(stuck), timeout,
        )
        for t in stuck:
            t.cancel()
        await asyncio.gather(*stuck, return_exceptions=True)
