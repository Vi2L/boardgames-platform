"""FastAPI-приложение boardgames-catalog.

Этап skeleton: только /health для smoke-теста. Бизнес-роутеры (games, offers,
matching, imports) будут подключаться по мере реализации этапов из плана.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from catalog.config import get_settings
from catalog.db import dispose_engine, get_engine
from catalog.routers import games as games_router
from catalog.routers import imports as imports_router
from catalog.routers import ingest as ingest_router
from catalog.routers import matching as matching_router
from catalog.routers import parsers as parsers_router
from catalog.routers import promotion as promotion_router
from catalog.routers import sources as sources_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: создаём engine заранее, чтобы первый запрос не платил за инициализацию.
    get_engine()
    yield
    # Shutdown: аккуратно закрываем пул.
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

    app.include_router(games_router.router)
    app.include_router(imports_router.router)
    app.include_router(ingest_router.router)
    app.include_router(matching_router.router)
    app.include_router(parsers_router.router)
    app.include_router(promotion_router.router)
    app.include_router(sources_router.router)
    return app


app = create_app()
