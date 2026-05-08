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
    # External IDs других каталогов (миграция 0006)
    dicefest_id: int | None = None
    nastolio_id: str | None = None
    cover_url: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    # Тип игры и связь с базой (миграция 0006)
    kind: str = "base"  # base | expansion | promo | accessory
    parent_game_id: int | None = None
    # Локализация в РФ (миграция 0006)
    ru_publisher: str | None = None
    ru_release_year: int | None = None
    is_localized_ru: bool = False
    preorder_price: int | None = None  # копейки
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


# Допустимые значения kind. Хранится строкой (не PG ENUM), валидация — на
# уровне Pydantic. Расширять enum в будущем без ALTER TYPE.
GAME_KINDS = ("base", "expansion", "promo", "accessory")


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
    dicefest_id: int | None = None
    nastolio_id: str | None = None
    cover_url: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    kind: str = Field(default="base", pattern=r"^(base|expansion|promo|accessory)$")
    parent_game_id: int | None = None
    ru_publisher: str | None = None
    ru_release_year: int | None = None
    is_localized_ru: bool = False
    preorder_price: int | None = None
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
    dicefest_id: int | None = None
    nastolio_id: str | None = None
    cover_url: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    status: str | None = None
    kind: str | None = Field(default=None, pattern=r"^(base|expansion|promo|accessory)$")
    parent_game_id: int | None = None
    ru_publisher: str | None = None
    ru_release_year: int | None = None
    is_localized_ru: bool | None = None
    preorder_price: int | None = None


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1)
    source: str = "manual"
    # ISO-код языка ('ru', 'en', 'de', ...). NULL для магазинных названий
    # и manual без явной локали — на стороне модели поле уже nullable.
    language: str | None = Field(None, max_length=8)
    verified: bool = False


class AliasPatch(BaseModel):
    """Редактирование существующего алиаса. Все поля опциональны."""
    alias: str | None = Field(None, min_length=1)
    source: str | None = None
    language: str | None = Field(None, max_length=8)
    verified: bool | None = None


class GameListOut(BaseModel):
    items: list[GameOut]
    total: int
    limit: int
    offset: int


class GameMergeRequest(BaseModel):
    """Объединение двух игр: source → target.

    target_id остаётся, source помечается status='merged' и пишет в
    meta.merged_into=target_id. Все offers и aliases переезжают.
    """
    source_id: int
    target_id: int


class GameMergeResult(BaseModel):
    source_id: int
    target_id: int
    offers_moved: int
    aliases_moved: int
    aliases_skipped_dup: int


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
    # Нормализованные поля магазина (миграция 0006). Все опциональны:
    # старый клиент может не отправлять — поведение остаётся прежним
    # (значения берутся из extra только если parser их положит).
    sku: str | None = None
    in_stock: bool | None = None
    original_price: int | None = None  # копейки до скидки
    is_preorder: bool | None = None
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
    # Нормализованные поля магазина (миграция 0006). nullable во всех случаях
    # — данные есть не у всех парсеров (HobbyGames кладёт sku/availability,
    # Crowd Games — in_stock, Лавка/GaGa — пока ничего).
    sku: str | None = None
    in_stock: bool | None = None
    original_price: int | None = None
    is_preorder: bool | None = None


class MatchingQueueOut(BaseModel):
    items: list[OfferOut]
    total: int
    limit: int
    offset: int


class MatchLinkRequest(BaseModel):
    game_id: int


# ---------- import jobs (uses datetime, defined above) ----------

class ImportProgress(BaseModel):
    """Прогресс импорт-job'а (зафиксированный shape для UI).

    Обновляется батчами через catalog.importers._log_buffer.LogBuffer —
    polling-frontend читает одной порцией с progress-bar и tail-логом.
    """

    phase: str  # 'collecting' | 'parsing' | 'done'
    current: int = 0
    total: int = 0
    current_title: str | None = None


class ImportJobOut(_ORMBase):
    id: int
    type: str
    status: str
    payload: dict[str, Any]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    progress: ImportProgress | None = None
    log_lines: list[str] | None = None
    created_at: datetime


# ---------- dicefest ----------

class DicefestImportRequest(BaseModel):
    """Запрос на запуск парсера dicefest.

    max_items=N полезен для пробных прогонов: парсим только первые N slug'ов.
    only_year ограничивает обход листингов одним годом (2024/2025/2026).
    """

    max_items: int | None = None
    only_year: int | None = None


