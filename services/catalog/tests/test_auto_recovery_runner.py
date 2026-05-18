"""Тесты auto_recovery_runner (CAT-4.5).

Тестируем `run_once`: condition checking + dedup + action execution.
HTTP-вызовы к parsers моканы, OllamaHealth сбрасывается в начале каждого
теста (singleton state).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from catalog.matching.v2.auto_recovery import run_once
from catalog.matching.v2.health import OllamaHealth
from catalog.models import AutoRecoveryRule, ImportJob, MatchQueue, Offer
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]


@pytest_asyncio.fixture
async def clean_recovery(engine: AsyncEngine) -> None:
    """Чистим таблицы перед каждым тестом + сбрасываем OllamaHealth."""
    OllamaHealth.reset_for_tests()
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE TABLE auto_recovery_rules, match_queue, offers, "
            "import_jobs RESTART IDENTITY CASCADE"
        ))


async def _create_offer(factory, offer_id: int, store_slug: str = "wb") -> None:
    """Helper — создаёт оффер для FK constraint match_queue.offer_id."""
    async with factory() as session:
        session.add(Offer(
            id=offer_id, store_slug=store_slug, external_id=str(offer_id),
            url=f"http://x/{offer_id}", title_raw=f"t{offer_id}",
        ))
        await session.commit()


@pytest_asyncio.fixture
async def factory(engine: AsyncEngine, clean_recovery: None):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _create_rule(
    factory, name: str, condition: dict, action: dict, *,
    enabled: bool = True, last_triggered_at: datetime | None = None,
) -> int:
    async with factory() as session:
        rule = AutoRecoveryRule(
            name=name, condition=condition, action=action,
            enabled=enabled, last_triggered_at=last_triggered_at,
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule.id


async def test_disabled_rule_skipped(factory):
    await _create_rule(
        factory, "off-rule",
        condition={"type": "circuit_state", "model": "x", "becomes": "closed"},
        action={"type": "re_enqueue_skipped"},
        enabled=False,
    )
    summary = await run_once(factory)
    assert summary["checked"] == 0
    assert summary["triggered"] == 0


async def test_dedup_skips_recently_triggered(factory):
    """last_triggered_at в пределах dedup_minutes → skip."""
    # OllamaHealth → closed чтобы condition был True.
    h = OllamaHealth.get_instance()
    h._status["bge-m3"] = True  # type: ignore[attr-defined]
    h._failures["bge-m3"] = 0  # type: ignore[attr-defined]

    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    await _create_rule(
        factory, "recent",
        condition={"type": "circuit_state", "model": "bge-m3", "becomes": "closed",
                   "dedup_minutes": 5},
        action={"type": "re_enqueue_skipped"},
        last_triggered_at=recent,
    )
    summary = await run_once(factory)
    assert summary["checked"] == 1
    assert summary["triggered"] == 0


async def test_circuit_state_closed_triggers_re_enqueue(factory):
    """Условие выполнено + last_triggered_at давний/null → action выполнен."""
    h = OllamaHealth.get_instance()
    h._status["bge-m3"] = True  # type: ignore[attr-defined]
    h._failures["bge-m3"] = 0  # type: ignore[attr-defined]

    # Засеваем skipped в очереди (с реальными офферами для FK)
    for i in range(3):
        await _create_offer(factory, 100 + i)
    async with factory() as session:
        for i in range(3):
            session.add(MatchQueue(
                offer_id=100 + i, store_slug="wb",
                title_raw="x", title_norm="x",
                status="skipped", error_detail="ml_unavailable: ...",
            ))
        await session.commit()

    rule_id = await _create_rule(
        factory, "qwen-recovery",
        condition={"type": "circuit_state", "model": "bge-m3", "becomes": "closed"},
        action={"type": "re_enqueue_skipped",
                "filters": {"reason": ["ml_unavailable"]}},
    )
    summary = await run_once(factory)
    assert summary["triggered"] == 1

    # last_triggered_at и last_result обновлены
    async with factory() as session:
        rule = await session.get(AutoRecoveryRule, rule_id)
        assert rule.last_triggered_at is not None
        assert "re_enqueued=3" in (rule.last_result or "")

    # Все 3 записи теперь pending
    async with factory() as session:
        rows = (await session.execute(
            select(MatchQueue.status).where(MatchQueue.status == "pending")
        )).all()
        assert len(rows) == 3


async def test_circuit_state_open_does_not_trigger(factory):
    """Модель в open — condition.becomes='closed' не выполнен."""
    # Default state — unknown (singleton сброшен в clean fixture).
    h = OllamaHealth.get_instance()
    h._status["bge-m3"] = False  # type: ignore[attr-defined]

    await _create_rule(
        factory, "no-trigger",
        condition={"type": "circuit_state", "model": "bge-m3", "becomes": "closed"},
        action={"type": "re_enqueue_skipped"},
    )
    summary = await run_once(factory)
    assert summary["triggered"] == 0


async def test_job_completed_condition(factory):
    """Последний ImportJob нужного type имеет status='done' → condition True."""
    async with factory() as session:
        session.add(ImportJob(type="bgg-batch", payload={}, status="done"))
        await session.commit()

    await _create_rule(
        factory, "after-bgg",
        condition={"type": "job_completed", "job_type": "bgg-batch"},
        action={"type": "re_enqueue_skipped"},
    )
    summary = await run_once(factory)
    assert summary["triggered"] == 1


async def test_job_completed_running_does_not_trigger(factory):
    """Если последний job — running, condition False."""
    async with factory() as session:
        # done → старый
        session.add(ImportJob(type="bgg-batch", payload={}, status="done"))
        await session.flush()
        # running → последний
        session.add(ImportJob(type="bgg-batch", payload={}, status="running"))
        await session.commit()

    await _create_rule(
        factory, "after-bgg",
        condition={"type": "job_completed", "job_type": "bgg-batch"},
        action={"type": "re_enqueue_skipped"},
    )
    summary = await run_once(factory)
    assert summary["triggered"] == 0


async def test_unknown_condition_skipped(factory):
    await _create_rule(
        factory, "weird",
        condition={"type": "unknown_thing"},
        action={"type": "re_enqueue_skipped"},
    )
    summary = await run_once(factory)
    assert summary["checked"] == 1
    assert summary["triggered"] == 0


async def test_re_enqueue_filters_by_reason(factory):
    """filters.reason — LIKE prefix match по error_detail."""
    h = OllamaHealth.get_instance()
    h._status["bge-m3"] = True  # type: ignore[attr-defined]

    await _create_offer(factory, 1)
    await _create_offer(factory, 2)
    async with factory() as session:
        session.add(MatchQueue(
            offer_id=1, store_slug="wb", title_raw="a", title_norm="a",
            status="skipped", error_detail="ml_unavailable: connect",
        ))
        session.add(MatchQueue(
            offer_id=2, store_slug="wb", title_raw="b", title_norm="b",
            status="skipped", error_detail="vec_below_threshold",
        ))
        await session.commit()

    await _create_rule(
        factory, "filter-test",
        condition={"type": "circuit_state", "model": "bge-m3", "becomes": "closed"},
        action={"type": "re_enqueue_skipped", "filters": {"reason": ["ml_unavailable"]}},
    )
    await run_once(factory)
    # Только offer_id=1 должен стать pending
    async with factory() as session:
        rows = (await session.execute(
            select(MatchQueue.offer_id, MatchQueue.status)
            .order_by(MatchQueue.offer_id)
        )).all()
        assert rows[0].status == "pending"
        assert rows[1].status == "skipped"
