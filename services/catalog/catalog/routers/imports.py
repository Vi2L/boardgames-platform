"""Импортёры: BGG (Tesera будет на этапе 4).

POST /import/bgg запускает background-task через asyncio.create_task — для одной
игры это занимает 1-3 секунды (BGG XML API + парсинг + upsert), синхронный режим
тоже доступен через ?wait=true для тестов.

GET /import/jobs/{id} — поллинг статуса.
"""
from __future__ import annotations

import asyncio
import csv as csv_mod
import io
import logging
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from catalog.auth import require_scope
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.db import get_engine, get_session
from catalog.importers._log_buffer import LogBuffer
from catalog.importers.bgg import (
    BggGame,
    fetch_bgg_thing,
    parse_bgg_xml,
    slug_from_title,
)
from catalog.importers.tesera import (
    TeseraGame,
    fetch_tesera_thing,
    parse_tesera_json,
)
from catalog.importers.bgg_hotness import run_hotness_import_job
from catalog.importers.bgg_geeklist import run_geeklist_import_job
from catalog.importers.dicefest import (
    _run_dicefest_import_job,
    _run_dicefest_reparse_job,
)
from catalog.models import Game, GameAlias, GameBgg, ImportJob
from catalog.parsers.bgg import BggClient
from catalog.parsers.bgg.service import enrich_batch
from catalog.schemas import (
    BggBatchImportRequest,
    BggImportRequest,
    DicefestImportRequest,
    GeeklistImportRequest,
    ImportJobOut,
    MiniBatchImportRequest,
    TeseraImportRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/import", tags=["import"])


async def _upsert_game_from_bgg(
    session: AsyncSession, bgg: BggGame
) -> int:
    """Идемпотентный upsert по bgg_id.

    Возвращает game_id. Алиасы апсертятся отдельно (по uq_alias_per_game).
    """
    slug = slug_from_title(bgg.title, bgg.bgg_id)

    # ON CONFLICT (bgg_id) DO UPDATE — обновляем основные поля, сохраняем
    # ручные правки в meta через jsonb merge нельзя без сложных выражений,
    # так что meta перезаписываем. Этап 7+ может усложнить.
    stmt = pg_insert(Game.__table__).values(
        slug=slug,
        title=bgg.title,
        year=bgg.year,
        designers=bgg.designers or None,
        publishers=bgg.publishers or None,
        players_min=bgg.players_min,
        players_max=bgg.players_max,
        age_min=bgg.age_min,
        playtime_min=bgg.playtime_min,
        playtime_max=bgg.playtime_max,
        bgg_id=bgg.bgg_id,
        cover_url=bgg.cover_url,
        description=bgg.description,
        meta=bgg.to_meta(),
        source="bgg",
        status="published",
    ).on_conflict_do_update(
        index_elements=["bgg_id"],
        set_={
            "title": bgg.title,
            "year": bgg.year,
            "designers": bgg.designers or None,
            "publishers": bgg.publishers or None,
            "players_min": bgg.players_min,
            "players_max": bgg.players_max,
            "age_min": bgg.age_min,
            "playtime_min": bgg.playtime_min,
            "playtime_max": bgg.playtime_max,
            "cover_url": bgg.cover_url,
            "description": bgg.description,
            "meta": bgg.to_meta(),
            "updated_at": _utcnow(),
        },
    ).returning(Game.id)
    game_id = (await session.execute(stmt)).scalar_one()

    # Альтернативные имена → game_aliases. ON CONFLICT DO NOTHING на uq_alias_per_game.
    for alias in bgg.aliases:
        await session.execute(
            pg_insert(GameAlias.__table__)
            .values(game_id=game_id, alias=alias, source="bgg")
            .on_conflict_do_nothing(constraint="uq_alias_per_game")
        )
    return game_id


async def _run_bgg_import_job(
    job_id: int, bgg_ids: list[int]
) -> None:
    """Background-таск: для каждого id — fetch BGG → parse → upsert.

    Ошибка по одному id не валит всю задачу — пишется в result.errors.
    Использует свой session_factory (не FastAPI dep), потому что вне HTTP-контекста.
    """
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as session:
        job = (await session.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
        job.status = "running"
        job.started_at = _utcnow()
        await session.commit()

    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for bgg_id in bgg_ids:
            try:
                xml = await fetch_bgg_thing(bgg_id, client=client)
                bgg = parse_bgg_xml(xml)
                if bgg is None:
                    errors.append({"bgg_id": bgg_id, "error": "not found"})
                    continue
                async with SessionFactory() as session:
                    gid = await _upsert_game_from_bgg(session, bgg)
                    await session.commit()
                imported.append({"bgg_id": bgg_id, "game_id": gid, "title": bgg.title})
            except Exception as exc:  # noqa: BLE001
                logger.exception("BGG import failed for %s", bgg_id)
                errors.append({"bgg_id": bgg_id, "error": str(exc)})

    async with SessionFactory() as session:
        job = (await session.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
        job.status = "failed" if errors and not imported else "done"
        job.finished_at = _utcnow()
        job.result = {"imported": imported, "errors": errors}
        if errors and not imported:
            job.error = errors[0]["error"]
        await session.commit()


async def _upsert_game_from_tesera(
    session: AsyncSession, tg: TeseraGame
) -> int:
    """Идемпотентный upsert по tesera_id.

    Если игра уже существует с таким же tesera_id — обновляем; иначе создаём.
    Если игра уже была импортирована из BGG (тот же объект, но без tesera_id) —
    Tesera создаст дубль; merge между источниками — задача этапа 5+ (matcher).
    """
    # slug должен быть уникальным; используем alias Tesera + tesera_id как фоллбэк.
    base_slug = tg.alias if tg.alias else f"tesera-{tg.tesera_id}"
    # alias уже похож на slug, но защитимся от верхнего регистра.
    slug = base_slug.lower().replace("_", "-")

    stmt = pg_insert(Game.__table__).values(
        slug=slug,
        title=tg.title,
        year=tg.year,
        players_min=tg.players_min,
        players_max=tg.players_max,
        age_min=tg.age_min,
        playtime_min=tg.playtime_min,
        playtime_max=tg.playtime_max,
        tesera_id=tg.tesera_id,
        cover_url=tg.cover_url,
        description=tg.description,
        meta=tg.to_meta(),
        source="tesera",
        status="published",
    ).on_conflict_do_update(
        index_elements=["tesera_id"],
        set_={
            "title": tg.title,
            "year": tg.year,
            "players_min": tg.players_min,
            "players_max": tg.players_max,
            "age_min": tg.age_min,
            "playtime_min": tg.playtime_min,
            "playtime_max": tg.playtime_max,
            "cover_url": tg.cover_url,
            "description": tg.description,
            "meta": tg.to_meta(),
            "updated_at": _utcnow(),
        },
    ).returning(Game.id)
    game_id = (await session.execute(stmt)).scalar_one()

    for alias in tg.aliases:
        await session.execute(
            pg_insert(GameAlias.__table__)
            .values(game_id=game_id, alias=alias, source="tesera")
            .on_conflict_do_nothing(constraint="uq_alias_per_game")
        )
    return game_id


async def _run_tesera_import_job(
    job_id: int, items: list[str | int]
) -> None:
    """Background-таск для batched-импорта из Tesera."""
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as session:
        job = (await session.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
        job.status = "running"
        job.started_at = _utcnow()
        await session.commit()

    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for item in items:
            try:
                payload = await fetch_tesera_thing(item, client=client)
                tg = parse_tesera_json(payload)
                if tg is None:
                    errors.append({"item": item, "error": "not found"})
                    continue
                async with SessionFactory() as session:
                    gid = await _upsert_game_from_tesera(session, tg)
                    await session.commit()
                imported.append(
                    {"item": item, "game_id": gid, "title": tg.title, "tesera_id": tg.tesera_id}
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Tesera import failed for %s", item)
                errors.append({"item": item, "error": str(exc)})

    async with SessionFactory() as session:
        job = (await session.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
        job.status = "failed" if errors and not imported else "done"
        job.finished_at = _utcnow()
        job.result = {"imported": imported, "errors": errors}
        if errors and not imported:
            job.error = errors[0]["error"]
        await session.commit()


@router.post(
    "/bgg",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_bgg(
    payload: BggImportRequest,
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    ids = payload.ids or ([payload.bgg_id] if payload.bgg_id else [])
    if not ids:
        raise HTTPException(status_code=400, detail="bgg_id или ids обязателен")

    job = ImportJob(type="bgg", payload={"ids": ids}, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await _run_bgg_import_job(job.id, ids)
        await session.refresh(job)
    else:
        # Fire-and-forget. Сама задача создаёт свою сессию — текущая dep-сессия
        # будет закрыта по завершении HTTP-запроса.
        asyncio.create_task(_run_bgg_import_job(job.id, ids))

    return ImportJobOut.model_validate(job)


# ─── BGG batch enrich (этап 2-3) ─────────────────────────────────────────────


def get_batch_bgg_client() -> BggClient:
    """FastAPI dependency для batch-endpoint'а. Тесты переопределяют через
    `app.dependency_overrides` для подмены MockTransport.

    Отдельная функция, а не общая с `routers/parsers.py:get_bgg_client`,
    потому что тесты часто хотят разный mock'инг для search vs batch
    (в search возвращается /search-XML, в batch — /thing-XML).

    from_settings — Bearer token обязателен для BGG XML API v2 (с июля 2025).
    Тесты переопределяют через `app.dependency_overrides[get_bgg_batch_client]`."""
    return BggClient.from_settings()


async def _run_bgg_batch_job(
    job_id: int,
    payload: BggBatchImportRequest,
    *,
    client: BggClient | None = None,
) -> None:
    """Background-таск для batch BGG XML enrich.

    Управляет своей сессией (фоновая задача — своя транзакция, не делим
    с HTTP-handler'ом). Прогресс пишет через `LogBuffer` каждые 100 строк
    или 2 сек — на 1000+ играх это даёт ~10-30 UPDATE'ов вместо 3000.
    """
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as session:
        # 1. Помечаем job как running.
        job = (
            await session.execute(select(ImportJob).where(ImportJob.id == job_id))
        ).scalar_one()
        job.status = "running"
        job.started_at = _utcnow()
        await session.commit()

        # LogBuffer держит свою же session — flush'ит UPDATE'ы туда.
        # flush_every_n=100 — для batch enrich (1000+ игр) хватит, чтобы
        # poll-UI видел движение каждые ~100 итераций / 2 секунды.
        buf = LogBuffer(session, job_id=job_id, flush_every_n=100, flush_every_s=2.0)

        rank_le = None if payload.all_ranked else payload.rank_le
        scope = "all-ranked" if payload.all_ranked else f"rank≤{rank_le}"
        buf.set_progress(phase="starting", current=0, total=0)
        buf.log(
            f"BGG batch enrich: scope={scope} batch_size={payload.batch_size} "
            f"skip_recent_days={payload.skip_recent_days} dry_run={payload.dry_run}"
        )
        await buf.flush()

        own_client = client is None
        if client is None:
            # from_settings — Bearer token обязателен (BGG XML API v2 с июля 2025).
            client = BggClient.from_settings()

        async def progress_cb(i: int, total: int, bgg) -> None:
            # Лог per-item только для не-skipped, чтобы не засорять ring-buffer.
            if bgg is not None:
                buf.log(f"[{i}/{total}] bgg_id={bgg.bgg_id} — {bgg.title}")
            buf.set_progress(
                phase="enriching",
                current=i,
                total=total,
                current_title=bgg.title if bgg is not None else None,
            )
            await buf.maybe_flush()

        try:
            if own_client:
                await client.__aenter__()
            stats = await enrich_batch(
                rank_le=rank_le,
                batch_size=payload.batch_size,
                skip_recent_days=payload.skip_recent_days,
                limit=payload.limit,
                dry_run=payload.dry_run,
                rate_limit_sec=payload.rate_limit_sec,
                progress_cb=progress_cb,
                session_factory=SessionFactory,
                client=client,
            )

            buf.log(
                f"Done: enriched={stats.enriched} skipped={stats.skipped} "
                f"failed={stats.failed}"
            )
            buf.set_progress(phase="done")
            await buf.flush()

            # Final status: failed только если совсем ничего не обогатили
            # и при этом были ошибки. Если хоть одна игра обработана — done
            # (частичный успех — нормально для long-running batch'а).
            final_status = (
                "failed" if stats.failed > 0 and stats.enriched == 0 else "done"
            )
            await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id)
                .values(
                    status=final_status,
                    finished_at=_utcnow(),
                    result=stats.to_dict(),
                    error=stats.errors[0]["error"] if final_status == "failed" and stats.errors else None,
                )
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — фоновая задача
            logger.exception("BGG batch job %d failed", job_id)
            buf.log(f"FAILED: {exc!r}")
            await buf.flush()
            await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id)
                .values(
                    status="failed",
                    finished_at=_utcnow(),
                    error=str(exc),
                )
            )
            await session.commit()
        finally:
            if own_client:
                await client.__aexit__(None, None, None)


@router.post(
    "/bgg/batch",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_bgg_batch(
    payload: BggBatchImportRequest,
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    session: AsyncSession = Depends(get_session),
    bgg: BggClient = Depends(get_batch_bgg_client),
) -> ImportJobOut:
    """Запустить batch-обогащение catalog'а через BGG XML API.

    Один из `rank_le` / `all_ranked` обязателен. Прогресс пишется в
    `ImportJob.progress` и `log_lines`, читать через `GET /import/jobs/{id}`.

    `wait=true` — синхронный режим для тестов. В продакшене — fire-and-forget.
    """
    if payload.rank_le is None and not payload.all_ranked:
        raise HTTPException(
            status_code=400,
            detail="rank_le или all_ranked обязателен",
        )
    if payload.rank_le is not None and payload.all_ranked:
        raise HTTPException(
            status_code=400,
            detail="rank_le и all_ranked взаимоисключают друг друга",
        )

    job = ImportJob(
        type="bgg-batch",
        payload=payload.model_dump(exclude_none=True),
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await _run_bgg_batch_job(job.id, payload, client=bgg)
        await session.refresh(job)
    else:
        asyncio.create_task(_run_bgg_batch_job(job.id, payload, client=bgg))

    return ImportJobOut.model_validate(job)


@router.post(
    "/tesera",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_tesera(
    payload: TeseraImportRequest,
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    items: list[str | int] = list(payload.items or [])
    if payload.alias:
        items.append(payload.alias)
    if payload.tesera_id:
        items.append(payload.tesera_id)
    if not items:
        raise HTTPException(
            status_code=400, detail="alias, tesera_id или items обязателен"
        )

    job = ImportJob(type="tesera", payload={"items": items}, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await _run_tesera_import_job(job.id, items)
        await session.refresh(job)
    else:
        asyncio.create_task(_run_tesera_import_job(job.id, items))

    return ImportJobOut.model_validate(job)


@router.post(
    "/dicefest",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_dicefest(
    payload: DicefestImportRequest,
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    """Парсит каталог dicefest.ru → пишет в staging-таблицу dicefest_raw_games.

    Двухстадийная схема: эта операция НЕ трогает основные games/game_aliases.
    Перенос в canonical БД — отдельный процесс через UI промоушена (PR-2).

    payload:
      - max_items=N — для пробного прогона (только первые N slug'ов)
      - only_year=2026 — ограничить обход одним годом

    Прогресс/логи доступны через GET /import/jobs/{id} (poll каждые 1.5с).
    """
    job = ImportJob(
        type="dicefest",
        payload=payload.model_dump(exclude_none=True),
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await _run_dicefest_import_job(job.id, job.payload)
        await session.refresh(job)
    else:
        asyncio.create_task(_run_dicefest_import_job(job.id, job.payload))

    return ImportJobOut.model_validate(job)


@router.post(
    "/dicefest/reparse",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_dicefest_reparse(
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    """Re-parse уже скачанных карточек dicefest БЕЗ повторных HTTP-запросов.

    Используется после изменения парсера (например, добавили новые поля
    или поправили селекторы) — обновляет извлекаемые поля по сохранённому
    raw_html. Не трогает status/promoted_*/raw_html/fetched_at.
    """
    job = ImportJob(
        type="dicefest-reparse",
        payload={},
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await _run_dicefest_reparse_job(job.id, {})
        await session.refresh(job)
    else:
        asyncio.create_task(_run_dicefest_reparse_job(job.id, {}))

    return ImportJobOut.model_validate(job)


@router.post(
    "/bgg/hotness",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_bgg_hotness(
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    """Ручной запуск BGG Hotness sync.

    Fetches /hot?type=boardgame → upsert bgg_hotness snapshot → auto-import
    игр, отсутствующих в каталоге. Идемпотентен: повторный вызов в тот же
    день не создаёт дублей в bgg_hotness.

    Прогресс доступен через GET /import/jobs/{id}.
    """
    job = ImportJob(type="bgg-hotness", payload={}, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await run_hotness_import_job(job.id)
        await session.refresh(job)
    else:
        asyncio.create_task(run_hotness_import_job(job.id))

    return ImportJobOut.model_validate(job)


@router.post(
    "/bgg/geeklist",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_bgg_geeklist(
    payload: GeeklistImportRequest,
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    trigger: str = Query("manual", description="manual | scheduled | api"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    """Ручной запуск GeekList snapshot.

    Fetch /xmlapi2/geeklist/{id} → upsert в bgg_geeklists → auto-import bgg_id'ов
    отсутствующих в каталоге. Идемпотентен в рамках дня (UNIQUE по
    (geeklist_id, snapshot_date)).

    `trigger` пишется в payload — для фильтрации в `GET /import/jobs?trigger=`.
    """
    job_payload = {
        "geeklist_id": payload.geeklist_id,
        "auto_import": payload.auto_import,
        "trigger": trigger,
    }
    job = ImportJob(type="bgg-geeklist", payload=job_payload, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await run_geeklist_import_job(job.id, payload.geeklist_id)
        await session.refresh(job)
    else:
        asyncio.create_task(run_geeklist_import_job(job.id, payload.geeklist_id))

    return ImportJobOut.model_validate(job)


@router.post(
    "/bgg/mini-batch",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_bgg_mini_batch(
    payload: MiniBatchImportRequest,
    wait: bool = Query(False, description="дождаться завершения (для тестов)"),
    trigger: str = Query("manual", description="manual | scheduled | api"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    """Ежедневный «catch-up» enrichment для хвоста rank-таблицы.

    Тонкая обёртка над batch enrich: rank_le=None (все ranked), увеличенный
    skip_recent_days (не пересекаемся с weekly top-sync), мягкий rate_limit_sec.
    На полной выборке ~30K ranked-игр и `batch_size=500` цикл обновления = ~60 дней.

    `type='bgg-mini-batch'` — отличается от 'bgg-batch' для фильтрации в истории.
    Внутри использует тот же `_run_bgg_batch_job`.
    """
    # Транслируем MiniBatchImportRequest → BggBatchImportRequest.
    # `all_ranked=True` обязательно когда rank_le=None (валидация в роутере /bgg/batch
    # этого требовала); здесь делаем явно для совместимости с _run_bgg_batch_job.
    batch_req = BggBatchImportRequest(
        all_ranked=True,
        batch_size=20,  # max 20 — лимит BGG /thing
        skip_recent_days=payload.skip_recent_days,
        limit=payload.batch_size,  # ← главный параметр: сколько игр за прогон
        dry_run=payload.dry_run,
        rate_limit_sec=payload.rate_limit_sec,
    )

    job_payload = {
        "trigger": trigger,
        "batch_size": payload.batch_size,
        "skip_recent_days": payload.skip_recent_days,
        "rate_limit_sec": payload.rate_limit_sec,
        "dry_run": payload.dry_run,
    }
    job = ImportJob(type="bgg-mini-batch", payload=job_payload, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if wait:
        await _run_bgg_batch_job(job.id, batch_req)
        await session.refresh(job)
    else:
        asyncio.create_task(_run_bgg_batch_job(job.id, batch_req))

    return ImportJobOut.model_validate(job)


async def _run_bgg_ranks_job(
    job_id: int,
    csv_bytes: bytes,
    top_n: int | None,
    dry_run: bool,
) -> None:
    """Background-таск для CSV-seed из BGG ranks выгрузки.

    Принимает сырые байты CSV (уже загруженные в память HTTP-хэндлером),
    парсит через csv.DictReader + io.StringIO, фильтрует по rank ≤ top_n,
    затем пакетно upsert'ит в games + game_bgg — та же логика, что в
    catalog.scripts.import_bgg_ranks, но адаптированная под ImportJob.
    """
    # split_row и slugify — pure-функции из CLI-скрипта; импортируем напрямую,
    # чтобы не дублировать CSV-парсинг в двух местах.
    from catalog.scripts.import_bgg_ranks import split_row  # noqa: PLC0415

    BATCH = 500  # меньше чем в CLI, чтобы прогресс обновлялся чаще

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as session:
        job = (
            await session.execute(select(ImportJob).where(ImportJob.id == job_id))
        ).scalar_one()
        job.status = "running"
        job.started_at = _utcnow()
        await session.commit()

        scope_str = f"top-{top_n}" if top_n else "all-ranked"
        buf = LogBuffer(session, job_id=job_id, flush_every_n=50, flush_every_s=2.0)
        buf.set_progress(phase="starting", current=0, total=0)
        buf.log(f"BGG ranks import: scope={scope_str} dry_run={dry_run}")
        await buf.flush()

        try:
            text = csv_bytes.decode("utf-8")
            reader = csv_mod.DictReader(io.StringIO(text))

            # Pre-scan: collect valid rows filtered by top_n, to know total.
            # Memory-acceptable: ~160K rows × ~200 bytes ≈ 32 MB worst-case.
            valid_rows: list[tuple[dict, dict]] = []
            for row in reader:
                split = split_row(row)
                if split is None:
                    continue
                games_row, bgg_row = split
                rank = bgg_row.get("rank")
                if top_n is not None and (rank is None or rank > top_n):
                    continue
                valid_rows.append((games_row, bgg_row))

            total = len(valid_rows)
            buf.set_progress(phase="upserting", current=0, total=total)
            buf.log(f"Filtered: {total} rows (top_n={top_n})")
            await buf.flush()

            enriched = 0
            if not dry_run:
                for batch_start in range(0, total, BATCH):
                    chunk = valid_rows[batch_start : batch_start + BATCH]
                    games_chunk = [r[0] for r in chunk]
                    bgg_chunk_by_id = {r[1]["bgg_id"]: r[1] for r in chunk}

                    async with SessionFactory() as upsert_session:
                        # 1. Upsert games, resolve bgg_id → game_id.
                        games_stmt = (
                            pg_insert(Game.__table__)
                            .values(games_chunk)
                            .on_conflict_do_update(
                                index_elements=["bgg_id"],
                                set_={
                                    "title": pg_insert(Game.__table__).excluded.title,
                                    "year": pg_insert(Game.__table__).excluded.year,
                                    "source": pg_insert(Game.__table__).excluded.source,
                                },
                            )
                            .returning(Game.__table__.c.id, Game.__table__.c.bgg_id)
                        )
                        rows_out = (await upsert_session.execute(games_stmt)).all()
                        bgg_id_to_game_id = {r.bgg_id: r.id for r in rows_out}

                        # 2. Upsert game_bgg with resolved game_id.
                        bgg_records = [
                            {"game_id": bgg_id_to_game_id[bgg_id], **payload}
                            for bgg_id, payload in bgg_chunk_by_id.items()
                            if bgg_id in bgg_id_to_game_id
                        ]
                        if bgg_records:
                            bgg_stmt = (
                                pg_insert(GameBgg.__table__)
                                .values(bgg_records)
                                .on_conflict_do_update(
                                    index_elements=["game_id"],
                                    set_={
                                        "rank": pg_insert(GameBgg.__table__).excluded.rank,
                                        "bayes_average": pg_insert(GameBgg.__table__).excluded.bayes_average,
                                        "average": pg_insert(GameBgg.__table__).excluded.average,
                                        "users_rated": pg_insert(GameBgg.__table__).excluded.users_rated,
                                        "is_expansion": pg_insert(GameBgg.__table__).excluded.is_expansion,
                                        "subtype_ranks": pg_insert(GameBgg.__table__).excluded.subtype_ranks,
                                        "raw": pg_insert(GameBgg.__table__).excluded.raw,
                                        "source": pg_insert(GameBgg.__table__).excluded.source,
                                        "fetched_at": pg_insert(GameBgg.__table__).excluded.fetched_at,
                                    },
                                )
                            )
                            await upsert_session.execute(bgg_stmt)

                        await upsert_session.commit()

                    enriched += len(chunk)
                    buf.set_progress(phase="upserting", current=enriched, total=total)
                    if enriched % 1000 == 0 or enriched == total:
                        buf.log(f"  {enriched}/{total} upserted")
                    await buf.maybe_flush()
            else:
                enriched = total  # dry-run: report что было бы импортировано

            buf.log(f"Done: processed={enriched} dry_run={dry_run}")
            buf.set_progress(phase="done", current=enriched, total=total)
            await buf.flush()

            await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id)
                .values(
                    status="done",
                    finished_at=_utcnow(),
                    result={"enriched": enriched, "skipped": 0, "failed": 0, "dry_run": dry_run},
                )
            )
            await session.commit()

        except Exception as exc:  # noqa: BLE001
            logger.exception("BGG ranks job %d failed", job_id)
            buf.log(f"FAILED: {exc!r}")
            await buf.flush()
            await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id)
                .values(status="failed", finished_at=_utcnow(), error=str(exc))
            )
            await session.commit()


@router.post(
    "/bgg/ranks",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def import_bgg_ranks(
    csv_file: UploadFile = File(..., description="BGG ranks CSV (скачать с boardgamegeek.com/data_dumps/bg_ranks)"),
    top_n: int | None = Form(None, description="Импортировать только top-N игр по rank (None = все)"),
    dry_run: bool = Form(False, description="Если True — только подсчитать, без записи в БД"),
    session: AsyncSession = Depends(get_session),
) -> ImportJobOut:
    """Seed каталога из BGG ranks CSV (boardgamegeek.com/data_dumps/bg_ranks).

    Создаёт minimal game records (title, year, bgg_id, rank) без полных
    XML-данных. После seed — запустить /import/bgg/batch для обогащения
    через BGG XML API.

    Принимает multipart/form-data: поле `csv_file` + опционально `top_n`
    и `dry_run`. Возвращает ImportJob — polling через GET /import/jobs/{id}.
    """
    csv_bytes = await csv_file.read()
    job = ImportJob(
        type="bgg-ranks",
        payload={"top_n": top_n, "dry_run": dry_run, "filename": csv_file.filename},
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    asyncio.create_task(_run_bgg_ranks_job(job.id, csv_bytes, top_n, dry_run))

    return ImportJobOut.model_validate(job)


@router.get(
    "/jobs",
    response_model=list[ImportJobOut],
    dependencies=[Depends(require_scope("read"))],
)
async def list_jobs(
    type: str | None = Query(default=None, description="фильтр по type (e.g. bgg-batch)"),
    status: str | None = Query(default=None, description="pending | running | done | failed"),
    trigger: str | None = Query(
        default=None,
        description="manual | scheduled | api — читается из payload->>'trigger'",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ImportJobOut]:
    """Листинг ImportJob'ов с фильтрами для UI BGG Sync (история запусков).

    `trigger` хранится в payload JSONB — фильтр через `payload->>'trigger' = ?`.
    Старые job'ы без этого поля попадают в результат только при `trigger=None`.
    Сортировка по created_at DESC (свежие сверху).
    """
    stmt = select(ImportJob)
    if type is not None:
        stmt = stmt.where(ImportJob.type == type)
    if status is not None:
        stmt = stmt.where(ImportJob.status == status)
    if trigger is not None:
        # JSONB ->> возвращает text; сравниваем по строке.
        stmt = stmt.where(ImportJob.payload["trigger"].astext == trigger)
    stmt = stmt.order_by(ImportJob.created_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).scalars().all()
    return [ImportJobOut.model_validate(r) for r in rows]


@router.get(
    "/jobs/{job_id}",
    response_model=ImportJobOut,
    dependencies=[Depends(require_scope("read"))],
)
async def get_job(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> ImportJobOut:
    job = (await session.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return ImportJobOut.model_validate(job)
