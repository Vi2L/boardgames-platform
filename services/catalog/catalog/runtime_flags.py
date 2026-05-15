"""RuntimeFlags — runtime-кэш для kill-switch'ей и других динамических флагов.

Модуль на уровне `catalog/` (а не `matching/v2/`) намеренно: его потребители
живут в разных доменах — `routers/runtime_flags.py` (admin REST) импортирует
`set_bool`, `matching/v2/engine.py` и `matching/v2/worker.py` — `is_ml_enabled`.
Когда появится второй флаг (для scheduler / dicefest / etc.), его место —
здесь же, не в субпакете одного потребителя.

Зачем отдельный модуль вместо `Settings`:
  `catalog.config.get_settings()` обёрнут в `@lru_cache` per-process. Значение
  ENV-переменной (например, `ML_ENABLED`) читается один раз и фризится.
  Чтобы выключить ML без рестарта сервиса, нужен источник правды вне процесса —
  таблица `runtime_flags` в Postgres.

Дизайн:
  - In-memory TTL-кэш (~5 сек) — чтобы каждый `ingest` не делал SELECT.
  - На промахе/протухании — один SELECT в `runtime_flags`, заполняем кэш.
  - Запись (через `PATCH /admin/runtime-flags/{key}`) сбрасывает локальный
    кэш этого процесса; параллельные инстансы catalog'а подхватят новое
    значение в течение TTL (≤ 5 сек). Для нашей нагрузки это приемлемая
    задержка propagation'а — альтернатива (LISTEN/NOTIFY или Redis pub/sub)
    переусложнение.

Текущие флаги:
  - `ml_enabled: bool` — общий выключатель T2/T3 (worker skip + ingest fallback).
    Если строки нет в БД → fallback на `Settings.ml_enabled` (legacy-режим).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.config import get_settings
from catalog.db import get_engine
from catalog.models import RuntimeFlag


_TTL_SECONDS = 5.0

# Sentinel для «нет в кэше / TTL истёк». Отдельный объект (не None, не False) —
# `None` уже занят семантикой «строки нет в БД» (cached negative), `False` — это
# валидное значение флага.
_MISS = object()


@dataclass
class _CacheEntry:
    value: bool | None
    expires_at: float


class _RuntimeFlagsCache:
    """Process-local TTL cache. Не singleton по сути — один глобальный
    инстанс в модуле, тестам можно instantiate'ить отдельно через
    `reset_for_tests()`."""

    def __init__(self) -> None:
        self._cache: dict[str, _CacheEntry] = {}

    def get_cached(self, key: str) -> object:
        """Возвращает кэшированное значение (`bool | None`) или `_MISS`
        если ключа нет / TTL истёк. Caller сравнивает с `_MISS` через `is`."""
        entry = self._cache.get(key)
        if entry is None or entry.expires_at < time.monotonic():
            return _MISS
        return entry.value

    def set(self, key: str, value: bool | None) -> None:
        self._cache[key] = _CacheEntry(
            value=value, expires_at=time.monotonic() + _TTL_SECONDS,
        )

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()


_cache = _RuntimeFlagsCache()


def reset_for_tests() -> None:
    """Очистить process-local cache. Тесты с разным набором флагов должны
    звать это в setup, иначе предыдущее значение протечёт через TTL."""
    _cache.clear()


async def _load_from_db(key: str, session: AsyncSession | None) -> bool | None:
    """Один SELECT в runtime_flags. Возвращает значение или None если строки
    нет. NOT использует кэш — caller должен сам положить в кэш."""
    if session is None:
        # Caller не передал сессию — открываем свою. Этот путь используется
        # из worker'а, у которого нет request-scoped session, и из тестов.
        engine = get_engine()
        SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionFactory() as own_session:
            row = (await own_session.execute(
                select(RuntimeFlag.value_bool).where(RuntimeFlag.key == key)
            )).scalar_one_or_none()
            return row
    row = (await session.execute(
        select(RuntimeFlag.value_bool).where(RuntimeFlag.key == key)
    )).scalar_one_or_none()
    return row


async def get_bool(
    key: str,
    *,
    default: bool,
    session: AsyncSession | None = None,
) -> bool:
    """Возвращает значение bool-флага. На промахе кэша делает один SELECT.

    `default` — значение если строки нет в БД (или БД не доступна — silent).
    Используется для `ml_enabled` как backstop: пока миграция 0013 не накатана,
    система работает в legacy-режиме (`Settings.ml_enabled`).
    """
    cached = _cache.get_cached(key)
    if cached is not _MISS:
        # В кэше — реальное значение (включая None = «строки нет в БД»).
        if cached is None:
            return default
        return bool(cached)

    try:
        value = await _load_from_db(key, session)
    except Exception:  # noqa: BLE001
        # БД упала или нет таблицы (миграция не накатана) — fallback на default.
        # Кэшировать negative нельзя: не хотим зафризить fallback на 5 сек.
        return default

    _cache.set(key, value)
    if value is None:
        return default
    return value


async def is_ml_enabled(session: AsyncSession | None = None) -> bool:
    """Главный читатель kill-switch'а matching v2.

    Источник правды — `runtime_flags.ml_enabled`. На fallback — `Settings.ml_enabled`
    (env-переменная). После миграции 0013 строка засеяна, fallback нужен только
    для legacy-окружений или в тестах без миграции.
    """
    settings_default = get_settings().ml_enabled
    return await get_bool("ml_enabled", default=settings_default, session=session)


async def set_bool(
    key: str,
    value: bool,
    *,
    updated_by: str,
    session: AsyncSession,
) -> bool:
    """Upsert runtime_flags. Инвалидирует локальный кэш — следующие чтения
    из ЭТОГО процесса увидят новое значение немедленно. Другие инстансы
    catalog'а подхватят в течение TTL (≤ 5 сек).

    Не делает commit — caller отвечает за транзакцию (стандартный паттерн
    для router-уровня).
    """
    # Raw SQL потому что нам нужен `now()` в updated_at на UPDATE; через
    # SQLAlchemy `pg_insert.excluded.updated_at` это server_default только
    # при INSERT, на UPDATE он не подставляется автоматически.
    await session.execute(
        text(
            "INSERT INTO runtime_flags (key, value_bool, updated_by) "
            "VALUES (:k, :v, :who) "
            "ON CONFLICT (key) DO UPDATE SET "
            "  value_bool = EXCLUDED.value_bool, "
            "  updated_by = EXCLUDED.updated_by, "
            "  updated_at = now()"
        ).bindparams(k=key, v=value, who=updated_by)
    )
    _cache.invalidate(key)
    return value
