"""CAT-10: импортёр новинок года через HTML-скрейп `boardgamegeek.com/browse/boardgame`.

Зачем: BGG XML API не отдаёт фильтр `yearpublished` + сортировку `numvoters` —
именно эти два сигнала нужны для отбора «свежих и заметных» игр года. HTML
browse-страница их даёт.

Запуск:
- `run_yearly_releases_sync(year=None, max_pages=5, ...)` — ядро.
- `run_yearly_releases_import_job(import_job_id)` — обёртка для ImportJob
  (вызывается через scheduler).

Идемпотентность: для bgg_id, уже присутствующих в catalog, ничего не делаем
(их обновит обычный `bgg_top_sync`/`bgg_mini_batch`). Новые — обогащаются через
`enrich_one()` с rate-limit'ом 1 req/sec. Повторный прогон в тот же день
никаких новых записей не добавит (если за это время BGG не вошёл новый title).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.db import get_engine
from catalog.importers._log_buffer import (
    BufLogger,
    LogBuffer,
    run_import_job_skeleton,
)
from catalog.models import Game, ImportJob
from catalog.parsers.bgg.browse import BrowseParseError, parse_browse_html
from catalog.parsers.bgg.client import BggClient
from catalog.parsers.bgg.service import enrich_one

logger = logging.getLogger(__name__)


def _current_utc_year() -> int:
    """Текущий год по UTC. Вынесено в функцию для тестируемости через monkeypatch."""
    return datetime.now(timezone.utc).year


async def run_yearly_releases_sync(
    *,
    year: int | None = None,
    max_pages: int = 5,
    page_rate_limit_sec: float = 3.0,
    enrich_rate_limit_sec: float = 1.0,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    client: BggClient | None = None,
    log: logging.Logger | None = None,
) -> dict:
    """Ядро: обходит N страниц browse за `year`, обогащает отсутствующие в каталоге.

    Параметры:
    - `year`: None → текущий UTC-год. Иначе явное значение из scheduler-params.
    - `max_pages`: страниц browse (100 игр на каждой). 5 = топ-500 года.
    - `page_rate_limit_sec`: пауза между HTTP-запросами browse-страниц. BGG
      может ввести anti-bot на эти URL'ы, поэтому держим ≥3 сек.
    - `enrich_rate_limit_sec`: пауза между `enrich_one()` для новых games.
      1 сек — best practice BGG XML API.

    Возвращает: {year, pages_fetched, parsed, existing, auto_imported, errors}.
    """
    log = log or logger
    if year is None:
        year = _current_utc_year()
        log.info("yearly[%d]: year не задан в params, используем runtime UTC-год", year)

    if session_factory is None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)

    own_client = client is None
    if client is None:
        client = BggClient.from_settings()

    pages_fetched = 0
    all_rows: list = []  # list[BrowseRow] — мог бы импортнуть но избегаем cycle

    try:
        if own_client:
            await client.__aenter__()
        for page in range(1, max_pages + 1):
            try:
                html = await client.fetch_browse_year(year, page=page)
            except Exception:  # noqa: BLE001
                log.exception("yearly[%d]: fetch page %d failed", year, page)
                break  # одна страница упала — продолжать остальные нет смысла
            try:
                rows = parse_browse_html(html)
            except BrowseParseError as exc:
                log.error("yearly[%d] page %d: parse error: %s", year, page, exc)
                break
            log.info("yearly[%d]: page %d parsed (%d rows)", year, page, len(rows))
            pages_fetched += 1
            all_rows.extend(rows)
            if not rows:
                log.info("yearly[%d]: page %d пустая — финиш", year, page)
                break
            # Пауза до следующей страницы (anti-bot mitigation).
            if page < max_pages:
                await asyncio.sleep(page_rate_limit_sec)
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    # Дедуп: парсер может вернуть одну игру дважды если страница повторилась.
    seen_ids: set[int] = set()
    unique_rows = []
    for r in all_rows:
        if r.bgg_id in seen_ids:
            continue
        seen_ids.add(r.bgg_id)
        unique_rows.append(r)

    parsed = len(unique_rows)
    log.info("yearly[%d]: распарсено %d уникальных bgg_id из %d страниц",
             year, parsed, pages_fetched)

    if not unique_rows:
        return {"year": year, "pages_fetched": pages_fetched, "parsed": 0,
                "existing": 0, "auto_imported": 0, "errors": 0}

    # Resolve: какие bgg_id уже в каталоге.
    async with session_factory() as session:
        result = await session.execute(
            select(Game.bgg_id).where(Game.bgg_id.in_(seen_ids))
        )
        existing_ids = {row[0] for row in result.all()}
    missing = [r for r in unique_rows if r.bgg_id not in existing_ids]
    log.info("yearly[%d]: %d уже в каталоге, %d новых для enrich",
             year, len(existing_ids), len(missing))

    # Enrich отсутствующих с rate-limit'ом. Reuse'им client (тот же httpx connection
    # pool, тот же Bearer token) — два BggClient одновременно нарушают rate-limit
    # к BGG XML API и ломают тестируемость (mock-client не действует на enrich).
    auto_imported = 0
    errors = 0
    if missing:
        # Если у нас был own_client — он закрыт в finally выше. Откроем заново.
        # Если caller передал client — он всё ещё активен, переиспользуем.
        own_enrich_client = client is None
        enrich_client = BggClient.from_settings() if own_enrich_client else client
        try:
            if own_enrich_client:
                await enrich_client.__aenter__()
            for row in missing:
                try:
                    async with session_factory() as session:
                        bgg = await enrich_one(row.bgg_id, session, client=enrich_client)
                        if bgg is not None:
                            await session.commit()
                            auto_imported += 1
                            log.info("yearly[%d]: enrich bgg_id=%d '%s' OK",
                                     year, row.bgg_id, bgg.title)
                        else:
                            log.warning("yearly[%d]: bgg_id=%d не найден в BGG",
                                        year, row.bgg_id)
                            errors += 1
                except Exception:  # noqa: BLE001
                    log.exception("yearly[%d]: enrich bgg_id=%d failed",
                                  year, row.bgg_id)
                    errors += 1
                await asyncio.sleep(enrich_rate_limit_sec)
        finally:
            if own_enrich_client:
                await enrich_client.__aexit__(None, None, None)

    return {
        "year": year,
        "pages_fetched": pages_fetched,
        "parsed": parsed,
        "existing": len(existing_ids),
        "auto_imported": auto_imported,
        "errors": errors,
    }


async def run_yearly_releases_import_job(import_job_id: int) -> None:
    """ImportJob-обёртка для `bgg_yearly_releases` scheduler-job'а.

    Читает `year` и `max_pages` из `import_job.payload`. Если `year` отсутствует
    или None — резолвится в `_current_utc_year()`.
    """
    SessionFactory = async_sessionmaker(get_engine(), expire_on_commit=False)

    async with SessionFactory() as session:
        job = (
            await session.execute(select(ImportJob).where(ImportJob.id == import_job_id))
        ).scalar_one()
        payload = job.payload or {}
        year = payload.get("year")  # None → runtime год резолвится внутри
        max_pages = int(payload.get("max_pages", 5))

    async def body(buf: LogBuffer, buf_log: BufLogger, sf):
        return await run_yearly_releases_sync(
            year=year,
            max_pages=max_pages,
            session_factory=sf,
            log=buf_log,  # type: ignore[arg-type]
        )

    def summary(r: dict) -> str:
        return (
            f"Done: year={r['year']} pages={r['pages_fetched']} parsed={r['parsed']} "
            f"existing={r['existing']} auto_imported={r['auto_imported']} "
            f"errors={r['errors']}"
        )

    await run_import_job_skeleton(
        import_job_id,
        init_log=f"BGG yearly releases sync запущен: year={year or 'runtime UTC'} max_pages={max_pages}",
        body=body,
        session_factory=SessionFactory,
        summary_fn=summary,
        logger_inst=logger,
    )
