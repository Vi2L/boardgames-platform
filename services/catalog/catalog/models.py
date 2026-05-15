"""ORM-модели каталога настольных игр.

SQLAlchemy 2.0 typed style (Mapped + mapped_column). Все таблицы наследуются
от Base из catalog.db.

Ключевые решения:
- `title_norm` / `alias_norm` — generated columns (`lower(immutable_unaccent(...))`),
  поверх них pg_trgm GIN-индекс. Это даёт fuzzy-search через `%` оператор и
  similarity() без триггеров. Сама функция immutable_unaccent создаётся в миграции —
  unaccent не IMMUTABLE по умолчанию, нужен IMMUTABLE-обёртка.
- Цены — int (копейки), как в `parsers`. На границе API при необходимости делим на 100.
- `offers.game_id` nullable: пока матчинг не сделан или score ниже порога, оффер
  висит unmatched и попадает в очередь ручного review.
- ARRAY и JSONB — диалект Postgres; через диалект-специфичные импорты.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# pgvector type adapter для SQLAlchemy. Vector(N) даёт колонку pgvector(N) и
# автоматически конвертирует list[float] ↔ array. Без него embedding пришлось бы
# передавать как строку '[0.1,0.2,...]'::vector.
from pgvector.sqlalchemy import Vector

from catalog.db import Base


def _now() -> datetime:
    """Server-side default предпочтительнее, но клиентский нужен для
    onupdate, чтобы updated_at тикал без явного INSERT...DEFAULT."""
    from datetime import timezone
    return datetime.now(timezone.utc)


class Game(Base):
    """Каноническая настольная игра. Источник истины — BGG/Tesera + ручные правки."""

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Generated column. Persisted (STORED), чтобы pg_trgm индекс мог его использовать.
    title_norm: Mapped[str] = mapped_column(
        Text,
        Computed("lower(immutable_unaccent(title))", persisted=True),
    )
    # First-class ru-название (миграция 0011). Денормализуется из лучшего
    # ru-alias скриптом backfill_title_ru.py (приоритет: verified > manual >
    # dicefest > wikidata) и при промоушене dicefest. Используется matcher v2
    # как часть text_used для embedding и для прямого pg_trgm-матча.
    title_ru: Mapped[str | None] = mapped_column(Text)

    year: Mapped[int | None] = mapped_column(Integer)
    designers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    publishers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    players_min: Mapped[int | None] = mapped_column(Integer)
    players_max: Mapped[int | None] = mapped_column(Integer)
    age_min: Mapped[int | None] = mapped_column(Integer)
    playtime_min: Mapped[int | None] = mapped_column(Integer)
    playtime_max: Mapped[int | None] = mapped_column(Integer)

    bgg_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    tesera_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    # Внешние ID других каталогов (миграция 0006). Денормализуются при
    # промоушене из dicefest_raw_games (id) и из external_links[kind='nastolio'].
    # Partial-unique индекс (WHERE NOT NULL) определён в миграции — SQLAlchemy
    # отдельный декларативный constraint не нужен, ORM просто читает значения.
    dicefest_id: Mapped[int | None] = mapped_column(BigInteger)
    nastolio_id: Mapped[str | None] = mapped_column(Text)

    cover_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # meta — свободные доп. поля (механики, рейтинг BGG, категории).
    # JSONB позволяет индексировать по ключам, в отличие от JSON.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Тип игры: 'base' (базовая), 'expansion' (дополнение), 'promo' (промо/мини-доп),
    # 'accessory' (аксессуар: органайзер, чехлы, токены и т.п.).
    # Хранится строкой, не PostgreSQL ENUM — расширять enum в будущем без ALTER TYPE.
    kind: Mapped[str] = mapped_column(
        String(16), default="base", server_default="base", nullable=False, index=True,
    )
    # Для expansion/promo/accessory — родительская игра-«база», от которой
    # они зависят. Self-FK с ON DELETE SET NULL: если базу удалили, связь
    # обнуляется, но допы не удаляются каскадом.
    parent_game_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="SET NULL"), index=True,
    )

    # Локализация в РФ (миграция 0006). При промоушене из dicefest:
    #   ru_publisher  ← dicefest_raw_games.publisher
    #   preorder_price ← dicefest_raw_games.preorder_price
    #   is_localized_ru = True
    # Поле `publishers` (выше) — список издателей оригинала (BGG); `ru_publisher`
    # — конкретный российский локализатор.
    ru_publisher: Mapped[str | None] = mapped_column(Text)
    ru_release_year: Mapped[int | None] = mapped_column(Integer)
    is_localized_ru: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    preorder_price: Mapped[int | None] = mapped_column(BigInteger)  # копейки

    # Откуда пришла каноническая запись: bgg / tesera / manual / auto-from-parsers.
    source: Mapped[str] = mapped_column(String(32), default="manual")
    # 'published' — видна публично; 'draft' — кандидат из авто-матчинга, ждёт review.
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=_now,
        onupdate=_now,
    )

    aliases: Mapped[list["GameAlias"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    offers: Mapped[list["Offer"]] = relationship(back_populates="game")
    # Satellite-таблицы (1:1). Источник-специфичные данные. Загружаются по запросу
    # через selectinload(Game.bgg, Game.wikidata).
    bgg: Mapped["GameBgg | None"] = relationship(
        back_populates="game", cascade="all, delete-orphan", uselist=False
    )
    wikidata: Mapped["GameWikidata | None"] = relationship(
        back_populates="game", cascade="all, delete-orphan", uselist=False
    )
    # Self-referential: parent_game ← база, children → допы/промо/аксессуары.
    # remote_side=[id] обязателен для self-FK, иначе SQLAlchemy не знает, какая
    # сторона — «один», а какая — «много».
    parent_game: Mapped["Game | None"] = relationship(
        "Game",
        remote_side="Game.id",
        back_populates="children",
        foreign_keys=[parent_game_id],
    )
    children: Mapped[list["Game"]] = relationship(
        "Game",
        back_populates="parent_game",
        foreign_keys=[parent_game_id],
    )


class GameAlias(Base):
    """Альтернативные написания игры — для матчинга оффер'ов из магазинов.

    Например, для Carcassonne: 'Каркассон', 'Carcassonne (Hobby World)',
    'Каркасон базовый набор'. Чем больше алиасов — тем выше шанс auto-match.
    """

    __tablename__ = "game_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_norm: Mapped[str] = mapped_column(
        Text,
        Computed("lower(immutable_unaccent(alias))", persisted=True),
    )
    # 'manual', 'auto-match' (от матчера), 'bgg', 'wikidata', 'tesera'.
    source: Mapped[str] = mapped_column(String(32), default="manual")
    # ISO-код языка для алиасов с известной локалью ('ru', 'en', 'de', ...).
    # NULL для магазинных названий (auto-match) и manual без явной локали.
    language: Mapped[str | None] = mapped_column(String(8))
    # True — алиас подтверждён человеком/доверенным источником (manual link).
    # False — авто-источник (pg_trgm match, Wikidata import).
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )

    game: Mapped[Game] = relationship(back_populates="aliases")

    __table_args__ = (UniqueConstraint("game_id", "alias_norm", name="uq_alias_per_game"),)


class Offer(Base):
    """Предложение магазина. Зеркало `parsers.products` + текущая цена.

    `game_id` NULLABLE — оффер живёт в БД и до матчинга. Если матчер не уверен,
    оффер уходит в /matching/queue (этап 5).
    """

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), index=True
    )
    store_slug: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    title_raw: Mapped[str] = mapped_column(Text)
    title_raw_norm: Mapped[str] = mapped_column(
        Text,
        Computed("lower(immutable_unaccent(title_raw))", persisted=True),
    )
    image_url: Mapped[str | None] = mapped_column(Text)
    last_price: Mapped[int | None] = mapped_column(BigInteger)  # копейки
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )

    # 'auto' (матчер уверен), 'manual' (человек подтвердил),
    # 'unmatched' (висит в очереди), 'rejected' (человек сказал «не игра»).
    match_status: Mapped[str] = mapped_column(String(16), default="unmatched", index=True)
    match_score: Mapped[float | None] = mapped_column(Float)

    # Нормализованные поля магазина (миграция 0006). Дублируют отдельные ключи
    # из raw_extra для индексируемых фильтров (наличие, скидка, предзаказ).
    # `external_id` — это идентификатор товара в магазине (для upsert), а
    # `sku` — внутренний артикул магазина (HobbyGames кладёт его отдельно).
    sku: Mapped[str | None] = mapped_column(String(64))
    in_stock: Mapped[bool | None] = mapped_column(Boolean)
    original_price: Mapped[int | None] = mapped_column(BigInteger)  # копейки до скидки
    is_preorder: Mapped[bool | None] = mapped_column(Boolean)

    raw_extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # True если оффер хотя бы раз был привязан к игре вручную, затем отвязан.
    # Используется очередью матчинга: такие офферы всплывают выше для повторного
    # review (оператор мог ошибиться при первом матче).
    was_linked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # Matcher v2 диагностика (миграция 0011).
    # match_tier: 0=cache hit, 1=trgm, 2=embedding, 3=llm; NULL до первого матча.
    # match_reason: текстовое объяснение для UI ('cache_hit', 'vec_confident', ...).
    # predicted_kind: классификация LLM-арбитром {'base'|'expansion'|'accessory'};
    # NULL = не классифицировался (T0/T1 матч или ML недоступен).
    match_tier: Mapped[int | None] = mapped_column(SmallInteger)
    match_reason: Mapped[str | None] = mapped_column(Text)
    predicted_kind: Mapped[str | None] = mapped_column(String(16))

    game: Mapped[Game | None] = relationship(back_populates="offers")
    prices: Mapped[list["OfferPrice"]] = relationship(
        back_populates="offer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("store_slug", "external_id", name="uq_offer_store_external"),
    )


class OfferPrice(Base):
    """История цен по конкретному офферу. Аналог `parsers.price_observations`."""

    __tablename__ = "offer_prices"

    offer_id: Mapped[int] = mapped_column(
        ForeignKey("offers.id", ondelete="CASCADE"), primary_key=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now(), default=_now
    )
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # копейки

    offer: Mapped[Offer] = relationship(back_populates="prices")


class ImportJob(Base):
    """Асинхронные импорты из BGG/Tesera/Dicefest (этапы 3-4 + dicefest).

    payload — параметры запуска (например, {'bgg_id': 822}); status —
    pending/running/done/failed; error — стектрейс/сообщение в случае failed.

    progress / log_lines добавлены в миграции 0003 для long-running импортёров
    (особенно dicefest на ~900 игр × 1с = 15+ минут). Обновляются батчами через
    catalog.importers._log_buffer.LogBuffer (раз в ~20 строк или 2 секунды),
    иначе UPDATE на каждый item даёт row-level lock + WAL-bloat.
    """

    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)  # 'bgg', 'tesera', 'dicefest'
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # {phase, current, total, current_title} — shape зафиксирован контрактом.
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Ring-buffer ~200 последних строк лога. Tail для UI через polling.
    log_lines: Mapped[list[str] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )


class GameBgg(Base):
    """Satellite-таблица BGG-данных (1:1 с games).

    Заполняется двумя источниками:
    - `source='csv-ranks'` — лёгкая выгрузка boardgames_ranks.csv: rank, scores,
      is_expansion, subtype_ranks. Описаний/механик/дизайнеров нет.
    - `source='xml-api'` — полноценный XML API через `/import/bgg`: обогащает
      description, designers, mechanics и т.д. ON CONFLICT обновляет поля,
      `source` поднимается до 'xml-api' (не понижается обратно).
    """

    __tablename__ = "game_bgg"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    bgg_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)

    # ranks-выгрузка
    rank: Mapped[int | None] = mapped_column(Integer, index=True)
    bayes_average: Mapped[float | None] = mapped_column(Float)
    average: Mapped[float | None] = mapped_column(Float)
    users_rated: Mapped[int | None] = mapped_column(Integer)
    is_expansion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # {strategygames: 1, thematic: 5, ...} — bucket-ranks по жанрам.
    subtype_ranks: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # XML API дополнительно (заполняется по факту /import/bgg)
    description: Mapped[str | None] = mapped_column(Text)
    designers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    artists: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    publishers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    mechanics: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    min_players: Mapped[int | None] = mapped_column(Integer)
    max_players: Mapped[int | None] = mapped_column(Integer)
    min_age: Mapped[int | None] = mapped_column(Integer)
    playtime_min: Mapped[int | None] = mapped_column(Integer)
    playtime_max: Mapped[int | None] = mapped_column(Integer)
    image_url: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)

    # Расширенная статистика BGG XML (миграция 0012, CAT-5). Источник истины
    # для этих метрик — XML API: CSV-выгрузка не содержит average_weight /
    # num_weights и отстаёт от XML на ~неделю. CSV перестаёт обновлять
    # эти поля начиная с 0012 (см. import_bgg_ranks.py — поля исключены
    # из ON CONFLICT set_).
    average_weight: Mapped[float | None] = mapped_column(Float)  # complexity 1.00–5.00
    num_weights: Mapped[int | None] = mapped_column(Integer)
    # BGG <poll> рекомендации (CAT-6). recommended_players — raw подсчёты
    # per player count: {"1": {best, recommended, not_recommended}, "6+": {...}}.
    # Скаляры recommended_age / language_dependence — winning value из голосов
    # (tie → min). totalvotes=0 → NULL.
    recommended_players: Mapped[dict[str, dict[str, int]] | None] = mapped_column(JSONB)
    recommended_age: Mapped[int | None] = mapped_column(Integer)
    # language_dependence — диапазон 1..5, но используем Integer для консистентности
    # с остальными числовыми полями game_bgg (rank, users_rated, num_weights).
    language_dependence: Mapped[int | None] = mapped_column(Integer)
    # Timestamp последнего XML-обогащения (CAT-7). NULL означает «никогда не
    # обогащалось через XML API» — игра присутствует только из CSV-выгрузки.
    # Используется отдельно от `fetched_at` (который трогает любой upsert) для
    # точной фильтрации «нужно обогатить через XML» в enrich_batch.
    bgg_stats_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Аудит и raw. Для XML-обогащения raw содержит {"parsed": <asdict(BggGame)>,
    # "xml": <raw item XML>} — позволяет re-парсить из БД при расширении парсера
    # без повторных запросов к BGG (rate-limited 1/sec).
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str | None] = mapped_column(String(32))  # 'csv-ranks' | 'xml-api'
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )

    game: Mapped[Game] = relationship(back_populates="bgg")


class GameWikidata(Base):
    """Satellite-таблица Wikidata (1:1 с games).

    Источник: SPARQL-запрос по property P2339 (BGG ID) → entity-payload.
    Главная ценность для catalog'а — labels[ru]/aliases[ru] для матчинга
    оффер'ов из российских магазинов.
    """

    __tablename__ = "game_wikidata"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    bgg_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(32), index=True)
    found: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # {ru: 'Каркассон', en: 'Carcassonne', ...}
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    # {ru: ['Каркасон', ...], en: [...]}
    aliases: Mapped[dict[str, list[str]]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    descriptions: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    # Если SPARQL вернул несколько Q-id — пишем все, выбираем первый по
    # числовому порядку. Для аудита.
    matched_entities: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )

    game: Mapped[Game] = relationship(back_populates="wikidata")


class ApiKey(Base):
    """API-ключи для межсервисного доступа (этап 7).

    Сам ключ хранится только хешем (argon2/bcrypt — решим на этапе 7).
    scopes: 'ingest', 'read', 'admin' — массив, чтобы один ключ мог иметь несколько.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True)
    owner: Mapped[str] = mapped_column(String(128))  # 'parsers', 'web_test', 'mobile' и т.д.
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DicefestRawGame(Base):
    """Staging-таблица сырых данных с dicefest.ru (миграция 0003).

    Двухстадийная схема обогащения: парсер пишет ТОЛЬКО сюда, основная games/
    game_aliases не трогается. Промоушен (перенос данных в canonical БД с
    pg_trgm-матчингом и журналом для отката) — отдельная операция через UI
    в PR-2.

    raw_html хранится отдельно от raw JSONB — чтобы можно было перепарсить
    карточку при изменении селекторов БЕЗ повторного запроса к dicefest.
    raw JSONB — структурированный дамп вытащенных полей (страховка от
    потери данных при изменении парсера).
    """

    __tablename__ = "dicefest_raw_games"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    page_url: Mapped[str] = mapped_column(Text, nullable=False)

    # Извлечённые поля — все nullable, потому что сайт может менять структуру
    # или вообще не отдавать поле для конкретной игры.
    title_ru: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str | None] = mapped_column(Text)        # из «RU / EN»-разделителя
    publisher: Mapped[str | None] = mapped_column(Text)        # «Издатель в РФ» в UI
    release_status: Mapped[str | None] = mapped_column(Text)   # data-status code
    description: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text)
    # Цена в копейках (как принято в проекте). Из pair «Цена на предзаказе: 1990 руб».
    preorder_price: Mapped[int | None] = mapped_column(BigInteger)
    # Массив ссылок на внешние сайты ([{kind, url, label, external_id?}]).
    # default=list — на новых INSERT через ORM; server_default — на raw SQL.
    external_links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False, server_default="[]"
    )

    raw_html: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    source_listing: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )

    # Workflow для промоушена (PR-2):
    #   new (default) → promoted | skipped | rejected
    # `promoted_to_game_id` — денормализованная ссылка для quick-glance в админке.
    status: Mapped[str] = mapped_column(Text, default="new", nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_to_game_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    # sha256 от значимых полей карточки (без raw_html и fetched_at).
    # Используется detection-логикой: при повторном скрапе сравниваем хеш и
    # сразу понимаем, изменилась ли карточка. Заполняется при apply из run'а
    # или одноразовым backfill-скриптом. NULL для исторических записей —
    # detection-runner на лету пересчитает и сохранит.
    content_hash: Mapped[str | None] = mapped_column(String(64))


class ImportPromotionLog(Base):
    """Универсальный аудит-журнал промоушенов из staging в canonical БД.

    Используется всеми источниками (dicefest, в будущем BGA / dicebreaker).
    `raw_id` намеренно без FK — staging-таблицы per-provider
    (dicefest_raw_games / bga_raw_games / ...), общий внешний ключ невозможен.

    revert: НЕ удаляем строку, а пишем reverted_at + reverted_by + новую
    запись action='revert'. Так у нас полная история действий.
    """

    __tablename__ = "import_promotion_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    raw_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # link|create|skip|reject|revert
    game_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="SET NULL")
    )
    alias_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("game_aliases.id", ondelete="SET NULL")
    )
    satellite_created: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    performed_by: Mapped[str | None] = mapped_column(Text)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class GameDicefest(Base):
    """Satellite-таблица для dicefest (заполняется при промоушене).

    PK на id (а не game_id) + UNIQUE(game_id, slug) — одна canonical Game
    может иметь несколько satellite-записей при переизданиях (две dicefest-
    страницы → один canonical Game).
    """

    __tablename__ = "game_dicefest"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="CASCADE"), nullable=False
    )
    raw_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("dicefest_raw_games.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title_ru: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)        # «Издатель в РФ»
    release_status: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text)
    page_url: Mapped[str | None] = mapped_column(Text)
    preorder_price: Mapped[int | None] = mapped_column(BigInteger)   # копейки
    external_links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False, server_default="[]"
    )
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("game_id", "slug", name="uq_game_dicefest_game_slug"),
    )


