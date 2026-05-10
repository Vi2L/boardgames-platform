"""Конфигурация сервиса. Читает env через pydantic-settings.

Все настройки централизованы здесь, чтобы не размазывать os.getenv по коду.
Это паттерн «12-factor config» — всё через переменные окружения, дефолты
подобраны для локальной разработки.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL DSN. Формат: postgresql+asyncpg://user:pass@host:port/db
    database_url: str = Field(
        default="postgresql+asyncpg://catalog:catalog@localhost:5433/catalog",
        description="async DSN для SQLAlchemy",
    )

    # Имя сервиса в логах/метриках
    service_name: str = "boardgames-catalog"
    log_level: str = "INFO"

    # X-API-Key auth. По умолчанию выключена для удобства dev/CI; в prod
    # включается через REQUIRE_AUTH=1. Когда выключена, scope-зависимости
    # пропускают всех (см. catalog/auth.py).
    require_auth: bool = False

    # ── BGG API ──────────────────────────────────────────────────────────────
    # Bearer-токен для BGG XML API v2 (обязателен с 2025-го; без него 401).
    bgg_api_token: str | None = Field(default=None)

    # Еженедельный sync TOP-N игр через enrich_batch (понедельник 03:00 UTC).
    bgg_top_sync_enabled: bool = Field(default=True)
    bgg_top_sync_rank_le: int = Field(default=1000)
    bgg_top_sync_skip_recent_days: int = Field(default=7)
    # unix-cron: «минута час день_мес месяц день_нед»
    bgg_top_sync_cron: str = Field(default="0 3 * * 1")

    # Ежедневный sync BGG Hotness (06:00 UTC).
    bgg_hotness_sync_enabled: bool = Field(default=True)
    bgg_hotness_sync_cron: str = Field(default="0 6 * * *")
    # Авто-импорт игр из Hotness, которых ещё нет в каталоге.
    bgg_hotness_auto_import: bool = Field(default=True)

    # On-demand staleness в /ingest/offers: если game_bgg.fetched_at старше N дней
    # и оффер auto-matched — запустить enrich_one в фоне. 0 = выключено.
    bgg_ingest_enrich_staleness_days: int = Field(default=14)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton-доступ к настройкам. lru_cache гарантирует один инстанс на процесс."""
    return Settings()
