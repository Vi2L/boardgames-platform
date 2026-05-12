"""Integration-тесты `upsert_bgg_data` — требуют живую тестовую БД с миграцией 0012.

Покрывают то, что нельзя проверить unit-тестами:
  - Запись всех новых полей в game_bgg при первом upsert.
  - raw blob {"parsed": ..., "xml": ...} (CAT-7) + bgg_stats_updated_at.
  - Идемпотентность — повторный upsert обновляет, не плодит дубли.
  - Перезапись CSV-полей XML-обогащением (CAT-5, Q2): bayes_average/average/
    users_rated теперь источник истины — XML.
  - CSV-импорт после XML НЕ откатывает XML-territory: source остаётся 'xml-api',
    raw не перетирается CSV-payload, bgg_stats_updated_at сохраняется.

Запуск:
    export TEST_DATABASE_URL='postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test'
    cd services/catalog && uv run pytest tests/test_bgg_repository.py -v
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from catalog.models import GameBgg
from catalog.parsers.bgg.parser import parse_thing_xml
from catalog.parsers.bgg.repository import upsert_bgg_data
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]

FIXTURE = Path(__file__).parent / "fixtures" / "bgg_carcassonne.xml"


@pytest_asyncio.fixture
async def clean_bgg_db(engine: AsyncEngine) -> None:
    """TRUNCATE games + satellite — чистый старт для каждого теста."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE TABLE game_bgg, game_aliases, games "
            "RESTART IDENTITY CASCADE"
        ))


@pytest_asyncio.fixture
async def session(engine: AsyncEngine, clean_bgg_db: None) -> AsyncIterator[AsyncSession]:
    Factory = async_sessionmaker(engine, expire_on_commit=False)
    async with Factory() as s:
        yield s


async def _get_bgg_row(session: AsyncSession, bgg_id: int) -> GameBgg:
    row = (await session.execute(
        select(GameBgg).where(GameBgg.bgg_id == bgg_id)
    )).scalar_one()
    return row


async def test_upsert_writes_all_new_fields(session: AsyncSession) -> None:
    """Первый upsert новой игры — все новые колонки + raw blob заполняются."""
    xml = FIXTURE.read_text(encoding="utf-8")
    bgg = parse_thing_xml(xml)
    assert bgg is not None

    await upsert_bgg_data(session, bgg, xml)
    await session.commit()

    row = await _get_bgg_row(session, 822)
    # CAT-5: расширенная статистика.
    assert row.users_rated == 118000
    assert row.average_weight == pytest.approx(1.89)
    assert row.num_weights == 24000
    # CAT-5: XML теперь перезаписывает CSV-метрики.
    assert row.bayes_average == pytest.approx(7.32)
    assert row.average == pytest.approx(7.42)
    # CAT-6: poll'ы.
    assert row.recommended_players is not None
    assert row.recommended_players["3"]["best"] == 250
    assert row.recommended_age == 8
    assert row.language_dependence == 1
    # CAT-7: raw blob + timestamp.
    assert row.raw is not None
    assert "parsed" in row.raw
    assert "xml" in row.raw
    assert row.raw["parsed"]["bgg_id"] == 822
    assert "<item" in row.raw["xml"]
    assert row.bgg_stats_updated_at is not None
    assert row.source == "xml-api"


async def test_upsert_idempotent(session: AsyncSession) -> None:
    """Повторный upsert обновляет fetched_at, не плодит дубли."""
    xml = FIXTURE.read_text(encoding="utf-8")
    bgg = parse_thing_xml(xml)
    assert bgg is not None

    await upsert_bgg_data(session, bgg, xml)
    await session.commit()
    first_fetched = (await _get_bgg_row(session, 822)).fetched_at

    # Эмулируем повторный enrich — данные те же, fetched_at должен обновиться.
    await upsert_bgg_data(session, bgg, xml)
    await session.commit()

    rows = (await session.execute(
        select(GameBgg).where(GameBgg.bgg_id == 822)
    )).scalars().all()
    assert len(rows) == 1  # PK (game_id) защищает от дубля
    assert rows[0].fetched_at >= first_fetched


