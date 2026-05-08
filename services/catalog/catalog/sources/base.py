"""Provider-agnostic интерфейс скрапера + реестр.

Каждый источник реализует Protocol `SourceScraper`. Runner (см. runner.py)
не знает про конкретный сайт — он умеет: «по списку params собери slugи,
для каждого slug'а получи payload + content_hash, классифицируй diff».

Реестр `REGISTRY` нужен, чтобы роутер `/sources/{provider}/...` мог найти
нужный скрапер по строке.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, Type

import httpx


@dataclass
class ScraperParams:
    """Параметры одного запуска. Сериализуются как JSONB в `source_scrape_runs.params`.

    Часть полей провайдер-специфична (only_year — только Dicefest), но мы
    держим их в одном dataclass для удобства передачи. Скрапер берёт только
    то, что понимает.
    """

    max_items: int | None = None
    only_year: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_items": self.max_items,
            "only_year": self.only_year,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ScraperParams:
        if not data:
            return cls()
        return cls(
            max_items=data.get("max_items"),
            only_year=data.get("only_year"),
            extra=data.get("extra") or {},
        )


@dataclass
class SourceItemPayload:
    """Результат `fetch_one`: достаточно, чтобы апсёртнуть в провайдер-staging.

    `payload` — словарь с полями карточки (для Dicefest: title_ru, title_en,
    publisher, …, external_links). НЕ содержит raw_html, чтобы UI и сравнения
    не таскали его без нужды.

    `raw_html` хранится отдельно для re-parse сценариев. Может быть None,
    если у провайдера нет понятия HTML (например, JSON API).

    `content_hash` считает сам скрапер — его реализация знает, какие поля
    действительно меняются, какие шумят (timestamps, query string).
    """

    slug: str
    payload: dict[str, Any]
    raw_html: str | None
    content_hash: str
    # Метаданные для аналитики/дедупа: откуда нашли slug (homepage, year=2024).
    source_listing: str | None = None


class SourceScraper(Protocol):
    """Интерфейс скрапера источника.

    Реализующие классы — обычно с classmethod'ами и без состояния (HTTP-клиент
    приходит снаружи, чтобы runner управлял rate-limit'ом и retry).
    """

    provider: ClassVar[str]
    """Короткий идентификатор: 'dicefest', 'bga', 'dicebreaker'.
    Используется как ключ в REGISTRY и колонке БД."""

    @classmethod
    async def collect_slugs(
        cls,
        client: httpx.AsyncClient,
        params: ScraperParams,
    ) -> tuple[list[str], dict[str, str]]:
        """Собрать все slug'и, которые надо обработать.

        Возвращает (sorted_slugs, {slug: source_listing}).
        """
        ...

    @classmethod
    async def fetch_one(
        cls,
        client: httpx.AsyncClient,
        slug: str,
    ) -> SourceItemPayload:
        """Скачать и распарсить одну карточку. Может бросать httpx.HTTPError."""
        ...

    @classmethod
    def staging_table(cls) -> str:
        """Имя SQL-таблицы провайдер-специфичного staging.

        Runner.apply_run использует её, чтобы найти текущий content_hash для
        slug'а и сделать UPSERT при apply.
        """
        ...

    @classmethod
    async def apply_payload(
        cls,
        session: Any,  # AsyncSession — typing-уровень избегаем циклы
        slug: str,
        payload: dict[str, Any],
        raw_html: str | None,
        content_hash: str,
        source_listing: str | None,
    ) -> int:
        """UPSERT payload в провайдер-staging. Возвращает id записи в staging.

        Этот метод знает специфику таблицы (какие колонки, что в JSONB).
        Для Dicefest — обёртка над `upsert_dicefest_raw`.
        """
        ...


REGISTRY: dict[str, Type[SourceScraper]] = {}
"""Заполняется в `catalog.sources.__init__`. Ключ — `provider`."""


def get_scraper(provider: str) -> Type[SourceScraper]:
    """Раздобыть скрапер по строке провайдера. Бросает ValueError, если нет."""
    try:
        return REGISTRY[provider]
    except KeyError as exc:
        known = ", ".join(sorted(REGISTRY)) or "(none)"
        raise ValueError(
            f"Unknown source provider: {provider!r}. Known: {known}",
        ) from exc
