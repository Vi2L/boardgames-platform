"""Точка входа FastAPI-приложения."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import catalog as catalog_router_module
from app.api import db as db_router_module
from app.api import debug as debug_router_module
from app.api import favorites as favorites_router_module
from app.api import health, history, parsers as parsers_router_module
from app.api import search as search_router_module
from app.api import snapshots as snapshots_router_module
from app.api import stats as stats_router_module
from app.api import stores as stores_router_module
from app.api import suites as suites_router_module
from app.deps import close_services, init_services

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_services()
    yield
    await close_services()


app = FastAPI(
    title="Parsers Debug Portal",
    description="Debug/testing web interface for the parsers service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router_module.router, prefix="/api")
app.include_router(parsers_router_module.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(stores_router_module.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(stats_router_module.router, prefix="/api")
app.include_router(db_router_module.router, prefix="/api")
app.include_router(snapshots_router_module.router, prefix="/api")
app.include_router(suites_router_module.router, prefix="/api")
app.include_router(favorites_router_module.router, prefix="/api")
app.include_router(catalog_router_module.router, prefix="/api")
app.include_router(debug_router_module.router, prefix="/api")

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