class SourceScrapeRun(Base):
    """Изолированный «сухой прогон» скрапа источника (миграция 0007).

    Парсер пишет items сюда (через `SourceScrapeItem`), а не в провайдер-
    специфичный staging. В staging они переезжают только при явном
    `apply_run`. Так оператор может посмотреть, что изменилось на сайте,
    и решить — применять или отбросить (`discard_run`).

    Универсальная: `provider` — varchar, не enum, чтобы добавлять источники
    без миграций (BGA, Dicebreaker, Wikidata).
    """

    __tablename__ = "source_scrape_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # running → ready → applied | discarded
    #                ↘ failed (error_message заполнен)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default="running"
    )
    # Параметры запуска: max_items, only_year, performed_by и т.д.
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )
    # Агрегаты для UI: {new, updated, unchanged, total_slugs, errors, applied?}.
    totals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    # Ring-buffer строк прогресса (как в ImportJob.log_lines). Хранится
    # JSONB-массивом, чтобы UI получал готовый список без парсинга.
    log_lines: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False, server_default="[]"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    performed_by: Mapped[str | None] = mapped_column(Text)


class SourceScrapeItem(Base):
    """Item внутри run'а: одна страница источника + её diff (миграция 0007).

    payload — сырые поля карточки (DicefestGame as dict, без raw_html).
    raw_html в отдельной колонке — большой объём, не нужен для UI-diff'а,
    тащить его в каждый GET items было бы расточительно.

    `change_type`:
      new       — slug'а нет в staging
      updated   — slug есть, но content_hash отличается
      unchanged — slug есть, content_hash совпадает
    """

    __tablename__ = "source_scrape_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("source_scrape_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_html: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # `{field: {before, after}}` для UI. NULL для new/unchanged — экономим место.
    field_diffs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )


