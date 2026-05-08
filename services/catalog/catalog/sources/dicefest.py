"""Dicefest scraper — provider-agnostic обёртка вокруг существующего парсера.

Сам парсер живёт в `catalog.importers.dicefest` (parse_card_html, fetch_card,
collect_all_slugs). Здесь — только адаптация к интерфейсу `SourceScraper`:
сборка `SourceItemPayload` с `content_hash` и UPSERT в staging при apply.

Намеренно не дублируем парсинг, fetch с retry и rate-limit — runner сам
управляет паузами между запросами; внутренний retry-механизм оригинального
`fetch_with_retry` остаётся.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, ClassVar

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.importers.dicefest import (
    collect_all_slugs as _collect_all_slugs,
    fetch_card as _fetch_card,
    parse_card_html as _parse_card_html,
    upsert_dicefest_raw as _upsert_dicefest_raw,
)
from catalog.importers.dicefest import DicefestGame
from catalog.sources.base import ScraperParams, SourceItemPayload
from catalog.sources.diff import compute_content_hash


class DicefestSourceScraper:
    """Реализация SourceScraper для dicefest.ru."""

    provider: ClassVar[str] = "dicefest"

    @classmethod
    async def collect_slugs(
        cls,
        client: httpx.AsyncClient,
        params: ScraperParams,
    ) -> tuple[list[str], dict[str, str]]:
        slugs, slug_to_source = await _collect_all_slugs(
            client, only_year=params.only_year,
        )
        if params.max_items:
            slugs = slugs[: params.max_items]
            slug_to_source = {s: slug_to_source[s] for s in slugs if s in slug_to_source}
        return slugs, slug_to_source

    @classmethod
    async def fetch_one(
        cls,
        client: httpx.AsyncClient,
        slug: str,
    ) -> SourceItemPayload:
        html = await _fetch_card(client, slug)
        game: DicefestGame = _parse_card_html(html, slug)
        # Преобразуем dataclass в dict; raw_html отделяем — он живёт отдельной
        # колонкой и не участвует в diff/hash.
        as_dict = asdict(game)
        raw_html = as_dict.pop("raw_html", "") or None
        content_hash = compute_content_hash(as_dict)
        return SourceItemPayload(
            slug=slug,
            payload=as_dict,
            raw_html=raw_html,
            content_hash=content_hash,
        )

    @classmethod
    def staging_table(cls) -> str:
        return "dicefest_raw_games"

    @classmethod
    async def apply_payload(
        cls,
        session: AsyncSession,
        slug: str,
        payload: dict[str, Any],
        raw_html: str | None,
        content_hash: str,
        source_listing: str | None,
    ) -> int:
        """Сконструировать DicefestGame из payload и переиспользовать существующий
        upsert. Дополнительно записываем content_hash отдельным апдейтом —
        старый upsert о нём не знает.
        """
        game = DicefestGame(
            slug=slug,
            page_url=payload.get("page_url") or "",
            title_ru=payload.get("title_ru"),
            title_en=payload.get("title_en"),
            publisher=payload.get("publisher"),
            release_status=payload.get("release_status"),
            description=payload.get("description"),
            cover_url=payload.get("cover_url"),
            preorder_price=payload.get("preorder_price"),
            external_links=payload.get("external_links") or [],
            raw_html=raw_html or "",
            raw=payload.get("raw") or {},
        )
        raw_id = await _upsert_dicefest_raw(session, game, source_listing)
        # Обновляем content_hash отдельно — старый upsert о нём не знает,
        # править его сигнатуру нежелательно (вызывается из других мест).
        from sqlalchemy import update

        from catalog.models import DicefestRawGame

        await session.execute(
            update(DicefestRawGame)
            .where(DicefestRawGame.id == raw_id)
            .values(content_hash=content_hash),
        )
        return raw_id
