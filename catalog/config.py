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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton-доступ к настройкам. lru_cache гарантирует один инстанс на процесс."""
    return Settings()
