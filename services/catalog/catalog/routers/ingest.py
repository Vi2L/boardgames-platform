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
from catalog.matching.matcher import (
    AUTO_MATCH_THRESHOLD,
    classify,
    find_best_match,
)
from catalog.models import GameAlias, GameBgg, Offer, OfferPrice
from catalog.schemas import (
    IngestResult,
    IngestResultItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


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

    for product in payload.products:
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

        # Не трогаем оператора: manual / rejected — финальные решения.
        if current_status in ("manual", "rejected"):
            new_game_id = current_game_id
            new_status = current_status
            new_score: float | None = None
        else:
            cand = await find_best_match(session, product.title)
            new_score = cand.score if cand else None
            new_status = classify(new_score)
            new_game_id = cand.game_id if (cand and new_score and new_score >= AUTO_MATCH_THRESHOLD) else None

            await session.execute(
                Offer.__table__.update()
                .where(Offer.__table__.c.id == offer_id)
                .values(
                    game_id=new_game_id,
                    match_status=new_status,
                    match_score=new_score,
                )
            )

            # Auto-match → запоминаем title_raw как alias, чтобы следующий
            # парсер с тем же написанием сматчился по alias_norm (быстрее
            # и стабильнее, чем по trigram'у).
            if new_status == "auto" and new_game_id is not None:
                await session.execute(
                    pg_insert(GameAlias.__table__)
                    .values(
                        game_id=new_game_id,
                        alias=product.title,
                        source="auto-match",
                    )
                    .on_conflict_do_nothing(constraint="uq_alias_per_game")
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
        items=items,
    )
