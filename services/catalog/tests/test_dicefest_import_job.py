"""Integration-тесты `_run_dicefest_import_job` (фоновая задача парсера).

Не запускаем настоящий HTTP к dicefest — monkey-patch'им fetch_listing /
fetch_card на чтение фикстур. Тесты идут через реальную тестовую БД (catalog_test),
проверяют что:
  - запись попадает в dicefest_raw_games;
  - re-run не плодит дублей и пропускает свежие slug'и;
  - max_items ограничивает прогон;
  - progress / log_lines обновляются.

Также мокаем asyncio.sleep, чтобы тест не ждал rate-limit (1 сек × N).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from catalog.db import get_engine
from catalog.importers import dicefest as dfmod
from catalog.models import DicefestRawGame, ImportJob
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]

FIXTURES = Path(__file__).parent / "fixtures"


@pytest_asyncio.fixture
async def clean_db(engine: AsyncEngine) -> None:
    """Чистим job + staging перед каждым тестом. RESTART IDENTITY — чтобы id
    предсказуемо начинался с 1 (тест не зависит от конкретного значения, но
    debug проще)."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE dicefest_raw_games, import_jobs "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def session(clean_db: None, engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as s:
        yield s


@pytest_asyncio.fixture(autouse=True)
async def _patch_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяем сетевые I/O на чтение фикстур + ускоряем sleep."""
    listing_html = (FIXTURES / "dicefest_listing_mini.html").read_text(encoding="utf-8")
    card_full = (FIXTURES / "dicefest_card_full.html").read_text(encoding="utf-8")
    card_year = (FIXTURES / "dicefest_card_year_half.html").read_text(encoding="utf-8")
    card_unknown = (FIXTURES / "dicefest_card_unknown_date.html").read_text(encoding="utf-8")

    cards = {
        "mythologies": card_full,
        "a-gest-of-robin-hood": card_year,
        "claustrophobia-1692": card_unknown,
        "azuleo": "<html>minimal stub for fourth slug</html>",
    }

    async def fake_fetch_listing(client, year=None):  # noqa: ARG001
        # parse_listing_html выберет 4 slug'а из мини-листинга
        slugs = dfmod.parse_listing_html(listing_html)
        label = "homepage" if year is None else f"year={year}"
        return slugs, label

    async def fake_fetch_card(client, slug):  # noqa: ARG001
        if slug not in cards:
            raise dfmod.httpx.HTTPError(f"404 for {slug}")
        return cards[slug]

    async def fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(dfmod, "fetch_listing", fake_fetch_listing)
    monkeypatch.setattr(dfmod, "fetch_card", fake_fetch_card)
    monkeypatch.setattr(dfmod.asyncio, "sleep", fast_sleep)


async def _create_job(session: AsyncSession, payload: dict) -> int:
    job = ImportJob(type="dicefest", payload=payload, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job.id


async def _get_job(session: AsyncSession, job_id: int) -> ImportJob:
    # expire — чтобы получить свежие значения после background-task'а
    obj = await session.get(ImportJob, job_id)
    assert obj is not None
    await session.refresh(obj)
    return obj


# ─── tests ────────────────────────────────────────────────────────────────────


async def test_import_writes_to_staging(session: AsyncSession) -> None:
    job_id = await _create_job(session, {})
    await dfmod._run_dicefest_import_job(job_id, {})

    # У нас 4 slug'а в фикстуре листинга, 3 успешные карточки + 1 минимальная
    # (azuleo возвращает <html>minimal stub</html> — парсер не упадёт, но
    # большинство полей будут None).
    rows = (
        await session.execute(
            text("SELECT slug, title_ru, publisher FROM dicefest_raw_games ORDER BY slug")
        )
    ).all()
    slugs = [r[0] for r in rows]
    assert slugs == sorted(["mythologies", "a-gest-of-robin-hood",
                            "claustrophobia-1692", "azuleo"])

    # Mythologies должна быть полной
    by_slug = {r[0]: r for r in rows}
    assert by_slug["mythologies"][1] == "Mythologies"
    assert by_slug["mythologies"][2] == "4GAMES"

    # job статус — done, прогресс заполнен
    job = await _get_job(session, job_id)
    assert job.status == "done"
    assert job.error is None
    assert job.progress is not None
    assert job.progress["phase"] == "done"
    assert job.progress["total"] == 4
    assert job.progress["current"] == 4
    assert job.result is not None
    assert len(job.result["imported"]) == 4
    assert job.result["errors"] == []


async def test_import_idempotent_on_rerun(session: AsyncSession) -> None:
    """Второй запуск с теми же slug'ами не плодит дублей и пропускает свежие."""
    job1 = await _create_job(session, {})
    await dfmod._run_dicefest_import_job(job1, {})
    count1 = (
        await session.execute(text("SELECT count(*) FROM dicefest_raw_games"))
    ).scalar_one()
    assert count1 == 4

    job2 = await _create_job(session, {})
    await dfmod._run_dicefest_import_job(job2, {})
    count2 = (
        await session.execute(text("SELECT count(*) FROM dicefest_raw_games"))
    ).scalar_one()
    assert count2 == 4  # дублей нет — UNIQUE(slug) + ON CONFLICT

    # Все 4 должны быть пропущены как fresh
    job = await _get_job(session, job2)
    assert job.result is not None
    assert job.result["skipped_fresh"] == 4


async def test_import_max_items_limits_run(session: AsyncSession) -> None:
    """max_items=2 → только 2 записи в staging."""
    job_id = await _create_job(session, {"max_items": 2})
    await dfmod._run_dicefest_import_job(job_id, {"max_items": 2})

    count = (
        await session.execute(text("SELECT count(*) FROM dicefest_raw_games"))
    ).scalar_one()
    assert count == 2
    job = await _get_job(session, job_id)
    assert job.progress is not None
    assert job.progress["total"] == 2


async def test_import_progress_and_log_lines_updated(session: AsyncSession) -> None:
    """После завершения progress.current == total и log_lines непустой."""
    job_id = await _create_job(session, {})
    await dfmod._run_dicefest_import_job(job_id, {})
    job = await _get_job(session, job_id)
    assert job.log_lines is not None
    assert len(job.log_lines) >= 4  # минимум по строке на slug
    # последняя строка — итог
    last = job.log_lines[-1]
    assert "Готово" in last or "Записано" in last