class ExternalLink(BaseModel):
    """Ссылка на внешний сайт из карточки dicefest.

    kind — машинный тип источника (`bgg`, `tesera`, `nastolio`, `shop`, `other`).
    external_id — извлечённый ID/slug в URL (например, BGG `447174`), если
    смогли распознать. Полезно для будущего матчинга canonical Game.
    """

    kind: str
    url: str
    label: str
    external_id: str | None = None


class DicefestRawGameOut(_ORMBase):
    id: int
    slug: str
    page_url: str
    title_ru: str | None = None
    title_en: str | None = None
    publisher: str | None = None        # «Издатель в РФ» — UI label
    release_status: str | None = None
    description: str | None = None
    cover_url: str | None = None
    preorder_price: int | None = None   # копейки
    external_links: list[ExternalLink] = []
    raw: dict[str, Any]
    source_listing: str | None = None
    fetched_at: datetime
    status: str
    promoted_at: datetime | None = None
    promoted_to_game_id: int | None = None
    notes: str | None = None
    # raw_html намеренно НЕ в Out — слишком большой для типового списка/детали;
    # запрашивается отдельным эндпоинтом при необходимости (например, для
    # просмотра «исходник» в debug-портале).


class DicefestRawListOut(BaseModel):
    items: list[DicefestRawGameOut]
    total: int
    limit: int
    offset: int


# ---------- promotion ----------

class PromotionCandidate(BaseModel):
    """Кандидат-canonical-Game для привязки raw-записи (dicefest и др.).

    `via` — что именно мэтчилось (title_ru/title_en raw vs games.title или alias).
    `has_satellite_for_provider` — у этой game уже есть satellite от текущего
    источника (для dicefest — game_dicefest). Красный флаг в UI.
    `year_diff` — разница годов между raw и canonical (если оба известны);
    UI рисует жёлтый warning при ≥3 лет.
    """

    game_id: int
    title: str
    year: int | None = None
    score: float
    via: str  # 'title' | 'alias_ru' | 'alias_en'
    matched_text: str | None = None
    aliases: list[GameAliasOut] = []
    has_satellite_for_provider: bool = False
    year_diff: int | None = None


class PromotionCandidatesOut(BaseModel):
    raw: DicefestRawGameOut
    candidates: list[PromotionCandidate]
    threshold: float


class PromotionApplyRequest(BaseModel):
    """Действие промоушена.

    action:
      - link: привязать raw к существующей game (target_game_id обязателен)
      - create: создать новую canonical Game со slug='dicefest-{slug}'
      - skip: пометить raw как 'skipped' (можно вернуть в 'new' через revert)
      - reject: пометить raw как 'rejected' (то же)
    """

    action: str  # 'link' | 'create' | 'skip' | 'reject'
    target_game_id: int | None = None
    notes: str | None = None
    performed_by: str | None = None


class PromotionApplyResult(BaseModel):
    raw_id: int
    log_id: int
    game_id: int | None = None
    alias_id: int | None = None
    satellite_id: int | None = None
    status: str  # status raw после действия


class PromotionLogOut(_ORMBase):
    id: int
    provider: str
    raw_id: int
    action: str
    game_id: int | None = None
    alias_id: int | None = None
    satellite_created: bool
    performed_by: str | None = None
    performed_at: datetime
    reverted_at: datetime | None = None
    reverted_by: str | None = None
    notes: str | None = None


class PromotionLogList(BaseModel):
    items: list[PromotionLogOut]
    total: int
    limit: int
    offset: int


class PromotionRevertResult(BaseModel):
    raw_id: int
    revert_log_id: int
    original_log_id: int
    status_after_revert: str


# ---------- batch auto-link (PR-5) ----------

class BatchLinkRequest(BaseModel):
    """Параметры batch auto-link.

    threshold — минимальный score для безопасного авто-link (по умолчанию 0.95
    «почти точное совпадение»). dry_run по умолчанию True для UX «preview сначала».
    """

    threshold: float = 0.95
    max_items: int = 100
    dry_run: bool = True
    skip_with_satellite: bool = True


class BatchLinkItemPreview(BaseModel):
    raw_id: int
    slug: str
    raw_title: str | None = None
    game_id: int
    game_title: str
    score: float
    via: str


class BatchLinkSkipped(BaseModel):
    raw_id: int
    slug: str
    reason: str       # 'low_score' | 'already_linked' | 'no_candidates' | 'promote_failed:N'
    top_score: float | None = None


class BatchLinkResult(BaseModel):
    scanned: int
    linked: int                          # сколько реально записано (0 при dry_run)
    would_link: int                      # сколько было бы записано
    skipped: list[BatchLinkSkipped]
    items: list[BatchLinkItemPreview]    # топ-50 для preview
    dry_run: bool
