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

    cover_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # meta — свободные доп. поля (механики, рейтинг BGG, категории).
    # JSONB позволяет индексировать по ключам, в отличие от JSON.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

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

    raw_extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

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
    """Асинхронные импорты из BGG/Tesera (этапы 3-4).

    payload — параметры запуска (например, {'bgg_id': 822}); status —
    pending/running/done/failed; error — стектрейс/сообщение в случае failed.
    """

    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)  # 'bgg', 'tesera'
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

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
