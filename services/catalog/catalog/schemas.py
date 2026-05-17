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
    # Производное поле: лучший alias с language='ru' по приоритету
    # verified-manual > dicefest > wikidata. Проставляется на уровне роутера
    # (см. list_games / get_game), не хранится в БД. Не приходит из ORM
    # автоматически — отсюда дефолт None и явный set после model_validate.
    title_ru: str | None = None
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
    # Расширенная статистика (миграция 0012, CAT-5).
    average_weight: float | None = None  # complexity 1.00–5.00
    num_weights: int | None = None
    # BGG <poll> рекомендации (CAT-6). recommended_players — raw подсчёты
    # per player count; фронт сам решает, как презентовать (best/recommended/
    # not_recommended counts → бар-чарт или метка «лучше всего с N»).
    recommended_players: dict[str, dict[str, int]] | None = None
    recommended_age: int | None = None
    language_dependence: int | None = None  # 1..5
    # Timestamp последнего XML-обогащения (CAT-7). NULL — игра только в CSV.
    bgg_stats_updated_at: datetime | None = None
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


class GameChildOut(_ORMBase):
    """Минимальная карточка для блока «Дети» (допы/промо/аксессуары).

    Используется на /games/{id}/children. Слим — без satellite-данных,
    чтобы один SELECT покрывал всю выдачу для UI-списка.
    """
    id: int
    slug: str
    title: str
    kind: str
    year: int | None = None
    cover_url: str | None = None
    status: str


class GameChildrenOut(BaseModel):
    parent_game_id: int
    items: list[GameChildOut]
    total: int


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


class BggBatchImportRequest(BaseModel):
    """POST /import/bgg/batch — массовое XML-обогащение топ-N или всех ranked игр.

    Ровно один из `rank_le` / `all_ranked` / `year_in` обязателен (валидация —
    в роутере, чтобы 422 был с понятным сообщением).

    `year_in` — выборка по `games.year` (например `[2025, 2026]` для новинок).
    В отличие от `rank_le` / `all_ranked` включает игры без rank: для свежих
    выпусков это норма (BGG ranks обновляются раз в месяц).
    """

    rank_le: int | None = Field(
        default=None, ge=1,
        description="обработать только игры с BGG rank ≤ N (топ-N).",
    )
    all_ranked: bool = Field(
        default=False,
        description="обработать все ranked-игры (~25 минут при rate-limit 1/сек).",
    )
    year_in: list[int] | None = Field(
        default=None,
        description=(
            "обработать игры с games.year ∈ списку (включает не-ranked). "
            "Пример: [2025, 2026] для новинок текущего сезона."
        ),
    )
    batch_size: int = Field(default=20, ge=1, le=20)
    skip_recent_days: int = Field(
        default=30, ge=0,
        description="не перезапрашивать игры с fetched_at < N дней (0 — форсировать).",
    )
    limit: int | None = Field(
        default=None, ge=1,
        description="общий потолок (для пробного прогона).",
    )
    dry_run: bool = False
    rate_limit_sec: float = Field(default=1.0, ge=0.0, le=10.0)


class GeeklistImportRequest(BaseModel):
    """POST /import/bgg/geeklist — snapshot кураторского BGG GeekList'а.

    GeekList — кураторский список thing-id с заголовком и комментариями. Используется
    для monthly «BGG Top 50 Most Played» (id типа 367126) и любых других топов.
    """

    geeklist_id: int = Field(..., ge=1, description="ID GeekList на BGG")
    auto_import: bool = Field(
        default=True,
        description="при True — автоматически enrich_one для bgg_id отсутствующих в каталоге",
    )


class MiniBatchImportRequest(BaseModel):
    """POST /import/bgg/mini-batch — ежедневный «catch-up» обогащения хвоста.

    Тонкая обёртка над batch enrich с дефолтами под daily-режим: маленький `limit`,
    увеличенный `skip_recent_days` (мы не трогаем то, что недавно обновлял weekly
    top-sync), мягкий `rate_limit_sec` чтобы не хватать BGG.

    На полной выборке ~30K ranked-игр и `limit=500` цикл обновления = ~60 дней.
    """

    batch_size: int = Field(default=500, ge=10, le=5000)
    skip_recent_days: int = Field(default=30, ge=0)
    rate_limit_sec: float = Field(default=2.0, ge=0.0, le=10.0)
    dry_run: bool = False


class SchedulerJobOut(_ORMBase):
    """Состояние одного scheduled-job'а: конфиг + last_run + next_run."""

    job_id: str
    cron_expr: str
    enabled: bool
    params: dict[str, Any]
    # Денормализованная инфа о последнем запуске (поддерживается trigger'ом и scheduler'ом).
    last_run_job_id: int | None = None
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    # Динамика из APScheduler runtime — заполняется в роутере.
    next_run_at: datetime | None = None
    # Описание провайдера для UI (display_name, doc) — заполняется в роутере из реестра.
    display_name: str | None = None
    description: str | None = None
    # Ring-buffer последних тиков (только для interval-jobs: match_worker /
    # ml_health_check). Каждый элемент = {ts, duration_ms, error}.
    # Источник — `catalog.scheduler.get_tick_history(job_id)`.
    tick_history: list[dict[str, Any]] = Field(default_factory=list)


