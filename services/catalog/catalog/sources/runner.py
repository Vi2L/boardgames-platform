"""Runner — оркестрация detection / apply / discard для одного run'а.

Архитектура одного прогона detection:

    1. Роутер создаёт `SourceScrapeRun` (status=running) и launch'ит
       `asyncio.create_task(run_detection(run_id))`. HTTP-ответ возвращается
       сразу с run_id — UI начинает polling'ом GET /runs/{id}.

    2. `run_detection` поднимает свою сессию (важно: фоновая задача не
       должна делить сессию с HTTP-handler'ом), httpx-клиент с UA, обходит
       slug'и, считает content_hash, классифицирует diff и пишет items.

    3. На каждый ~20-й item flush'ится прогресс/лог (через `RunLogBuffer`)
       и `totals`, чтобы UI видел движение в real-time.

    4. На finally — финальный flush, перевод status в `ready` (или `failed`),
       закрытие сессии.

Apply / Discard — синхронные операции из роутера. Apply UPSERT'ит выбранные
items в провайдер-staging через `scraper.apply_payload`.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.db import get_engine
from catalog.importers.dicefest import (
    RATE_LIMIT_JITTER_SEC,
    RATE_LIMIT_SEC,
    USER_AGENT,
)
from catalog.models import SourceScrapeItem, SourceScrapeRun
from catalog.sources.base import ScraperParams, SourceScraper
from catalog.sources.diff import compute_content_hash, compute_field_diffs

logger = logging.getLogger(__name__)

RING_SIZE = 200  # как в LogBuffer — ring-buffer log_lines
FLUSH_EVERY_N = 20
FLUSH_EVERY_S = 2.0


class RunLogBuffer:
    """Тонкий аналог `_log_buffer.LogBuffer` для `SourceScrapeRun`.

    Не переиспользуем оригинал, потому что у нас другая модель и нет
    `progress` (мы храним totals). Структура та же: накапливаем строки в
    памяти, flush'им раз в N строк или раз в M секунд.
    """

    def __init__(
        self,
        session: AsyncSession,
        run_id: int,
        *,
        flush_every_n: int = FLUSH_EVERY_N,
        flush_every_s: float = FLUSH_EVERY_S,
        ring_size: int = RING_SIZE,
    ) -> None:
        self._session = session
        self._run_id = run_id
        self._flush_every_n = flush_every_n
        self._flush_every_s = flush_every_s
        self._ring_size = ring_size

        self._lines: list[str] = []
        self._totals: dict[str, Any] | None = None
        self._unflushed_lines = 0
        self._last_flush_ts = time.monotonic()

    def log(self, line: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._lines.append(f"[{ts}] {line}")
        if len(self._lines) > self._ring_size:
            self._lines = self._lines[-self._ring_size :]
        self._unflushed_lines += 1

    def set_totals(self, totals: dict[str, Any]) -> None:
        # merge-семантика: новые ключи дополняют старые.
        if self._totals is None:
            self._totals = {}
        self._totals.update(totals)

    async def maybe_flush(self) -> bool:
        elapsed = time.monotonic() - self._last_flush_ts
        if (
            self._unflushed_lines >= self._flush_every_n
            or elapsed >= self._flush_every_s
        ):
            await self.flush()
            return True
        return False

    async def flush(self) -> None:
        if self._unflushed_lines == 0 and self._totals is None:
            return
        values: dict[str, Any] = {"log_lines": list(self._lines)}
        if self._totals is not None:
            values["totals"] = dict(self._totals)
        await self._session.execute(
            update(SourceScrapeRun)
            .where(SourceScrapeRun.id == self._run_id)
            .values(**values),
        )
        await self._session.commit()
        self._unflushed_lines = 0
        self._last_flush_ts = time.monotonic()


# ─── Detection ────────────────────────────────────────────────────────────────


async def _load_existing_hashes(
    session: AsyncSession, table: str, slugs: list[str],
) -> dict[str, tuple[str | None, dict[str, Any] | None]]:
    """Подтянуть текущие (content_hash, payload-snapshot) по slug'ам staging-таблицы.

    Для UPDATE-классификации нам нужен и hash (быстрая сверка), и payload
    (для compute_field_diffs). У DicefestRawGame payload-фрагменты разбросаны
    по колонкам — соберём похожий dict, чтобы diff показывал внятные before/after.

    Универсальность: SQL делается с `text()` по имени таблицы, потому что
    структура per-provider. Сейчас — только dicefest. Когда появятся другие
    провайдеры, расширим этот mapper.
    """
    if not slugs:
        return {}

    if table == "dicefest_raw_games":
        # asyncpg сам преобразует Python list → text[]; explicit CAST в SQL
        # помогает type-inference у driver'а. SQLAlchemy `expanding=True` тут
        # не подходит — оно генерирует `IN (...)`, а нам нужен ANY(array).
        sql = text(
            """
            SELECT slug,
                   content_hash,
                   jsonb_build_object(
                     'slug', slug,
                     'page_url', page_url,
                     'title_ru', title_ru,
                     'title_en', title_en,
                     'publisher', publisher,
                     'release_status', release_status,
                     'description', description,
                     'cover_url', cover_url,
                     'preorder_price', preorder_price,
                     'external_links', external_links,
                     'raw', raw
                   ) AS payload_snapshot
            FROM dicefest_raw_games
            WHERE slug = ANY(CAST(:slugs AS text[]))
            """
        )
        result = await session.execute(sql, {"slugs": slugs})
    else:
        raise NotImplementedError(f"Snapshot loader не реализован для {table!r}")

    out: dict[str, tuple[str | None, dict[str, Any] | None]] = {}
    for slug, content_hash, snapshot in result.all():
        out[slug] = (content_hash, snapshot)
    return out


async def _backfill_existing_hash(
    session: AsyncSession, table: str, slug: str, payload_snapshot: dict[str, Any],
) -> str:
    """Если у существующей staging-записи `content_hash IS NULL` — посчитать на
    лету и сохранить, чтобы следующий прогон не пересчитывал то же самое.

    Возвращает посчитанный хеш. Не падает при конфликте с параллельным
    backfill'ом — UPDATE идёт по slug, и мы лишь освежаем поле.
    """
    h = compute_content_hash(payload_snapshot)
    if table == "dicefest_raw_games":
        await session.execute(
            text(
                "UPDATE dicefest_raw_games SET content_hash = :h "
                "WHERE slug = :slug AND content_hash IS NULL"
            ),
            {"h": h, "slug": slug},
        )
        await session.commit()
    return h


def _classify(
    prev_hash: str | None,
    prev_payload: dict[str, Any] | None,
    new_hash: str,
    new_payload: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]] | None]:
    """Вернуть (change_type, field_diffs).

    new       — slug'а нет в staging
    unchanged — content_hash совпадает
    updated   — отличается, считаем field_diffs для UI
    """
    if prev_hash is None and prev_payload is None:
        return "new", None
    if prev_hash == new_hash:
        return "unchanged", None
    diffs = compute_field_diffs(prev_payload, new_payload)
    return "updated", diffs


async def run_detection(
    run_id: int,
    scraper: type[SourceScraper],
    params: ScraperParams,
) -> None:
    """Фоновая задача detection. Сама управляет своей сессией и httpx-клиентом."""
    started = datetime.now(timezone.utc)
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    counters = {"new": 0, "updated": 0, "unchanged": 0, "errors": 0, "total_slugs": 0}

    async with SessionFactory() as session:
        run = await session.get(SourceScrapeRun, run_id)
        if run is None:
            logger.error("source run %d not found", run_id)
            return
        run.status = "running"
        run.started_at = started
        await session.commit()

        buf = RunLogBuffer(session, run_id=run_id)
        try:
            buf.log(f"Старт detection для провайдера {scraper.provider!r}.")
            buf.set_totals(counters)
            await buf.flush()

            async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
            ) as client:
                slugs, slug_to_source = await scraper.collect_slugs(client, params)
                counters["total_slugs"] = len(slugs)
                buf.set_totals(counters)
                buf.log(f"Найдено {len(slugs)} slug'ов; начинаю обход карточек.")
                await buf.flush()

                # Снимок существующих hash'ей и payload'ов одной выборкой —
                # чтобы не дёргать БД на каждый slug.
                existing = await _load_existing_hashes(
                    session, scraper.staging_table(), slugs,
                )

                for i, slug in enumerate(slugs):
                    try:
                        item = await scraper.fetch_one(client, slug)
                    except httpx.HTTPError as e:
                        counters["errors"] += 1
                        buf.log(f"[{i + 1}/{len(slugs)}] {slug} — ошибка: {e}")
                        # Вежливая пауза даже на ошибке.
                        await asyncio.sleep(
                            RATE_LIMIT_SEC + random.uniform(0, RATE_LIMIT_JITTER_SEC),
                        )
                        await buf.maybe_flush()
                        continue

                    prev_hash, prev_payload = existing.get(slug, (None, None))
                    # Если запись существует, но без content_hash — backfill'им
                    # на лету. Это нужно один раз; следующий прогон уже найдёт
                    # хеш в БД.
                    if prev_payload is not None and prev_hash is None:
                        prev_hash = await _backfill_existing_hash(
                            session, scraper.staging_table(), slug, prev_payload,
                        )

                    change_type, field_diffs = _classify(
                        prev_hash, prev_payload, item.content_hash, item.payload,
                    )
                    counters[change_type] = counters.get(change_type, 0) + 1

                    session.add(
                        SourceScrapeItem(
                            run_id=run_id,
                            slug=slug,
                            payload=item.payload,
                            raw_html=item.raw_html,
                            content_hash=item.content_hash,
                            prev_hash=prev_hash,
                            change_type=change_type,
                            field_diffs=field_diffs,
                        ),
                    )

                    # commit пакетами — не на каждом slug'е, чтобы не плодить
                    # WAL. Совмещаем с flush'ем log_lines/totals.
                    if (i + 1) % FLUSH_EVERY_N == 0:
                        await session.commit()

                    title = item.payload.get("title_ru") or item.payload.get("title_en") or slug
                    buf.log(
                        f"[{i + 1}/{len(slugs)}] {slug} — {change_type} ({title})",
                    )
                    buf.set_totals(counters)
                    await buf.maybe_flush()

                    await asyncio.sleep(
                        RATE_LIMIT_SEC + random.uniform(0, RATE_LIMIT_JITTER_SEC),
                    )

                # Финальный commit оставшихся items (если N не делится на FLUSH_EVERY_N).
                await session.commit()

            buf.log(
                "Detection завершён: "
                f"new={counters['new']} updated={counters['updated']} "
                f"unchanged={counters['unchanged']} errors={counters['errors']}",
            )
            buf.set_totals(counters)
            await buf.flush()

            await session.execute(
                update(SourceScrapeRun)
                .where(SourceScrapeRun.id == run_id)
                .values(
                    status="ready",
                    finished_at=datetime.now(timezone.utc),
                ),
            )
            await session.commit()

        except Exception as e:  # noqa: BLE001 — фоновая задача, ловим всё
            logger.exception("source run %d failed", run_id)
            buf.log(f"Прогон упал: {e!r}")
            await buf.flush()
            await session.execute(
                update(SourceScrapeRun)
                .where(SourceScrapeRun.id == run_id)
                .values(
                    status="failed",
                    error_message=str(e),
                    finished_at=datetime.now(timezone.utc),
                ),
            )
            await session.commit()


# ─── Apply / Discard ──────────────────────────────────────────────────────────


class RunNotReady(RuntimeError):
    """Попытка apply/discard над run'ом, который не в статусе `ready`."""


