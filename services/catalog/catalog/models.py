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

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    # Аудит и raw
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