class SchedulerRescheduleRequest(BaseModel):
    """PATCH /scheduler/jobs/{id} — изменить cron/enabled/params без рестарта."""

    cron_expr: str | None = Field(
        default=None,
        description="unix-cron 5 полей. Если None — не трогаем расписание.",
    )
    enabled: bool | None = Field(
        default=None,
        description="True — включить, False — pause_job. Если None — не трогаем.",
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description="merge в существующий params (не replace). Используется на старте job'а.",
    )


class TeseraImportRequest(BaseModel):
    """Tesera принимает alias (slug) или числовой id. Можно батчем."""
    alias: str | None = None
    tesera_id: int | None = None
    items: list[str | int] | None = None


class AutoRecoveryRuleOut(_ORMBase):
    """GET/POST /admin/auto-recovery-rules — JSON-полиморфные правила."""
    id: int
    name: str
    condition: dict[str, Any]
    action: dict[str, Any]
    enabled: bool
    last_triggered_at: datetime | None = None
    last_result: str | None = None
    created_at: datetime
    updated_at: datetime
    updated_by: str | None = None


class AutoRecoveryRuleCreate(BaseModel):
    """POST /admin/auto-recovery-rules — создать правило."""
    name: str = Field(min_length=1, max_length=128)
    condition: dict[str, Any]
    action: dict[str, Any]
    enabled: bool = True


class AutoRecoveryRuleUpdate(BaseModel):
    """PATCH /admin/auto-recovery-rules/{id} — partial update."""
    name: str | None = Field(default=None, min_length=1, max_length=128)
    condition: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    enabled: bool | None = None


class RuntimeFlagBoolUpdate(BaseModel):
    """PATCH /admin/runtime-flags/{key} — обновить bool-флаг."""

    value: bool = Field(description="новое значение флага")


class RuntimeFlagOut(_ORMBase):
    """GET /admin/runtime-flags/{key} — текущее состояние флага.

    Наследует `_ORMBase` (`from_attributes=True`) чтобы конструироваться
    напрямую из ORM-объекта `RuntimeFlag` через `model_validate(row)` —
    как остальные `*Out`-схемы (см. `SchedulerJobOut`, `GameOut`).
    """

    key: str
    value_bool: bool | None
    updated_at: datetime
    updated_by: str | None


# ---------- ingest от parsers ----------
# Request-side (IngestRequest, IngestOfferIn) живёт в общем пакете
# bg_shared.ingest — он же используется publisher'ом в services/parsers.
# Менять контракт — там, не здесь. См. docs/parallel-agents.md §10.2.


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
    # Сколько офферов отброшено категорийным whitelist'ом (не настолки).
    # Старые publisher'ы без поля `category` не вызывают rejection — это
    # счётчик намеренного отказа, не сетевая ошибка. См. ingest router.
    skipped_category: int = 0
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
    # True если оффер ранее был привязан и затем отвязан оператором (миграция 0008).
    was_linked: bool = False


class MatchingQueueOut(BaseModel):
    items: list[OfferOut]
    total: int
    limit: int
    offset: int


class GameOffersOut(BaseModel):
    """Список offers, связанных с конкретной игрой (drawer-таб «Offers»)."""
    game_id: int
    items: list[OfferOut]
    total: int


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


# Усечённые summary для GET /promotion/log/{log_id}/details — отдаём UI
# минимум, нужный для модалки деталей. Полные карточки доступны через
# /games/{id} и /promotion/{provider}/{raw_id}, если оператору нужно глубже.
class PromotionLogRawGameSummary(_ORMBase):
    id: int
    slug: str
    title_ru: str | None = None
    title_en: str | None = None
    publisher: str | None = None
    page_url: str
    preorder_price: int | None = None  # копейки
    fetched_at: datetime
    status: str


class PromotionLogGameSummary(_ORMBase):
    id: int
    slug: str
    title: str
    year: int | None = None
    status: str


class PromotionLogAliasSummary(_ORMBase):
    id: int
    game_id: int
    alias: str
    alias_norm: str
    source: str
    language: str | None = None
    verified: bool


class PromotionLogDetails(BaseModel):
    """Развёрнутые детали одной записи журнала промоушена.

    Все вложенные сущности подгружаются по id из самой записи (raw_id /
    game_id / alias_id) и могут быть None, если ссылка пустая или объект
    был удалён (например, alias после revert). reverted_by_entry_id —
    id revert-записи, которая отменила эту операцию (заполняется только
    если log.reverted_at IS NOT NULL).
    """

    entry: PromotionLogOut
    raw_game: PromotionLogRawGameSummary | None = None
    game: PromotionLogGameSummary | None = None
    alias: PromotionLogAliasSummary | None = None
    reverted_by_entry_id: int | None = None


# ---------- batch auto-link (PR-5) ----------