class MatchProfile(Base):
    """Сохранённая конфигурация матчинга для одного провайдера (миграция 0007).

    params — JSONB, чтобы добавлять параметры без миграций. Ожидаемая схема:

      {
        "threshold": 0.6,
        "prefer_external_id": true,
        "weights": {"ru": 1.0, "en": 1.0, "alias": 1.0}
      }

    is_default — отметка «дефолтный профиль провайдера». Partial UNIQUE
    `(provider) WHERE is_default = true` (создан в миграции) гарантирует
    ровно одного дефолта на провайдера.
    """

    __tablename__ = "match_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=_now,
        onupdate=_now,
    )

    __table_args__ = (
        UniqueConstraint("provider", "name", name="uq_match_profiles_provider_name"),
    )


class SchedulerConfig(Base):
    """Runtime-конфиг APScheduler-job'ов (таблица scheduler_configs, миграция 0010).

    Раньше cron-выражения жили в Settings (env). Теперь UI правит их через
    PATCH /scheduler/jobs/{id}/reschedule без рестарта сервиса. Settings оставлены
    как seed-дефолты при первом старте (миграция INSERT'ит дефолтные строки).

    `params` JSONB — provider-специфика (rank_le, batch_size, ...). Это убирает
    необходимость заводить отдельные колонки/Settings-поля под каждый параметр
    каждого job'а.

    `last_run_*` — денормализация: при ручном trigger или scheduler-запуске
    обновляем эти три поля, чтобы UI мог отрисовать health-блок одним SELECT'ом
    без JOIN с import_jobs + MAX по типу.
    """

    __tablename__ = "scheduler_configs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    last_run_job_id: Mapped[int | None] = mapped_column(BigInteger)
    last_run_status: Mapped[str | None] = mapped_column(String(16))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )


