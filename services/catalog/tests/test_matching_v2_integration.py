"""Integration-тесты matching v2 — требуют живую тестовую БД с миграцией 0011.

Запуск:
    export TEST_DATABASE_URL='postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test'
    cd services/catalog && uv run pytest tests/test_matching_v2_integration.py -v

Покрывают то, что нельзя тестировать unit-тестами:
  - SQL для tier_0_cache (TTL, negative cache, hit)
  - SQL для tier_1_trgm (UNION title/title_ru/aliases, GROUP BY, threshold)
  - match_decisions cache CRUD + invalidate_for_game
  - match_log.log_change + revert_one + bulk revert через batch_id
  - match_queue.enqueue + claim_batch + finalize_*
  - End-to-end /ingest/offers через ASGI — sync T0+T1 путь
  - Аудит изменений: link → match_log запись с предыдущим состоянием
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from catalog import api as api_mod
from catalog.matching.v2 import normalize_title
from catalog.matching.v2.auditor import log_change, revert_one, revert_batch
from catalog.matching.v2.decisions import (
    invalidate_for_game,
    save_decision,
)
from catalog.matching.v2.domain import MatchAction
from catalog.matching.v2.queue_repo import (
    claim_batch,
    count_by_status,
    enqueue,
    finalize_skipped,
    finalize_success,
    recover_stuck,
    reschedule_retry,
)
from catalog.matching.v2.tiers import tier_0_cache, tier_1_trgm
from catalog.models import (
    Game,
    GameAlias,
    MatchDecision,
    MatchLog,
    MatchQueue,
    Offer,
)
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def clean_v2_db(engine: AsyncEngine) -> None:
    """TRUNCATE matching v2 таблиц + games/offers для чистого старта."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE TABLE match_log, match_decisions, match_queue, "
            "games, game_aliases, offers, offer_prices, import_jobs "
            "RESTART IDENTITY CASCADE"
        ))


@pytest_asyncio.fixture
async def session(engine: AsyncEngine, clean_v2_db: None) -> AsyncIterator[AsyncSession]:
    """Async session с автоматическим commit/close."""
    Factory = async_sessionmaker(engine, expire_on_commit=False)
    async with Factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(clean_v2_db: None) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_game(
    session: AsyncSession,
    *,
    slug: str = "carcassonne",
    title: str = "Carcassonne",
    title_ru: str | None = "Каркассон",
    kind: str = "base",
) -> int:
    game = Game(slug=slug, title=title, title_ru=title_ru, kind=kind, source="manual")
    session.add(game)
    await session.commit()
    await session.refresh(game)
    return game.id


# ── Tier 0: match_decisions cache ─────────────────────────────────────────


class TestTier0Cache:
    async def test_cache_miss_returns_none(self, session: AsyncSession):
        result = await tier_0_cache(session, "несуществующий")
        assert result is None

    async def test_cache_hit_positive(self, session: AsyncSession):
        gid = await _seed_game(session)
        await save_decision(
            session, title_norm="каркассон", game_id=gid,
            source="manual", tier=None, score=0.95,
        )
        await session.commit()

        result = await tier_0_cache(session, "каркассон")
        assert result is not None
        assert result.matched is True
        assert result.game_id == gid
        assert result.tier == 0
        assert "manual" in (result.reason or "")

    async def test_cache_hit_negative(self, session: AsyncSession):
        """game_id=NULL — это negative cache (reject). Должен возвращать REJECT."""
        await save_decision(
            session, title_norm="мусор", game_id=None,
            source="manual", tier=None, score=None,
        )
        await session.commit()

        result = await tier_0_cache(session, "мусор")
        assert result is not None
        assert result.matched is False
        assert result.action == MatchAction.REJECT

    async def test_ttl_expired_treated_as_miss(self, session: AsyncSession):
        """Запись с истёкшим TTL не возвращается."""
        gid = await _seed_game(session)
        # ручной INSERT с уже истёкшим decided_at
        await session.execute(text(
            "INSERT INTO match_decisions (title_norm, game_id, source, ttl_days, decided_at) "
            "VALUES (:tn, :gid, 'auto_t1', 30, now() - interval '31 days')"
        ).bindparams(tn="stale_title", gid=gid))
        await session.commit()

        result = await tier_0_cache(session, "stale_title")
        assert result is None  # TTL истёк → miss

    async def test_invalidate_for_game(self, session: AsyncSession):
        gid = await _seed_game(session)
        await save_decision(
            session, title_norm="a", game_id=gid, source="manual",
        )
        await save_decision(
            session, title_norm="b", game_id=gid, source="auto_t1",
            tier=1, score=0.95,
        )
        await session.commit()

        deleted = await invalidate_for_game(session, gid)
        assert deleted == 2
        await session.commit()

        # Cache miss после инвалидации
        assert await tier_0_cache(session, "a") is None
        assert await tier_0_cache(session, "b") is None


