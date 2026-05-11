"""Оркестратор BGG: связывает client + parser + repository в high-level операции.

- `search_games(query)` — поиск по запросу через `/search` (Этап 1).
- `enrich_one(bgg_id)` — fetch одной игры через `/thing` + parse + upsert.
- `enrich_batch(rank_le, batch_size, ...)` — batched-обогащение топ-N игр
  с rate-limit между батчами (BGG best practice ≈1 req/sec).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.db import get_engine
from catalog.models import GameBgg
from catalog.parsers.bgg.client import THING_BATCH_MAX, BggClient
from catalog.parsers.bgg.models import BggGame, BggSearchHit
from catalog.parsers.bgg.parser import parse_search_xml, parse_thing_xml
from catalog.parsers.bgg.repository import upsert_bgg_data

logger = logging.getLogger(__name__)


# ─── search (этап 1) ─────────────────────────────────────────────────────────


async def search_games(
    query: str,
    *,
    limit: int = 20,
    exact: bool = False,
    client: BggClient | None = None,
) -> list[BggSearchHit]:
    """Поиск игр по запросу через BGG `/search`.

    BGG не поддерживает параметр limit на стороне API — отдаёт всё, что
    нашёл. Усечение делаем сами.

    `client=None` → создаём свой `BggClient` на одну операцию. Для сценария
    «много поисков подряд» (batch enrich) лучше передавать готовый client
    снаружи, чтобы переиспользовать TCP/TLS.
    """
    own_client = client is None
    if client is None:
        # from_settings — иначе BGG XML API v2 вернёт 401 (Bearer token обязателен
        # с июля 2025). Тесты передают внешний `client` с MockTransport напрямую.
        client = BggClient.from_settings()
    try:
        if own_client:
            await client.__aenter__()
        xml_text = await client.search(query, exact=exact)
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    hits = parse_search_xml(xml_text)
    if limit > 0:
        hits = hits[:limit]
    return hits


# ─── enrich (этап 2) ─────────────────────────────────────────────────────────


@dataclass
class EnrichStats:
    """Сводка одного прогона `enrich_batch`."""

    enriched: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enriched": self.enriched,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors[:50],  # первые 50 — для job.result
        }


# Сигнатура callback'а для прогресса. async, чтобы можно было flush'ить
# `LogBuffer` в БД (этап 3 интеграция с ImportJob).
ProgressCb = Callable[[int, int, BggGame | None], Awaitable[None]]


def _parse_things_xml(xml_text: str) -> list[BggGame]:
    """Парсит batch-ответ `/thing?id=1,2,3`. Каждый <item> → BggGame.

    Зачем не использовать `parse_thing_xml`: тот находит первый `<item>` и
    возвращает один. Здесь нужны все. Логика парсинга одного item'а — уже
    в `parse_thing_xml`, дублировать не хочу: эмитим под-XML на каждый item
    и переиспользуем его.
    """
    root = ET.fromstring(xml_text)
    games: list[BggGame] = []
    for item in root.findall("item"):
        # Оборачиваем item в фейковый <items>...</items>, чтобы переиспользовать
        # `parse_thing_xml`, который ожидает root <items>.
        sub = ET.Element("items")
        sub.append(item)
        sub_xml = ET.tostring(sub, encoding="unicode")
        bgg = parse_thing_xml(sub_xml)
        if bgg is not None:
            games.append(bgg)
    return games


async def enrich_one(
    bgg_id: int,
    session: AsyncSession,
    *,
    client: BggClient | None = None,
) -> BggGame | None:
    """Fetch одной игры через `/thing` + parse + upsert. Не коммитит сессию.

    Возвращает `BggGame` (если игра найдена) или None (BGG отдаёт пустой
    `<items/>` для несуществующих id).
    """
    own_client = client is None
    if client is None:
        # from_settings — иначе BGG XML API v2 вернёт 401 (Bearer token обязателен
        # с июля 2025). Тесты передают внешний `client` с MockTransport напрямую.
        client = BggClient.from_settings()
    try:
        if own_client:
            await client.__aenter__()
        xml_text = await client.fetch_thing(bgg_id)
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    bgg = parse_thing_xml(xml_text)
    if bgg is None:
        return None
    await upsert_bgg_data(session, bgg)
    return bgg


def _chunked(items: list[int], size: int) -> Iterable[list[int]]:
    """Разбивает список на пачки заданного размера. Для batch /thing-запросов."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _select_enrich_candidates(
    session: AsyncSession,
    *,
    rank_le: int | None,
    skip_recent_days: int,
    limit: int | None,
) -> list[int]:
    """Выбирает bgg_id'ы кандидатов на enrich.

    Условия:
      - rank IS NOT NULL (только ranked игры — у несранкованных нет смысла
        тянуть полный XML на этапе 2)
      - rank <= rank_le (если задан)
      - source IS DISTINCT FROM 'xml-api' OR fetched_at < now() - skip_recent_days
        (skip_recent_days=0 → не пропускаем недавние, прогон полный)

    Сортировка по rank ASC — топ-N сначала. Это даёт смысл для интерактивного
    запуска через UI: оператор видит, что популярные игры обогатились первыми.
    """
    stmt = select(GameBgg.bgg_id).where(GameBgg.rank.is_not(None)).order_by(GameBgg.rank)
    if rank_le is not None:
        stmt = stmt.where(GameBgg.rank <= rank_le)
    if skip_recent_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=skip_recent_days)
        # Свежие записи ('xml-api', fetched_at >= cutoff) пропускаем.
        # Игры с source='csv-ranks' проходят всегда — они ещё не обогащены.
        stmt = stmt.where(
            (GameBgg.source.is_distinct_from("xml-api")) | (GameBgg.fetched_at < cutoff),
        )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def enrich_batch(
    *,
    rank_le: int | None = None,
    batch_size: int = THING_BATCH_MAX,
    skip_recent_days: int = 30,
    limit: int | None = None,
    dry_run: bool = False,
    rate_limit_sec: float = 1.0,
    progress_cb: ProgressCb | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    client: BggClient | None = None,
) -> EnrichStats:
    """Batch-обогащение топ-N игр через `/thing?id=<id1,id2,...>`.

    Параметры:
      - `rank_le=1000` — только игры с BGG rank ≤ 1000 (топ-1000).
      - `batch_size=20` — сколько ID за один запрос. Лимит BGG = 20.
      - `skip_recent_days=30` — не перезапрашивать игры, обогащённые недавно
        (resume-state без отдельной таблицы). 0 → форсировать всё.
      - `limit=N` — общий потолок на количество ID за прогон (для тестов /
        пробного прогона).
      - `dry_run=True` — не пишет в БД, только считает кандидатов и эмитит
        вызовы `progress_cb` (если задан) с None в третьем аргументе.
      - `rate_limit_sec=1.0` — задержка между batch-запросами (best practice
        BGG). 0 → без задержки (для тестов).
      - `progress_cb(i, total, BggGame | None)` — вызывается после каждой
        обработанной игры. None в 3-ем аргументе — игра не найдена / failed.
      - `session_factory=None` → используем дефолт от catalog.db.get_engine().

    Возвращает `EnrichStats`. Не коммитит на dry_run; commit'ит batch'ами
    (один commit на batch_size игр) вне dry_run.
    """
    if batch_size < 1 or batch_size > THING_BATCH_MAX:
        raise ValueError(f"batch_size должен быть 1..{THING_BATCH_MAX}; получено {batch_size}")

    if session_factory is None:
        engine = get_engine()
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

    own_client = client is None
    if client is None:
        # from_settings — иначе BGG XML API v2 вернёт 401 (Bearer token обязателен
        # с июля 2025). Тесты передают внешний `client` с MockTransport напрямую.
        client = BggClient.from_settings()

    stats = EnrichStats()

    try:
        if own_client:
            await client.__aenter__()

        # ── 1. отбор кандидатов ───────────────────────────────────────────
        async with session_factory() as session:
            candidates = await _select_enrich_candidates(
                session,
                rank_le=rank_le,
                skip_recent_days=skip_recent_days,
                limit=limit,
            )

        total = len(candidates)
        if total == 0:
            logger.info("enrich_batch: нет кандидатов (rank_le=%s, skip_recent=%s)", rank_le, skip_recent_days)
            return stats

        # ── 2. batch-обработка ────────────────────────────────────────────
        processed = 0
        first_batch = True
        for chunk in _chunked(candidates, batch_size):
            # Rate-limit между батчами (не перед первым).
            if not first_batch and rate_limit_sec > 0:
                await asyncio.sleep(rate_limit_sec)
            first_batch = False

            # Маппинг bgg_id → got, чтобы понять, что не вернулось.
            got: dict[int, BggGame] = {}
            try:
                xml_text = await client.fetch_things(chunk)
                for bgg in _parse_things_xml(xml_text):
                    got[bgg.bgg_id] = bgg
            except Exception as exc:  # noqa: BLE001 — fault tolerance
                logger.exception("BGG batch failed: ids=%s", chunk)
                # Весь batch проваливается — все его ID идут в errors.
                for bgg_id in chunk:
                    stats.failed += 1
                    stats.errors.append({"bgg_id": bgg_id, "error": str(exc)})
                    processed += 1
                    if progress_cb is not None:
                        await progress_cb(processed, total, None)
                continue

            # Upsert каждого + collect skipped (BGG не вернул такой ID).
            if not dry_run:
                async with session_factory() as session:
                    for bgg_id in chunk:
                        bgg = got.get(bgg_id)
                        processed += 1
                        if bgg is None:
                            stats.skipped += 1
                            if progress_cb is not None:
                                await progress_cb(processed, total, None)
                            continue
                        try:
                            await upsert_bgg_data(session, bgg)
                            stats.enriched += 1
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("upsert failed for bgg_id=%s", bgg_id)
                            stats.failed += 1
                            stats.errors.append({"bgg_id": bgg_id, "error": str(exc)})
                        if progress_cb is not None:
                            await progress_cb(processed, total, bgg)
                    await session.commit()
            else:
                # dry_run: считаем, что все вернувшиеся были бы обогащены.
                for bgg_id in chunk:
                    processed += 1
                    bgg = got.get(bgg_id)
                    if bgg is None:
                        stats.skipped += 1
                    else:
                        stats.enriched += 1
                    if progress_cb is not None:
                        await progress_cb(processed, total, bgg)

    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    logger.info(
        "enrich_batch done: enriched=%d skipped=%d failed=%d (dry_run=%s)",
        stats.enriched, stats.skipped, stats.failed, dry_run,
    )
    return stats