class RuntimeFlag(Base):
    """Хранилище runtime-настроек, которые должны меняться без рестарта
    (таблица runtime_flags, миграция 0013).

    Семантический сосед `SchedulerConfig` — оба хранят значения, переопределяющие
    Settings, и обновляются через REST без перезапуска. Отличие: SchedulerConfig
    специализирован под APScheduler-job'ы, RuntimeFlag — general-purpose bool/int
    (сейчас единственный потребитель — `ml_enabled` kill-switch для matching v2).

    `Settings` обёрнут в `@lru_cache` per-process, поэтому значение из ENV/`.env`
    фризится при первом обращении — хот-перезагрузка через Settings невозможна
    без `cache_clear()` и broadcast по инстансам. RuntimeFlag решает это через БД.

    Схема намеренно минимальная — одна колонка на тип значения. Если завтра
    понадобится string/int флаг, добавляем `value_str` / `value_int` без
    миграции данных по существующим ключам.

    Чтение — через `catalog.runtime_flags.is_ml_enabled` / `get_bool` (in-memory
    TTL-кэш 5 сек, чтобы не бомбить БД на каждый ingest), запись — через
    `PATCH /admin/runtime-flags/{key}`.
    """

    __tablename__ = "runtime_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now,
    )
    updated_by: Mapped[str | None] = mapped_column(Text)


