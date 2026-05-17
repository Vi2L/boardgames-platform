"""Webhook от parsers: POST /ingest/offers.

Контракт стабильный (см. catalog/CLAUDE.md и плановый webhook-формат). На каждый
батч продуктов:

1. Upsert offer (по uniq store_slug+external_id), обновляем last_price/last_seen.
2. Записываем точку в offer_prices (если price пришёл).
3. Если offer ещё не сматчен (match_status in ('unmatched', NULL)) ИЛИ был
   matched автоматически — пересматчиваем (каталог мог обновиться).
   manual/rejected трогать НЕ нужно — это решение оператора.
4. При auto-match добавляем title_raw как alias (с source='auto-match').

Idempotent: повторный ingest того же батча не плодит дублей и не двигает
manual-связь.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bg_shared.ingest import IngestRequest

from catalog.auth import require_scope
from catalog.db import get_engine, get_session
from catalog.matching.v2 import MatchAction, MatchContext, match_sync, normalize_title
from catalog.matching.v2.auditor import log_change
from catalog.matching.v2.decisions import save_decision
from catalog.matching.v2.queue_repo import enqueue
from catalog.models import GameAlias, GameBgg, Offer, OfferPrice
from catalog.schemas import (
    IngestResult,
    IngestResultItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

# Категории, которые принимаем в catalog (whitelist defence-in-depth).
# Парсеры обязаны заявлять `category` начиная с 2026-05-18 — но `None`
# принимается для обратной совместимости (старый publisher без поля).
# Если payload приходит с категорией вне whitelist'а — оффер дропается,
# в БД не пишется, матчинг не запускается. Это защита от ситуации
# «парсер сломался и начал слать книги».
_ALLOWED_CATEGORIES: frozenset[str | None] = frozenset({
    "boardgames",
    "expansion",
    "accessory",
    None,  # legacy clients
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _enrich_one_background(bgg_id: int) -> None:
    """Fire-and-forget обогащение одной игры из BGG.

    Создаёт свою сессию (не делит транзакцию с HTTP-handler'ом).
    Любая ошибка логируется и проглатывается — не должна аффектить ingest-ответ.
    При следующем ingest этой же игры (если fetched_at всё ещё старый) задача
    запустится снова.
    """
    from catalog.parsers.bgg.client import BggClient
    from catalog.parsers.bgg.service import enrich_one

    try:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with BggClient.from_settings() as client:
            async with session_factory() as session:
                bgg = await enrich_one(bgg_id, session, client=client)
                if bgg is not None:
                    await session.commit()
                    logger.info("ingest staleness: обновлён bgg_id=%d (%s)", bgg_id, bgg.title)
                else:
                    logger.warning("ingest staleness: bgg_id=%d не найден в BGG", bgg_id)
    except Exception:  # noqa: BLE001
        logger.exception("ingest staleness: enrich_one(bgg_id=%d) failed", bgg_id)


@router.post(
    "/offers",
    response_model=IngestResult,
    dependencies=[Depends(require_scope("ingest"))],
)
async def ingest_offers(
    payload: IngestRequest, session: AsyncSession = Depends(get_session)
) -> IngestResult:
    fetched_at = payload.fetched_at or _utcnow()
    items: list[IngestResultItem] = []
    auto_count = 0
    unmatched_count = 0
    skipped_category_count = 0

    for product in payload.products:
        # Категорийный whitelist — отсекаем «не настолки» ДО любого
        # обращения к БД и матчеру. Парсеры маркетплейсов (avito/ozon/
        # wb/onlinetrade) фильтруют на источнике; этот слой ловит баги
        # парсеров и старые DLQ-payload'ы. См. _ALLOWED_CATEGORIES.
        if product.category not in _ALLOWED_CATEGORIES:
            skipped_category_count += 1
            logger.info(
                "ingest skip non-board category: store=%s external_id=%s category=%r title=%r",
                payload.store_slug,
                product.external_id,
                product.category,
                product.title[:60],
            )
            continue

        # Нормализованные поля: берём из явного поля payload, иначе пытаемся
        # вытащить из extra (для обратной совместимости со старыми клиентами,
        # которые ещё не обновлены под новый контракт). Парсеры magasинов
        # кладут разные ключи в extra — see migration 0006 backfill.
        extra = product.extra or {}
        sku = product.sku if product.sku is not None else extra.get("sku")
        in_stock = product.in_stock
        if in_stock is None:
            # HobbyGames → 'availability', Crowd Games → 'in_stock'
            for key in ("availability", "in_stock"):
                v = extra.get(key)
                if isinstance(v, bool):
                    in_stock = v
                    break
        original_price = product.original_price
        if original_price is None:
            v = extra.get("original_price")
            if isinstance(v, int):
                original_price = v
        is_preorder = product.is_preorder

        # Upsert offer. ON CONFLICT — обновляем last_*, оставляем существующий
        # game_id и match_status (могли быть manual/rejected).
        upsert = (
            pg_insert(Offer.__table__)
            .values(
                store_slug=payload.store_slug,
                external_id=product.external_id,
                url=product.url,
                title_raw=product.title,
                image_url=product.image_url,
                last_price=product.price,
                last_seen_at=fetched_at,
                match_status="unmatched",  # будет перезаписан ниже, если auto-match
                raw_extra=product.extra,
                sku=sku,
                in_stock=in_stock,
                original_price=original_price,
                is_preorder=is_preorder,
            )
            .on_conflict_do_update(
                constraint="uq_offer_store_external",
                set_={
                    "url": product.url,
                    "title_raw": product.title,
                    "image_url": product.image_url,
                    "last_price": product.price,
                    "last_seen_at": fetched_at,
                    "raw_extra": product.extra,
                    "sku": sku,
                    "in_stock": in_stock,
                    "original_price": original_price,
                    "is_preorder": is_preorder,
                },
            )
            .returning(
                Offer.__table__.c.id,
                Offer.__table__.c.game_id,
                Offer.__table__.c.match_status,
            )
        )
        row = (await session.execute(upsert)).one()
        offer_id, current_game_id, current_status = row

        # Дефолты, чтобы все ветки имели определённые имена при финальном UPDATE.
        new_game_id = current_game_id
        new_status = current_status
        new_score: float | None = None
        new_tier: int | None = None
        result_reason: str | None = None

        # Не трогаем оператора: manual / rejected — финальные решения.
        if current_status in ("manual", "rejected"):
            pass  # дефолты выше — оставляем всё как было
        else:
            # ── Matcher v2: Tier 0 (cache) → Tier 1 (pg_trgm 0.92) ───────────
            # Если результат matched — запись в БД сразу.
            # Если needs_async — пушим в match_queue, оффер в pending_ml.
            # Если ml_disabled и !matched — обычный unmatched (как было).
            result = await match_sync(session, product.title, store_slug=payload.store_slug)
            new_score = result.score
            new_tier = result.tier
            result_reason = result.reason

            if result.matched:
                # Auto-match (T0 cache hit или T1 pg_trgm ≥ 0.92).
                new_game_id = result.game_id
                new_status = "auto"
                alias_id_created: int | None = None

                # Запоминаем title_raw как alias, чтобы следующий ingest сматчился
                # по точному alias_norm (быстрее и стабильнее, чем по triграмме).
                # Только для T1 — T0 уже на это title_norm имеет запись в decisions.
                if result.tier == 1:
                    alias_stmt = (
                        pg_insert(GameAlias.__table__)
                        .values(
                            game_id=new_game_id,
                            alias=product.title,
                            source="auto-match",
                        )
                        .on_conflict_do_nothing(constraint="uq_alias_per_game")
                        .returning(GameAlias.__table__.c.id)
                    )
                    alias_row = (await session.execute(alias_stmt)).first()
                    if alias_row is not None:
                        alias_id_created = int(alias_row[0])

                # Сохраняем решение в Tier 0 cache: следующий ingest того же
                # title_raw попадёт в T0 без T1.
                # При T0 cache hit (`result.tier in (None, 0)`) запись УЖЕ в
                # match_decisions — не пересохраняем, иначе перезаписали бы
                # `decided_at` свежим now() и бессрочный manual-decision
                # стал бы перетираться по auto_t0-семантике.
                if result.tier == 1:
                    await save_decision(
                        session,
                        title_norm=normalize_title(product.title),
                        game_id=new_game_id,
                        source="auto_t1",
                        tier=result.tier,
                        score=new_score,
                    )

                # Аудит-запись.
                await log_change(
                    session,
                    offer_id=offer_id,
                    action=result.action or MatchAction.AUTO_T1,
                    prev_game_id=current_game_id,
                    new_game_id=new_game_id,
                    prev_status=current_status,
                    new_status="auto",
                    tier=result.tier,
                    score=new_score,
                    reason=result.reason,
                    alias_created_id=alias_id_created,
                    performed_by="system",
                )

                # Staleness check: если BGG-данные для этой игры старше N дней —
                # запускаем обогащение фоном. Не блокируем ingest-ответ.
                from catalog.config import get_settings
                staleness_days = get_settings().bgg_ingest_enrich_staleness_days
                if staleness_days > 0:
                    cutoff = _utcnow() - timedelta(days=staleness_days)
                    bgg_row = (await session.execute(
                        select(GameBgg.bgg_id, GameBgg.fetched_at)
                        .where(GameBgg.game_id == new_game_id)
                    )).one_or_none()
                    if bgg_row is not None and bgg_row.fetched_at < cutoff:
                        asyncio.create_task(
                            _enrich_one_background(bgg_row.bgg_id),
                            name=f"ingest-stale-enrich-{bgg_row.bgg_id}",
                        )

            elif result.needs_async:
                # ML включён, sync не дал — пушим в очередь T2/T3.
                # Контракт `IngestResult` снаружи: match_status='unmatched' —
                # parsers'у не важно, обработается ли оффер ML или manual.
                new_game_id = None
                new_status = "unmatched"
                await enqueue(
                    session,
                    offer_id=offer_id,
                    store_slug=payload.store_slug,
                    title_raw=product.title,
                    title_norm=normalize_title(product.title),
                )
            else:
                # T0 negative cache (cached_reject) или ml_disabled.
                # Сохраняем reason для UI (operator увидит почему unmatched).
                new_game_id = result.game_id  # может быть None
                new_status = "rejected" if result.action == MatchAction.REJECT else "unmatched"

            # Один UPDATE для всех веток (DRY)
            await session.execute(
                Offer.__table__.update()
                .where(Offer.__table__.c.id == offer_id)
                .values(
                    game_id=new_game_id,
                    match_status=new_status,
                    match_score=new_score,
                    match_tier=new_tier,
                    match_reason=result_reason,
                )
            )

        # История цен — отдельная точка на каждый ingest. ON CONFLICT по
        # композитному PK (offer_id, fetched_at) — если за тот же миг уже
        # есть запись (повторный ingest), не дублируем.
        if product.price is not None:
            await session.execute(
                pg_insert(OfferPrice.__table__)
                .values(offer_id=offer_id, fetched_at=fetched_at, price=product.price)
                .on_conflict_do_nothing(index_elements=["offer_id", "fetched_at"])
            )

        if new_status == "auto":
            auto_count += 1
        elif new_status == "unmatched":
            unmatched_count += 1

        items.append(
            IngestResultItem(
                external_id=product.external_id,
                offer_id=offer_id,
                game_id=new_game_id,
                match_status=new_status,
                match_score=new_score,
            )
        )

    await session.commit()

    return IngestResult(
        store_slug=payload.store_slug,
        accepted=len(items),
        auto_matched=auto_count,
        unmatched=unmatched_count,
        skipped_category=skipped_category_count,
        items=items,
    )
