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

    # CAT-8 (families): после успешного `enrich_one` подтягивать членов BGG-семей.
    # Запускается fire-and-forget через asyncio.create_task. Editable через
    # UI / runtime_flags (key='bgg_family_cascade_enabled', миграция 0018 в CAT-8) —
    # эта ENV-настройка работает как seed-default, runtime_flags переопределяет.
    bgg_family_cascade_enabled: bool = Field(default=True)
    # Пауза между cascade-вызовами enrich_one (best practice BGG XML API).
    bgg_family_cascade_rate_limit_sec: float = Field(default=1.0)

    # ── Matching v2 (миграция 0011) ──────────────────────────────────────────
    # Локальный Ollama-сервис для embedding (bge-m3) и LLM-арбитра (qwen2.5).
    # macOS host видим из Docker по host.docker.internal:11434.
    ollama_base_url: str = Field(default="http://host.docker.internal:11434")
    ml_embed_model: str = Field(default="bge-m3")
    ml_llm_model: str = Field(default="qwen2.5:7b-instruct")

    # 0 = ML отключён (как kill-switch без рестарта). При false ingest всегда
    # пишет 'unmatched' с reason='ml_disabled' минуя очередь.
    ml_enabled: bool = Field(default=True)

    # Health-poll интервал (сек). OllamaHealth singleton кэширует статус,
    # реальный HTTP-вызов раз в N сек. APScheduler job выполняет poll.
    ml_health_poll_interval_sec: int = Field(default=30)

    # Async-воркер для T2/T3.
    match_worker_interval_sec: int = Field(default=10)
    match_worker_batch_size: int = Field(default=32)
    # MAX_ATTEMPTS для retry перед перевод в 'failed'. Backoff: 30→120→600 сек.
    match_worker_max_attempts: int = Field(default=3)

    # Пороги (могут быть переопределены через MatchProfile.params в БД).
    # T1: pg_trgm. 0.92 = почти-точное совпадение (опечатка в одну букву).
    match_t1_auto_threshold: float = Field(default=0.92)
    # T2: bge-m3 cosine. 0.85 = высокая семантическая близость.
    match_t2_auto_threshold: float = Field(default=0.85)
    # Сколько кандидатов поднимать через vector search для T2/T3.
    match_t2_top_k: int = Field(default=5)
    # T3 кандидаты: ниже этого score даже не отдаём LLM-арбитру.
    match_t3_min_score: float = Field(default=0.70)
    # Минимальный confidence от LLM для auto-match. Иначе → manual queue.
    match_t3_confidence_threshold: float = Field(default=0.75)

    # TTL для match_decisions кэша per source. После TTL — Tier 0 пропускает запись.
    match_decisions_ttl_t1_days: int = Field(default=30)
    match_decisions_ttl_t2_days: int = Field(default=14)
    match_decisions_ttl_t3_days: int = Field(default=7)

    # Retention для match_log (CAT-11). Записи старше N дней удаляются
    # ежедневным scheduler-job'ом `match_log_retention`. Не реверченные
    # записи (`reverted_at IS NULL` И `action != 'revert'`) сохраняются —
    # они потенциально нужны для отката.
    match_log_retention_days: int = Field(default=90)

    # CAT-4.5: cross-service URL для auto_recovery_runner — он опрашивает
    # `/api/debug/breakers` parsers'а для condition.type='breaker_state'.
    # Default = docker-compose service name. Если задать пустую строку,
    # breaker-conditions автоматически False (skip).
    parsers_base_url: str = Field(default="http://parsers:8001")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton-доступ к настройкам. lru_cache гарантирует один инстанс на процесс."""
    return Settings()