class BggGeeklist(Base):
    """Snapshot'ы BGG GeekList-ов (таблица bgg_geeklists, миграция 0010).

    BGG GeekList — кураторский список thing-id с названием, описанием и опциональным
    комментарием на каждую позицию. Используется для monthly «BGG Top 50 Most Played»
    (id типа 367126) и любых других кураторских топов.

    Отличие от bgg_hotness:
      - Hotness — ровно 50 позиций, ежедневно, фиксированная схема BGG → отдельные
        строки в bgg_hotness для per-bgg_id индексации.
      - GeekList — произвольной длины (50–1000+), on-demand → items как JSONB-array.
        Per-item индексация не нужна: auto-import (resolve game_id, enrich_one) делается
        в момент загрузки, потом этот snapshot — read-only история.

    UNIQUE (geeklist_id, snapshot_date) — повторный прогон в тот же день идемпотентен.
    """

    __tablename__ = "bgg_geeklists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    geeklist_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)  # owner на BGG
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # items: [{rank, bgg_id, name, year, thumbnail_url, body, game_id?}, ...]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )

    __table_args__ = (
        UniqueConstraint("geeklist_id", "snapshot_date", name="uq_bgg_geeklist_date"),
    )


class BggHotness(Base):
    """История BGG Hotness-снимков (таблица bgg_hotness, миграция 0009).

    BGG обновляет список ~50 «горячих» игр ежедневно. Каждый ежедневный
    snapshot — отдельные строки (fetched_date, bgg_id). ON CONFLICT DO NOTHING
    на uq_bgg_hotness_date_bgg гарантирует идемпотентность при повторных
    запусках в тот же день.

    game_id — денормализованная ссылка на canonical game (nullable, SET NULL
    при удалении game). Позволяет быстро джойнить без поиска по bgg_id.
    """

    __tablename__ = "bgg_hotness"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Дата снимка (UTC-день). Один снимок в день — сравнение WHERE date = today() дёшево.
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    bgg_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    # Ссылка на canonical game (SET NULL при merge/удалении игры).
    game_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("games.id", ondelete="SET NULL"),
        index=True,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )

    __table_args__ = (
        UniqueConstraint("snapshot_date", "bgg_id", name="uq_bgg_hotness_date_bgg"),
    )


