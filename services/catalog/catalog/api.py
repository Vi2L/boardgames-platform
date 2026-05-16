"""FastAPI-приложение boardgames-catalog.

Этап skeleton: только /health для smoke-теста. Бизнес-роутеры (games, offers,
matching, imports) будут подключаться по мере реализации этапов из плана.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

# uvicorn конфигурирует только свои логгеры (uvicorn.*); root-логгер без handler'а.
# Эта строка добавляет stderr-handler на root-логгер, чтобы catalog.* и
# apscheduler.* сообщения не терялись. Вызов идемпотентен: basicConfig — no-op
# если handler уже есть (например, при тестах с caplog).
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
from sqlalchemy import text

from catalog.config import get_settings
from catalog.db import dispose_engine, get_engine
from catalog.routers import bgg_lists as bgg_lists_router
from catalog.routers import games as games_router
from catalog.routers import imports as imports_router
from catalog.routers import ingest as ingest_router
from catalog.routers import matching as matching_router
from catalog.routers import parsers as parsers_router
from catalog.routers import promotion as promotion_router
from catalog.routers import auto_recovery as auto_recovery_router
from catalog.routers import runtime_flags as runtime_flags_router
from catalog.routers import scheduler as scheduler_router
from catalog.routers import sources as sources_router
from catalog.scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: создаём engine заранее, чтобы первый запрос не платил за инициализацию.
    get_engine()

    # ── Matching v2: recovery + health check ─────────────────────────────────
    # При старте: вернуть зависшие 'processing' записи match_queue в 'pending'.
    # Сценарий: сервис упал во время обработки — без recovery записи висят
    # вечно. Делаем здесь, до старта scheduler'а — иначе worker может взять
    # уже застрявшие.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from catalog.matching.v2.health import OllamaHealth
    from catalog.matching.v2.queue_repo import recover_stuck

    SessionFactory = async_sessionmaker(get_engine(), expire_on_commit=False)
    try:
        async with SessionFactory() as session:
            recovered = await recover_stuck(session)
            await session.commit()
            if recovered > 0:
                import logging
                logging.getLogger(__name__).info(
                    "matching v2 startup: recovered %d stuck match_queue items",
                    recovered,
                )
    except Exception:  # noqa: BLE001
        # Если match_queue ещё не существует (миграция не накатана) — игнорируем.
        import logging
        logging.getLogger(__name__).exception(
            "matching v2 startup: recover_stuck failed (миграция 0011 не применена?)"
        )

    # Первый health-check Ollama сразу при старте — чтобы scheduler-job не
    # ждал 30 секунд до первого poll'а.
    import asyncio as _asyncio
    _asyncio.create_task(OllamaHealth.get_instance().check())

    # BGG sync scheduler. create_scheduler() async — читает scheduler_configs из БД.
    # Сохраняем в app.state.scheduler для роутера /scheduler (PATCH → hot-reload).
    # wait=False при shutdown — не ждём завершения долгих задач (enrich_batch ~25 мин)
    # при SIGTERM; они упадут вместе с loop'ом.
    scheduler = await create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    scheduler.shutdown(wait=False)
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.service_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness-проверка без обращения к БД. Для k8s/compose healthcheck."""
        return {"status": "ok", "service": settings.service_name}

    @app.get("/health/db", tags=["meta"])
    async def health_db() -> dict[str, str]:
        """Readiness: проверяет, что БД отвечает. SELECT 1 — самый дешёвый ping."""
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "reachable"}

    app.include_router(bgg_lists_router.router)
    app.include_router(games_router.router)
    app.include_router(imports_router.router)
    app.include_router(ingest_router.router)
    app.include_router(matching_router.router)
    app.include_router(parsers_router.router)
    app.include_router(promotion_router.router)
    app.include_router(auto_recovery_router.router)
    app.include_router(runtime_flags_router.router)
    app.include_router(scheduler_router.router)
    app.include_router(sources_router.router)
    return app


app = create_app()
