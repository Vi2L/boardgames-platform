"""Тесты расширенного match_candidates: weights и prefer_external_id.

Покрытие:
  * Backwards-compat: без params — поведение прежнее (1.0/1.0/1.0, без external_id).
  * weights: нулевой ru-вес отключает совпадение по русскому title; поднятие
    ru-веса перетягивает топ.
  * prefer_external_id: deterministic-кандидат с BGG ID добавляется со score=1.0
    и поднимается в начало списка, даже если fuzzy-результаты слабее.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from catalog.models import DicefestRawGame, Game, GameAlias
from catalog.promotion import dicefest as promo
from catalog.schemas import MatchParams, MatchWeights
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]


@pytest_asyncio.fixture
async def clean_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE import_promotion_log, game_dicefest, "
                "dicefest_raw_games, offers, offer_prices, game_aliases, "
                "game_bgg, game_wikidata, games "
                "RESTART IDENTITY CASCADE"
            ),
        )


@pytest_asyncio.fixture
async def session(clean_db: None, engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    Factory = async_sessionmaker(engine, expire_on_commit=False)
    async with Factory() as s:
        yield s


# ─── helpers ──────────────────────────────────────────────────────────────────


async def _mk_game(session: AsyncSession, **kw) -> Game:
    g = Game(slug=kw.pop("slug"), title=kw.pop("title"), **kw)
    session.add(g)
    await session.commit()
    await session.refresh(g)
    return g


async def _mk_alias(session: AsyncSession, game_id: int, alias: str, language: str | None = None) -> None:
    session.add(GameAlias(game_id=game_id, alias=alias, source="manual", language=language))
    await session.commit()


async def _mk_raw(session: AsyncSession, **kw) -> DicefestRawGame:
    raw = DicefestRawGame(
        slug=kw.pop("slug"),
        page_url=kw.pop("page_url", "https://dicefest.ru/game/x/"),
        raw=kw.pop("raw", {}),
        fetched_at=datetime.now(timezone.utc),
        external_links=kw.pop("external_links", []),
        **kw,
    )
    session.add(raw)
    await session.commit()
    await session.refresh(raw)
    return raw


# ─── backwards-compat ─────────────────────────────────────────────────────────


async def test_match_without_params_behaves_as_before(session: AsyncSession) -> None:
    """Без MatchParams — старый контракт: веса 1.0, threshold уважается."""
    await _mk_game(session, slug="g1", title="Carcassonne")
    raw = await _mk_raw(session, slug="r1", title_en="Carcassonne", title_ru=None)

    _, cands = await promo.match_candidates(session, raw.id, threshold=0.3, limit=5)
    assert cands, "должен быть минимум один кандидат"
    assert cands[0]["title"] == "Carcassonne"


# ─── weights ──────────────────────────────────────────────────────────────────


async def test_zero_ru_weight_disables_ru_match(session: AsyncSession) -> None:
    """weights.ru=0 → совпадение по title_ru не учитывается, остаётся только en."""
    await _mk_game(session, slug="g1", title="Каркассон")
    await _mk_game(session, slug="g2", title="Carcassonne")
    raw = await _mk_raw(
        session, slug="r1", title_ru="Каркассон", title_en="Carcassonne",
    )

    params = MatchParams(
        threshold=0.3,
        prefer_external_id=False,
        weights=MatchWeights(ru=0.0, en=1.0, alias=1.0),
    )
    _, cands = await promo.match_candidates(
        session, raw.id, threshold=0.3, limit=5, params=params,
    )
    titles = [c["title"] for c in cands]
    # ru-кандидат «Каркассон» отвалился (вес 0), остался только en.
    assert "Carcassonne" in titles
    assert "Каркассон" not in titles


async def test_high_ru_weight_promotes_ru_candidate(session: AsyncSession) -> None:
    """ru>en — ru-кандидат должен оказаться выше en, если оба матчатся."""
    await _mk_game(session, slug="g1", title="Каркассон")
    await _mk_game(session, slug="g2", title="Carcassonne")
    raw = await _mk_raw(
        session, slug="r1", title_ru="Каркассон", title_en="Carcassonne",
    )

    # ru-вес сильно больше — ожидаем «Каркассон» сверху.
    params = MatchParams(
        threshold=0.3,
        prefer_external_id=False,
        weights=MatchWeights(ru=2.0, en=0.5, alias=1.0),
    )
    _, cands = await promo.match_candidates(
        session, raw.id, threshold=0.3, limit=5, params=params,
    )
    assert cands[0]["title"] == "Каркассон"
    assert cands[0]["via"] == "title_ru"


# ─── prefer_external_id ───────────────────────────────────────────────────────


async def test_prefer_external_id_promotes_bgg_match(session: AsyncSession) -> None:
    """raw с BGG external_id находит canonical Game по games.bgg_id со score=1.0."""
    await _mk_game(session, slug="g1", title="Совсем не похожее название", bgg_id=822)
    raw = await _mk_raw(
        session,
        slug="r1",
        title_ru="Какой-то rebrand",
        external_links=[{"kind": "bgg", "url": "...", "external_id": "822"}],
    )

    params = MatchParams(
        threshold=0.3,
        prefer_external_id=True,
        weights=MatchWeights(),
    )
    _, cands = await promo.match_candidates(
        session, raw.id, threshold=0.3, limit=5, params=params,
    )
    assert cands, "должен найтись хотя бы external-кандидат"
    assert cands[0]["score"] == 1.0
    assert cands[0]["via"] == "external_id:bgg"
    assert cands[0]["title"] == "Совсем не похожее название"


async def test_prefer_external_id_does_not_duplicate_fuzzy_hit(session: AsyncSession) -> None:
    """Если та же Game была найдена и fuzzy, и через external_id — должна быть
    одна запись, причём с via='external_id:...' (deterministic заменяет fuzzy)."""
    await _mk_game(session, slug="g1", title="Carcassonne", bgg_id=822)
    raw = await _mk_raw(
        session,
        slug="r1",
        title_en="Carcassonne",
        external_links=[{"kind": "bgg", "external_id": "822"}],
    )

    params = MatchParams(
        threshold=0.3, prefer_external_id=True, weights=MatchWeights(),
    )
    _, cands = await promo.match_candidates(
        session, raw.id, threshold=0.3, limit=5, params=params,
    )
    # Каждая game_id встречается ровно один раз.
    game_ids = [c["game_id"] for c in cands]
    assert len(game_ids) == len(set(game_ids))
    # И первый — deterministic
    assert cands[0]["via"] == "external_id:bgg"


async def test_prefer_external_id_off_keeps_fuzzy_only(session: AsyncSession) -> None:
    """Если prefer_external_id=False — external_id ветка не активируется,
    даже если в raw есть BGG link."""
    await _mk_game(session, slug="g1", title="Carcassonne", bgg_id=822)
    raw = await _mk_raw(
        session,
        slug="r1",
        title_en="Carcassonne",
        external_links=[{"kind": "bgg", "external_id": "822"}],
    )

    params = MatchParams(
        threshold=0.3, prefer_external_id=False, weights=MatchWeights(),
    )
    _, cands = await promo.match_candidates(
        session, raw.id, threshold=0.3, limit=5, params=params,
    )
    assert cands
    # Только fuzzy-via, без external_id.
    assert all("external_id" not in c["via"] for c in cands)