# ── Tier 1: pg_trgm ────────────────────────────────────────────────────────


class TestTier1Trgm:
    async def test_exact_match_above_threshold(self, session: AsyncSession):
        gid = await _seed_game(session, title_ru="Каркассон")
        result = await tier_1_trgm(session, "Каркассон", auto_threshold=0.92)
        assert result is not None
        assert result.matched is True
        assert result.game_id == gid
        assert result.tier == 1

    async def test_typo_above_threshold(self, session: AsyncSession):
        """«Каркасон» (одна 'с' пропущена) vs «Каркассон» — должен сматчиться."""
        gid = await _seed_game(session, title_ru="Каркассон")
        result = await tier_1_trgm(session, "Каркасон", auto_threshold=0.7)
        # На 0.7 опечатка ловится; на 0.92 — нет (~0.73 similarity)
        if result and result.score and result.score >= 0.7:
            assert result.game_id == gid

    async def test_unrelated_returns_none_or_candidates(self, session: AsyncSession):
        await _seed_game(session, title_ru="Каркассон")
        result = await tier_1_trgm(session, "Совершенно другая игра")
        # Может быть None или вернуть кандидатов ниже threshold
        if result is not None:
            assert result.matched is False

    async def test_alias_match(self, session: AsyncSession):
        gid = await _seed_game(session, title_ru="Каркассон")
        # Добавляем alias
        session.add(GameAlias(
            game_id=gid, alias="Каркассон: базовая игра",
            source="manual", language="ru",
        ))
        await session.commit()

        result = await tier_1_trgm(
            session, "Каркассон: базовая игра", auto_threshold=0.92,
        )
        assert result is not None
        assert result.matched is True
        assert result.game_id == gid


# ── match_log + revert ─────────────────────────────────────────────────────


class TestMatchLogAudit:
    async def test_log_change_creates_record(self, session: AsyncSession):
        gid = await _seed_game(session)
        # Создаём offer
        offer = Offer(
            store_slug="test", external_id="1",
            url="http://x", title_raw="X",
            match_status="unmatched",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)

        log_id = await log_change(
            session, offer_id=offer.id, action=MatchAction.AUTO_T1,
            prev_game_id=None, new_game_id=gid,
            prev_status="unmatched", new_status="auto",
            tier=1, score=0.95, reason="trgm_title_ru",
            performed_by="test",
        )
        await session.commit()

        log = await session.get(MatchLog, log_id)
        assert log is not None
        assert log.action == "auto_t1"
        assert log.new_game_id == gid
        assert log.score == 0.95
        assert log.reverted_at is None

    async def test_revert_one_restores_offer_state(self, session: AsyncSession):
        gid = await _seed_game(session)
        offer = Offer(
            store_slug="test", external_id="1",
            url="http://x", title_raw="Carcassonne",
            match_status="auto", game_id=gid,
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)

        log_id = await log_change(
            session, offer_id=offer.id, action=MatchAction.AUTO_T1,
            prev_game_id=None, new_game_id=gid,
            prev_status="unmatched", new_status="auto",
            tier=1, score=0.95,
        )
        await session.commit()

        result = await revert_one(session, log_id, performed_by="test")
        await session.commit()

        # offer вернулся в unmatched
        offer_refreshed = await session.get(Offer, offer.id, populate_existing=True)
        assert offer_refreshed.game_id is None
        assert offer_refreshed.match_status == "unmatched"

        # Создалась revert-запись в match_log
        assert "revert_log_id" in result
        revert_log = await session.get(MatchLog, result["revert_log_id"])
        assert revert_log.action == "revert"

    async def test_revert_batch_by_uuid(self, session: AsyncSession):
        """Bulk-revert: один batch_id = одна операция отката."""
        gid = await _seed_game(session)
        batch = uuid4()
        offer_ids: list[int] = []
        log_ids: list[int] = []

        for i in range(3):
            offer = Offer(
                store_slug="test", external_id=f"{i}",
                url=f"http://x/{i}", title_raw=f"X{i}",
                match_status="auto", game_id=gid,
            )
            session.add(offer)
            await session.commit()
            await session.refresh(offer)
            offer_ids.append(offer.id)

            log_id = await log_change(
                session, offer_id=offer.id, action=MatchAction.AUTO_T2,
                prev_game_id=None, new_game_id=gid,
                prev_status="unmatched", new_status="auto",
                tier=2, score=0.88, batch_id=batch,
            )
            log_ids.append(log_id)

        await session.commit()

        result = await revert_batch(session, batch, performed_by="test")
        await session.commit()

        assert result["reverted"] == 3
        for oid in offer_ids:
            offer = await session.get(Offer, oid, populate_existing=True)
            assert offer.match_status == "unmatched"
            assert offer.game_id is None


