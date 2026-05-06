from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .db import PriceDatabase

router = APIRouter()

# db инжектируется из api.py после старта приложения
_db: PriceDatabase


def set_db(db: PriceDatabase) -> None:
    global _db
    _db = db


@router.get("/dashboard", include_in_schema=False)
async def dashboard():
    """HTML-дашборд мониторинга."""
    import pathlib
    html_path = pathlib.Path(__file__).parent / "dashboard.html"
    return FileResponse(html_path, media_type="text/html")


@router.get("/api/stats")
async def stats_summary(hours: int = 24):
    """Сводная статистика запросов к /search за последние N часов."""
    return await _db.get_stats(hours=hours)


@router.get("/api/stats/stores")
async def store_health():
    """Здоровье каждого парсера за последние 24 часа."""
    return await _db.get_store_stats()


@router.get("/api/stats/errors")
async def recent_errors(limit: int = 20):
    """Последние N ошибок парсеров."""
    return await _db.get_recent_errors(limit=limit)