# ─── Matching v2 (миграция 0011) ──────────────────────────────────────────────


class MatchDecision(Base):
    """Tier-0 кэш: нормализованный title → game_id (миграция 0011).

    Tier 0 в matcher v2 — это дешёвый lookup по title_norm перед запуском trgm/
    embedding/LLM. Запись создаётся при любом успешном auto/manual матче и
    инвалидируется при unlink/reject/revert.

    TTL per source — для «свежести» AI-решений: manual=∞, auto_t1=30 дней,
    auto_t2=14, auto_t3=7. Tier 0 проверяет (decided_at + ttl_days > now()) и
    игнорирует протухшие записи (они «доспеют» в следующем reassess).

    game_id NULL = «это не игра» (negative cache, заполняется reject-операцией).
    """

    __tablename__ = "match_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title_norm: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    game_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="CASCADE"),
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    tier: Mapped[int | None] = mapped_column(SmallInteger)
    ttl_days: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now,
    )


class MatchLog(Base):
    """Аудит изменений offers.game_id/match_status (миграция 0011).

    Запись создаётся через service-слой (engine/router) при любом изменении
    привязки оффера — auto, manual, reject, unlink, reassess, revert. Это даёт:
      - performed_by (system|worker|llm|api-key owner)
      - точный action (важно для UI badge)
      - prev/new pair для безопасного отката

    Bulk-revert через batch_id (UUID): один reassess-all создаёт N записей с
    общим batch_id; потом одной транзакцией можно откатить весь batch.

    alias_created_id — связанный alias, добавленный при auto/manual матче.
    При revert(delete_alias=True) — удаляется этот алиас.
    """

    __tablename__ = "match_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False,
    )
    prev_game_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="SET NULL"),
    )
    new_game_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="SET NULL"),
    )
    prev_status: Mapped[str | None] = mapped_column(String(16))
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    tier: Mapped[int | None] = mapped_column(SmallInteger)
    score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    batch_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    alias_created_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("game_aliases.id", ondelete="SET NULL"),
    )
    performed_by: Mapped[str | None] = mapped_column(Text)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now,
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by: Mapped[str | None] = mapped_column(Text)


