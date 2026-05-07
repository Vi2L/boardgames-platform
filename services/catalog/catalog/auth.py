"""X-API-Key аутентификация со scope'ами.

Дизайн:
- Ключ — 32 байта random URL-safe (44 символа base64). Сам ключ нигде не хранится,
  в БД лежит только sha256-хеш. Энтропии 256 бит хватает: rainbow-table-атака
  на такой keyspace невозможна, salt не нужен (это машинный токен, не
  пользовательский пароль).
- Скоупы — массив строк. Стандартные: 'ingest' (только POST /ingest/*),
  'read' (GET /games, /matching/queue), 'admin' (POST/PATCH /games, /matching/*,
  /import).
- Чтобы не ломать dev-flow и существующие тесты, auth по умолчанию ВЫКЛЮЧЕНА.
  Включается через REQUIRE_AUTH=1 в env. Это компромисс: prod включает явно,
  dev и CI не платят сложность.
- Просроченные ключи (revoked_at != NULL) трактуются как несуществующие.

Использование на роутах:
    @router.post("/ingest/offers", dependencies=[Depends(require_scope("ingest"))])
    async def ingest_offers(...): ...
"""
from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.config import get_settings
from catalog.db import get_session
from catalog.models import ApiKey


def hash_key(plaintext: str) -> str:
    """sha256 hex. Достаточно для high-entropy машинных токенов."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_key() -> str:
    """Plaintext-ключ. Возвращается единожды при создании, не хранится."""
    return secrets.token_urlsafe(32)


def require_scope(required: str):
    """FastAPI dependency-фабрика. На роуте: dependencies=[Depends(require_scope('ingest'))].

    Логика:
    - REQUIRE_AUTH != '1' → проходим без проверки (dev-режим).
    - Заголовка нет → 401.
    - Ключ невалиден / отозван → 401.
    - Скоуп не покрывает → 403.
    - 'admin' — суперскоуп, покрывает всё.
    """

    async def _dep(
        x_api_key: str | None = Header(None),
        session: AsyncSession = Depends(get_session),
    ) -> ApiKey | None:
        settings = get_settings()
        if not settings.require_auth:
            return None

        if not x_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-API-Key header required",
            )

        key_hash = hash_key(x_api_key)
        api_key = (
            await session.execute(
                select(ApiKey).where(
                    ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None)
                )
            )
        ).scalar_one_or_none()

        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or revoked API key",
            )

        scopes = set(api_key.scopes or [])
        if "admin" in scopes or required in scopes:
            return api_key

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"scope '{required}' required",
        )

    return _dep