# Опциональный высокоуровневый итератор по результатам — на случай, если
# вызывающему нужен поток, а не коллбэк. Не используем сейчас, оставлен для
# UI с SSE.
async def iter_enrich(
    *,
    rank_le: int | None = None,
    batch_size: int = THING_BATCH_MAX,
    skip_recent_days: int = 30,
    limit: int | None = None,
    rate_limit_sec: float = 1.0,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    client: BggClient | None = None,
) -> AsyncIterator[tuple[int, int, BggGame | None]]:  # pragma: no cover - util
    """Async-итератор, эмитит (processed, total, bgg | None) на каждом шаге.

    Вызывает `enrich_batch` через коллбэк, который отправляет события в
    `asyncio.Queue`. Полезно для SSE-обвязки в /sources-стиле endpoint.
    """
    queue: asyncio.Queue[tuple[int, int, BggGame | None] | None] = asyncio.Queue()

    async def _cb(i: int, total: int, bgg: BggGame | None) -> None:
        await queue.put((i, total, bgg))

    async def _runner() -> None:
        try:
            await enrich_batch(
                rank_le=rank_le,
                batch_size=batch_size,
                skip_recent_days=skip_recent_days,
                limit=limit,
                rate_limit_sec=rate_limit_sec,
                progress_cb=_cb,
                session_factory=session_factory,
                client=client,
            )
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(_runner())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        await task