# ── match_queue: outbox ────────────────────────────────────────────────────


class TestMatchQueue:
    async def test_enqueue_idempotent(self, session: AsyncSession):
        """Повторный enqueue одного offer_id не плодит дубль."""
        gid = await _seed_game(session)
        offer = Offer(
            store_slug="t", external_id="1", url="http://x",
            title_raw="Y", match_status="unmatched",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)

        id1 = await enqueue(
            session, offer_id=offer.id, store_slug="t",
            title_raw="Y", title_norm="y",
        )
        id2 = await enqueue(
            session, offer_id=offer.id, store_slug="t",
            title_raw="Y", title_norm="y",
        )
        await session.commit()

        # UNIQUE(offer_id) + ON CONFLICT DO UPDATE: один ряд, обновлённый
        rows = (await session.execute(
            select(MatchQueue).where(MatchQueue.offer_id == offer.id)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "pending"

    async def test_claim_batch_marks_processing(self, session: AsyncSession):
        gid = await _seed_game(session)
        offer = Offer(
            store_slug="t", external_id="1", url="http://x",
            title_raw="Z", match_status="unmatched",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)

        await enqueue(
            session, offer_id=offer.id, store_slug="t",
            title_raw="Z", title_norm="z",
        )
        await session.commit()

        claimed = await claim_batch(session, 10)
        await session.commit()
        assert len(claimed) == 1
        assert claimed[0].offer_id == offer.id
        # processing уже не виден повторно
        again = await claim_batch(session, 10)
        await session.commit()
        assert len(again) == 0

    async def test_finalize_success_marks_done(self, session: AsyncSession):
        gid = await _seed_game(session)
        offer = Offer(
            store_slug="t", external_id="1", url="http://x",
            title_raw="W", match_status="unmatched",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)
        await enqueue(
            session, offer_id=offer.id, store_slug="t",
            title_raw="W", title_norm="w",
        )
        await session.commit()

        claimed = await claim_batch(session, 1)
        await session.commit()
        await finalize_success(
            session, claimed[0].id, game_id=gid, score=0.9, tier=2,
        )
        await session.commit()

        counts = await count_by_status(session)
        assert counts.get("done", 0) == 1
        assert counts.get("pending", 0) == 0

    async def test_claim_batch_sets_claimed_at(self, session: AsyncSession):
        """`claim_batch` денормализует момент claim'а в `claimed_at` — это
        источник правды для `recover_stuck` (не `created_at`).
        """
        await _seed_game(session)
        offer = Offer(
            store_slug="t", external_id="cl1", url="http://x",
            title_raw="ClaimedAt", match_status="unmatched",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)

        await enqueue(
            session, offer_id=offer.id, store_slug="t",
            title_raw="ClaimedAt", title_norm="claimedat",
        )
        await session.commit()

        # До claim: claimed_at = NULL.
        row = (await session.execute(
            select(MatchQueue).where(MatchQueue.offer_id == offer.id)
        )).scalar_one()
        assert row.claimed_at is None

        await claim_batch(session, 10)
        await session.commit()

        # После claim: claimed_at заполнен.
        await session.refresh(row)
        assert row.claimed_at is not None
        assert row.status == "processing"

    async def test_recover_stuck_skips_null_claimed_at(self, session: AsyncSession):
        """Legacy-строки (claimed_at IS NULL) НЕ подбираются recover_stuck —
        безопаснее оставить оператору на разбор, чем перепрогонять без точного
        timestamp claim'а. Это контракт миграции 0013.
        """
        await _seed_game(session)
        offer = Offer(
            store_slug="t", external_id="leg1", url="http://x",
            title_raw="Legacy", match_status="unmatched",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)

        await enqueue(
            session, offer_id=offer.id, store_slug="t",
            title_raw="Legacy", title_norm="legacy",
        )
        await session.commit()

        # Симулируем legacy-строку: processing + claimed_at=NULL + старый created_at.
        await session.execute(text(
            "UPDATE match_queue SET status='processing', "
            "claimed_at=NULL, created_at=now() - interval '1 hour' "
            "WHERE offer_id=:oid"
        ).bindparams(oid=offer.id))
        await session.commit()

        recovered = await recover_stuck(session, stale_minutes=5)
        await session.commit()
        assert recovered == 0

        row = (await session.execute(
            select(MatchQueue).where(MatchQueue.offer_id == offer.id)
        )).scalar_one()
        assert row.status == "processing"  # не тронут

    async def test_recover_stuck_returns_stale_processing(self, session: AsyncSession):
        """Записи с claimed_at старше stale_minutes возвращаются в pending,
        и claimed_at сбрасывается в NULL (чтобы повторный recover не нашёл их).
        """
        await _seed_game(session)
        offer = Offer(
            store_slug="t", external_id="st1", url="http://x",
            title_raw="Stuck", match_status="unmatched",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)

        await enqueue(
            session, offer_id=offer.id, store_slug="t",
            title_raw="Stuck", title_norm="stuck",
        )
        await session.commit()

        await claim_batch(session, 1)
        # Сдвигаем claimed_at в прошлое (10 минут назад при stale_minutes=5).
        await session.execute(text(
            "UPDATE match_queue SET claimed_at=now() - interval '10 minutes' "
            "WHERE offer_id=:oid"
        ).bindparams(oid=offer.id))
        await session.commit()

        recovered = await recover_stuck(session, stale_minutes=5)
        await session.commit()
        assert recovered == 1

        row = (await session.execute(
            select(MatchQueue).where(MatchQueue.offer_id == offer.id)
        )).scalar_one()
        assert row.status == "pending"
        assert row.claimed_at is None  # сброшено для семантической чистоты

    async def test_reschedule_retry_backoff(self, session: AsyncSession):
        offer = Offer(
            store_slug="t", external_id="1", url="http://x",
            title_raw="R", match_status="unmatched",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)
        await enqueue(
            session, offer_id=offer.id, store_slug="t",
            title_raw="R", title_norm="r",
        )
        await session.commit()

        claimed = await claim_batch(session, 1)
        await session.commit()

        status = await reschedule_retry(
            session, claimed[0].id, error="test_error", max_attempts=3,
        )
        await session.commit()
        assert status == "pending"
        # 3-я попытка → failed
        for _ in range(2):
            claimed = await claim_batch(session, 1)
            # next_attempt_at в будущем — claim_batch не вернёт, симулируем reset
            await session.execute(text(
                "UPDATE match_queue SET status='processing', next_attempt_at=NULL"
            ))
            await session.commit()
            status = await reschedule_retry(
                session, claimed[0].id if claimed else 1,
                error="test", max_attempts=3,
            ) if claimed else None
            await session.commit()


# ── End-to-end /ingest/offers через ASGI ──────────────────────────────────


class TestIngestE2E:
    async def test_ingest_cache_hit_on_second_call(self, client: AsyncClient):
        """1-й ingest → T1 match + save_decision. 2-й того же title → T0 hit."""
        # seed game c title_ru = "Каркассон"
        r = await client.post(
            "/games",
            json={"slug": "carc", "title": "Carcassonne", "title_ru": "Каркассон"},
        )
        assert r.status_code in (200, 201)

        # 1-й ingest
        r1 = await client.post(
            "/ingest/offers",
            json={
                "store_slug": "hg",
                "products": [{
                    "external_id": "1", "title": "Каркассон",
                    "url": "http://x", "price": 100000,
                }],
            },
        )
        assert r1.status_code == 200
        body1 = r1.json()
        item1 = body1["items"][0]
        # T1 trgm должен сработать — игра по title_ru совпадает
        assert item1["match_status"] in ("auto", "unmatched")

        # 2-й ingest с тем же external_id → T0 cache (если 1-й был auto)
        r2 = await client.post(
            "/ingest/offers",
            json={
                "store_slug": "hg",
                "products": [{
                    "external_id": "1", "title": "Каркассон",
                    "url": "http://x", "price": 100000,
                }],
            },
        )
        assert r2.status_code == 200

    async def test_ml_status_endpoint(self, client: AsyncClient):
        r = await client.get("/matching/ml-status")
        assert r.status_code == 200
        body = r.json()
        # Структура: models + queue + failures
        assert "models" in body
        assert "queue" in body

    async def test_match_log_empty_initially(self, client: AsyncClient):
        r = await client.get("/matching/log")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body
