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
    language: str | None = None
    verified: bool = False


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


class GameBggOut(_ORMBase):
    """BGG satellite-данные: ranks + (опционально) XML-API enrichment."""
    bgg_id: int
    rank: int | None = None
    bayes_average: float | None = None
    average: float | None = None
    users_rated: int | None = None
    is_expansion: bool = False
    subtype_ranks: dict[str, Any] | None = None
    description: str | None = None
    designers: list[str] | None = None
    artists: list[str] | None = None
    publishers: list[str] | None = None
    mechanics: list[str] | None = None
    categories: list[str] | None = None
    min_players: int | None = None
    max_players: int | None = None
    min_age: int | None = None
    playtime_min: int | None = None
    playtime_max: int | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    source: str | None = None
    fetched_at: datetime


class GameWikidataOut(_ORMBase):
    """Wikidata satellite: labels/aliases/descriptions per language."""
    bgg_id: int | None = None
    entity_id: str | None = None
    found: bool = False
    labels: dict[str, str] = Field(default_factory=dict)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    descriptions: dict[str, str] = Field(default_factory=dict)
    fetched_at: datetime


class GameDetailOut(GameOut):
    """Карточка с алиасами и satellite-данными. /games/{id}."""
    aliases: list[GameAliasOut] = Field(default_factory=list)
    bgg: GameBggOut | None = None
    wikidata: GameWikidataOut | None = None


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


# ---------- ingest от parsers ----------

class IngestOfferIn(BaseModel):
    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str
    price: int | None = None  # копейки
    image_url: str | None = None
    extra: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    store_slug: str = Field(min_length=1, max_length=64)
    fetched_at: datetime | None = None
    products: list[IngestOfferIn]


class IngestResultItem(BaseModel):
    external_id: str
    offer_id: int
    game_id: int | None
    match_status: str
    match_score: float | None


class IngestResult(BaseModel):
    store_slug: str
    accepted: int
    auto_matched: int
    unmatched: int
    items: list[IngestResultItem]


# ---------- matching queue ----------

class OfferOut(_ORMBase):
    id: int
    game_id: int | None
    store_slug: str
    external_id: str
    url: str
    title_raw: str
    image_url: str | None
    last_price: int | None
    last_seen_at: datetime
    match_status: str
    match_score: float | None


class MatchingQueueOut(BaseModel):
    items: list[OfferOut]
    total: int
    limit: int
    offset: int


class MatchLinkRequest(BaseModel):
    game_id: int


# ---------- import jobs (uses datetime, defined above) ----------

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