class BatchLinkRequest(BaseModel):
    """Параметры batch auto-link.

    threshold — минимальный score для безопасного авто-link (по умолчанию 0.95
    «почти точное совпадение»). dry_run по умолчанию True для UX «preview сначала».

    `match_params` — расширенные параметры (weights, prefer_external_id).
    Если задан, его `threshold` имеет приоритет над верхнеуровневым.
    """

    threshold: float = 0.95
    max_items: int = 100
    dry_run: bool = True
    skip_with_satellite: bool = True
    match_params: "MatchParams | None" = None


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


# ---------- parsers (BGG / Wikidata / ...) ----------

class BggSearchRequest(BaseModel):
    """Запрос поиска игр в BGG XML API через `POST /parsers/bgg/search`."""
    query: str = Field(min_length=1, max_length=256)
    # exact=True проксируется в BGG `/search?exact=1` — фильтр по полному
    # совпадению primary name. False (default) даёт fuzzy-поведение, нужное
    # оператору в Live Test.
    exact: bool = False
    limit: int = Field(default=20, ge=1, le=100)


class BggSearchHitOut(BaseModel):
    """Одна позиция в ответе `POST /parsers/bgg/search`."""
    bgg_id: int
    title: str
    year: int | None = None


class BggSearchResponse(BaseModel):
    query: str
    exact: bool
    count: int
    items: list[BggSearchHitOut]


# ---------- match params (унифицированный матчинг) ----------

class MatchWeights(BaseModel):
    """Веса score per поле. Default = 1.0 для всех — поведение совпадает с старым.

    `ru` / `en` — при матче по title/alias на соответствующем языке.
    `alias` — общий мультипликатор для совпадений через game_aliases (поверх
    языкового веса). Полезно, если оператор хочет понизить доверие к auto-match
    aliases в пользу title.
    """

    ru: float = Field(default=1.0, ge=0.0, le=2.0)
    en: float = Field(default=1.0, ge=0.0, le=2.0)
    alias: float = Field(default=1.0, ge=0.0, le=2.0)


class MatchParams(BaseModel):
    """Параметры матчинга, передаваемые в /candidates и /batch-link.

    Все поля опциональны; при отсутствии параметров поведение совпадает с
    текущим (threshold=0.3-0.5 в зависимости от endpoint, веса = 1.0,
    external_id не учитывается).
    """

    threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    prefer_external_id: bool = Field(
        default=False,
        description=(
            "Если у raw есть BGG/Tesera ID в external_links — добавить "
            "deterministic-кандидата со score=1.0 поверх trgm-результатов."
        ),
    )
    weights: MatchWeights = Field(default_factory=MatchWeights)


# ---------- match profiles ----------

class MatchProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    params: MatchParams
    is_default: bool = False


class MatchProfileOut(_ORMBase):
    id: int
    provider: str
    name: str
    params: dict[str, Any]
    is_default: bool
    updated_at: datetime


# ---------- sources: scrape runs ----------

class ScrapeRunCreate(BaseModel):
    """Тело POST /sources/{provider}/runs. Параметры скрапа провайдер-специфичны;
    собираются в `ScraperParams` в runner'е.
    """

    max_items: int | None = Field(default=None, ge=1, le=10000)
    only_year: int | None = Field(default=None, ge=2000, le=2100)
    extra: dict[str, Any] = Field(default_factory=dict)


class ScrapeRunTotals(BaseModel):
    """Снимок счётчиков прогона для UI. Поля опциональны — runner заполняет
    их по мере прогресса; UI рендерит только что есть."""

    new: int | None = None
    updated: int | None = None
    unchanged: int | None = None
    total_slugs: int | None = None
    errors: int | None = None
    applied: int | None = None


class ScrapeRunOut(_ORMBase):
    id: int
    provider: str
    status: str
    params: dict[str, Any]
    totals: dict[str, Any]
    error_message: str | None = None
    log_lines: list[str]
    started_at: datetime
    finished_at: datetime | None = None
    performed_by: str | None = None


class ScrapeRunListOut(BaseModel):
    runs: list[ScrapeRunOut]
    total: int


class ScrapeItemOut(_ORMBase):
    id: int
    run_id: int
    slug: str
    payload: dict[str, Any]
    content_hash: str
    prev_hash: str | None = None
    change_type: str
    field_diffs: dict[str, Any] | None = None
    fetched_at: datetime


class ScrapeItemListOut(BaseModel):
    items: list[ScrapeItemOut]
    total: int


class ScrapeRunApplyRequest(BaseModel):
    """`item_ids` и `change_types` фильтруются как AND. Если оба None — ошибка.
    UI всегда передаёт хотя бы один."""

    item_ids: list[int] | None = None
    change_types: list[str] | None = None
    performed_by: str | None = None


class ScrapeRunApplyResult(BaseModel):
    run_id: int
    applied: int


class ScrapeRunDiscardResult(BaseModel):
    run_id: int
    status: str


# Forward-references: BatchLinkRequest объявлен раньше MatchParams и использует
# его как опциональное поле. Pydantic v2 при `from __future__ import annotations`
# все аннотации видит строкой — после определения MatchParams нужно явно
# пересобрать модель, иначе поле останется без валидатора.
BatchLinkRequest.model_rebuild()