class MatchQueue(Base):
    """Outbox для async tier'ов T2/T3 (миграция 0011).

    Когда `/ingest/offers` синхронно (T0+T1) не дал уверенного матча — пушим
    оффер сюда со status='pending'. APScheduler-воркер (`match_worker_job`)
    каждые N секунд берёт batch через `SELECT FOR UPDATE SKIP LOCKED`,
    обрабатывает T2 (vector) → T3 (LLM) → финализирует offer.

    Почему отдельная таблица а не флаг в offers:
      - retry с exponential backoff через next_attempt_at (нужно отдельное поле)
      - priority (manual reassess приоритетнее auto)
      - observability через простой SELECT COUNT(*) WHERE status='pending'
      - не загромождаем offers оперативным состоянием
    UNIQUE(offer_id) — одна запись на оффер. ON CONFLICT DO NOTHING на повторе.
    """

    __tablename__ = "match_queue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False,
    )
    store_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    title_raw: Mapped[str] = mapped_column(Text, nullable=False)
    title_norm: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending",
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_game_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="SET NULL"),
    )
    result_score: Mapped[float | None] = mapped_column(Float)
    result_tier: Mapped[int | None] = mapped_column(SmallInteger)
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now,
    )
    # Момент когда воркер забрал запись через claim_batch (status='processing').
    # NULL до первого claim. `recover_stuck` использует именно это поле — не
    # `created_at`, иначе при горячем рестарте только что заклеймленная запись
    # с давним created_at ошибочно возвращалась бы в pending.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("offer_id", name="uq_match_queue_offer"),
    )