async def test_upsert_overwrites_csv_metrics(session: AsyncSession) -> None:
    """Q2: XML перезаписывает bayes_average/average/users_rated, даже если
    они уже были в game_bgg из CSV-выгрузки."""
    # Семитруем CSV-state: создаём game + game_bgg с заведомо «старыми» CSV-значениями.
    bgg_t = GameBgg.__table__
    await session.execute(text(
        "INSERT INTO games (slug, title, bgg_id, source, status) "
        "VALUES ('carcassonne-822', 'Carcassonne', 822, 'bgg-ranks', 'published')"
    ))
    game_id = (await session.execute(
        text("SELECT id FROM games WHERE bgg_id = 822")
    )).scalar_one()
    await session.execute(pg_insert(bgg_t).values(
        game_id=game_id,
        bgg_id=822,
        # CSV-метрики (намеренно «устаревшие» — XML должен их перезаписать).
        rank=155,
        bayes_average=6.50,  # → 7.32 из XML
        average=6.99,        # → 7.42 из XML
        users_rated=50000,   # → 118000 из XML
        is_expansion=False,
        subtype_ranks={"strategygames": 1},
        source="csv-ranks",
        raw={"csv": {"id": "822"}},
    ))
    await session.commit()

    # Теперь XML-обогащение.
    xml = FIXTURE.read_text(encoding="utf-8")
    bgg = parse_thing_xml(xml)
    assert bgg is not None
    await upsert_bgg_data(session, bgg, xml)
    await session.commit()

    row = await _get_bgg_row(session, 822)
    # XML перезаписал CSV-метрики.
    assert row.bayes_average == pytest.approx(7.32)
    assert row.average == pytest.approx(7.42)
    assert row.users_rated == 118000
    # CSV-only поля остались.
    assert row.rank == 155
    assert row.is_expansion is False
    assert row.subtype_ranks == {"strategygames": 1}
    # raw перетёрся свежим XML-blob'ом.
    assert "parsed" in row.raw
    assert row.source == "xml-api"


async def test_csv_does_not_revert_xml_territory(session: AsyncSession) -> None:
    """После XML-обогащения повторный CSV-импорт НЕ откатывает source/raw/
    bgg_stats_updated_at — они XML-territory с миграции 0012 (Q1 + наша правка).

    Воспроизводит вызов через тот же ON CONFLICT, что и `import_bgg_ranks.flush()`.
    """
    # Шаг 1: XML-обогащение.
    xml = FIXTURE.read_text(encoding="utf-8")
    bgg = parse_thing_xml(xml)
    assert bgg is not None
    await upsert_bgg_data(session, bgg, xml)
    await session.commit()
    row = await _get_bgg_row(session, 822)
    xml_stamp = row.bgg_stats_updated_at
    xml_raw = row.raw

    # Шаг 2: эмулируем CSV-импорт (повторение set_ из import_bgg_ranks.py).
    bgg_t = GameBgg.__table__
    csv_stmt = pg_insert(bgg_t).values(
        game_id=row.game_id,
        bgg_id=822,
        rank=160,  # CSV пересчитал — игра упала на 5 позиций.
        bayes_average=7.99,  # эти значения CSV пытается записать, но они исключены из set_.
        average=7.99,
        users_rated=999999,
        is_expansion=False,
        subtype_ranks={"familygames": 10},
        raw={"csv": {"id": "822", "rank": "160"}},
        source="csv-ranks",
    ).on_conflict_do_update(
        index_elements=["game_id"],
        set_={
            "rank": pg_insert(bgg_t).excluded.rank,
            "is_expansion": pg_insert(bgg_t).excluded.is_expansion,
            "subtype_ranks": pg_insert(bgg_t).excluded.subtype_ranks,
        },
    )
    await session.execute(csv_stmt)
    await session.commit()
    await session.refresh(row)

    # CSV обновил только rank/is_expansion/subtype_ranks.
    assert row.rank == 160
    assert row.subtype_ranks == {"familygames": 10}
    # XML-territory НЕ откатился.
    assert row.source == "xml-api"
    assert row.bgg_stats_updated_at == xml_stamp
    assert row.raw == xml_raw
    # CAT-5 метрики тоже остались из XML (не перезаписаны CSV-значениями).
    assert row.bayes_average == pytest.approx(7.32)
    assert row.average == pytest.approx(7.42)
    assert row.users_rated == 118000
