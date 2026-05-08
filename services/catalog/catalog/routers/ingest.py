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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.matching.matcher import (
    AUTO_MATCH_THRESHOLD,
    classify,
    find_best_match,
)
from catalog.models import GameAlias, Offer, OfferPrice
from catalog.schemas import (
    IngestRequest,
    IngestResult,
    IngestResultItem,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