class GameEmbedding(Base):
    """Vector(1024) от bge-m3 (миграция 0011).

    Каждая строка = один embedded text:
      - alias_id IS NULL → вектор от game.title (либо составленного из title +
        title_ru, см. embedder.build_text())
      - alias_id IS NOT NULL → вектор от alias_text

    UNIQUE (game_id, alias_id) — одна game может иметь N embeddings (по одному
    на title + каждый alias). При vector_search возвращаем лучший hit per game
    через GROUP BY game_id + MAX(score).

    text_used — точная строка, поданная в модель. Хранится для отладки и
    реиндексации после смены модели (model='bge-m3' → 'bge-m3-v2'): можно
    SELECT text_used WHERE model='bge-m3' и пере-embed одним проходом.

    HNSW-индекс по embedding vector_cosine_ops (m=16, ef_construction=128) —
    создаётся в миграции через raw SQL (alembic не имеет hnsw поддержки).
    """

    __tablename__ = "game_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    alias_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("game_aliases.id", ondelete="CASCADE"),
    )
    text_used: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    model: Mapped[str] = mapped_column(
        String(64), nullable=False, default="bge-m3", server_default="bge-m3",
    )
    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now,
    )

    __table_args__ = (
        UniqueConstraint("game_id", "alias_id", name="uq_game_embeddings_pair"),
    )