async def apply_run(
    session: AsyncSession,
    run_id: int,
    *,
    item_ids: list[int] | None = None,
    change_types: list[str] | None = None,
    performed_by: str | None = None,
) -> dict[str, Any]:
    """Применить выбранные items к провайдер-staging.

    `item_ids` (явный список) и `change_types` (`['new', 'updated']`)
    взаимодействуют как AND: оператор может сказать «только new из вот этих
    конкретных items».

    Идемпотентен: повторный apply для тех же items — ON CONFLICT DO UPDATE
    в нижележащем `apply_payload`.
    """
    run = await session.get(SourceScrapeRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    if run.status != "ready":
        raise RunNotReady(
            f"run {run_id} в статусе {run.status!r}; apply допустим только из 'ready'",
        )

    from catalog.sources.base import get_scraper

    scraper = get_scraper(run.provider)

    stmt = select(SourceScrapeItem).where(SourceScrapeItem.run_id == run_id)
    if item_ids:
        stmt = stmt.where(SourceScrapeItem.id.in_(item_ids))
    if change_types:
        stmt = stmt.where(SourceScrapeItem.change_type.in_(change_types))
    items = (await session.execute(stmt)).scalars().all()

    applied = 0
    for item in items:
        # source_listing хранится в payload (мы кладём его в момент detection).
        source_listing = (item.payload or {}).get("source_listing")
        await scraper.apply_payload(
            session,
            slug=item.slug,
            payload=item.payload,
            raw_html=item.raw_html,
            content_hash=item.content_hash,
            source_listing=source_listing,
        )
        applied += 1

    totals = dict(run.totals or {})
    totals["applied"] = (totals.get("applied") or 0) + applied
    await session.execute(
        update(SourceScrapeRun)
        .where(SourceScrapeRun.id == run_id)
        .values(
            status="applied",
            totals=totals,
            performed_by=performed_by or run.performed_by,
        ),
    )
    await session.commit()

    return {"run_id": run_id, "applied": applied}


async def discard_run(
    session: AsyncSession,
    run_id: int,
    *,
    performed_by: str | None = None,
) -> dict[str, Any]:
    """Отбросить run без переноса в staging. Items остаются для аналитики."""
    run = await session.get(SourceScrapeRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    if run.status != "ready":
        raise RunNotReady(
            f"run {run_id} в статусе {run.status!r}; discard допустим только из 'ready'",
        )
    await session.execute(
        update(SourceScrapeRun)
        .where(SourceScrapeRun.id == run_id)
        .values(status="discarded", performed_by=performed_by or run.performed_by),
    )
    await session.commit()
    return {"run_id": run_id, "status": "discarded"}
