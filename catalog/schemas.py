"""Pydantic-схемы запросов/ответов API.

Раздел между ORM-моделями (catalog.models) и API-схемами — намеренный:
ORM может содержать служебные поля и связи, которые не должны протекать
в API. Pydantic v2 + ConfigDict(from_attributes=True) даёт удобную
конвертацию `Game.model_validate(orm_game)`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- games ----------

class GameAliasOut(_ORMBase):
    id: int
    alias: str
    source: str


class GameOut(_ORMBase):
    id: int
    slug: str
    title: str
    year: int | None = None
    designers: list[str] | None = None
    publishers: list[str] | None = None
    players_min: int | None = None
    players_max: int | None = None
    age_min: int | None = None
    playtime_min: int | None = None
    playtime_max: int | None = None
    bgg_id: int | None = None
    tesera_id: int | None = None
    cover_url: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    source: str
    status: str
    created_at: datetime
    updated_at: datetime


class GameDetailOut(GameOut):
    """Карточка с алиасами. /games/{id}."""
    aliases: list[GameAliasOut] = Field(default_factory=list)


class GameCreate(BaseModel):
    """Ручное создание Game через POST /games."""
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    title: str = Field(min_length=1)
    year: int | None = None
    designers: list[str] | None = None
    publishers: list[str] | None = None
    players_min: int | None = None
    players_max: int | None = None
    age_min: int | None = None
    playtime_min: int | None = None
    playtime_max: int | None = None
    bgg_id: int | None = None
    tesera_id: int | None = None
    cover_url: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    source: str = "manual"


class GamePatch(BaseModel):
    """Частичное обновление. Все поля опциональны."""
    title: str | None = None
    year: int | None = None
    designers: list[str] | None = None
    publishers: list[str] | None = None
    players_min: int | None = None
    players_max: int | None = None
    age_min: int | None = None
    playtime_min: int | None = None
    playtime_max: int | None = None
    bgg_id: int | None = None
    tesera_id: int | None = None
    cover_url: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    status: str | None = None


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1)
    source: str = "manual"


class GameListOut(BaseModel):
    items: list[GameOut]
    total: int
    limit: int
    offset: int


# ---------- imports ----------

class BggImportRequest(BaseModel):
    bgg_id: int | None = None
    ids: list[int] | None = None


class TeseraImportRequest(BaseModel):
    """Tesera принимает alias (slug) или числовой id. Можно батчем."""
    alias: str | None = None
    tesera_id: int | None = None
    items: list[str | int] | None = None


class ImportJobOut(_ORMBase):
    id: int
    type: str
    status: str
    payload: dict[str, Any]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime
