"""Тесты promotion-логики для dicefest.

8 сценариев из плана PR-2:
  1. match_returns_top5_sorted_by_score
  2. match_marks_existing_satellite — кандидат с уже привязанным dicefest → flag
  3. promote_link_creates_alias_and_satellite
  4. promote_create_creates_new_game_with_alias_and_satellite
  5. promote_idempotent_on_double_click — два POST → второй получает 409
  6. revert_undoes_link — alias/satellite удалены, raw.status='new'
  7. revert_after_merge_fails_loudly — games.status='merged' → 409
  8. revert_does_not_touch_offers — offers.game_id неизменно
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from catalog.models import (
    DicefestRawGame,
    Game,
    GameAlias,
    GameDicefest,
    ImportPromotionLog,
    Offer,
)
from catalog.promotion import dicefest as promo
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
            )
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


async def _mk_raw(session: AsyncSession, **kw) -> DicefestRawGame:
    r = DicefestRawGame(
        slug=kw.pop("slug"),
        page_url=kw.pop("page_url", "https://dicefest.ru/game/x/"),
        raw=kw.pop("raw", {}),
        fetched_at=datetime.now(timezone.utc),
        **kw,
    )
    session.add(r)
    await session.commit()
    await session.refresh(r)
    return r


# ─── 1. match top5 sorted ─────────────────────────────────────────────────────


async def test_match_returns_top5_sorted_by_score(session: AsyncSession) -> None:
    """Несколько похожих игр → сортировка по score DESC, limit=5."""
    # Готовим 6 канонических с разной похожестью на "Mythologies".
    titles = [
        "Mythologies",        # exact
        "Mythologies Mini",   # высокий
        "Mythos",             # средний
        "Settlers",           # низкий
        "Catan",              # низкий
        "Mythologi",          # высокий-typo
    ]
    for i, t in enumerate(titles):
        await _mk_game(session, slug=f"g{i}", title=t)
    raw = await _mk_raw(session, slug="myth", title_ru="Mythologies")

    raw_obj, candidates = await promo.match_candidates(
        session, raw.id, threshold=0.3, limit=5,
    )
    assert raw_obj.slug == "myth"
    assert len(candidates) <= 5
    # Score сортировано DESC
    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
    # Точное совпадение должно быть первым
    assert candidates[0]["title"] == "Mythologies"
    assert candidates[0]["score"] >= 0.99


# ─── 2. has_satellite_for_provider flag ───────────────────────────────────────


async def test_match_marks_existing_satellite(session: AsyncSession) -> None:
    """Игра, к которой уже привязан другой dicefest-page, помечена флагом."""
    g = await _mk_game(session, slug="m", title="Mythologies")
    raw_existing = await _mk_raw(session, slug="myth-old", title_ru="Mythologies (1-е изд)")
    # Добавим satellite — имитирует, что эту game уже промоушили
    sat = GameDicefest(
        game_id=g.id, raw_id=raw_existing.id, slug=raw_existing.slug,
        title_ru=raw_existing.title_ru, fetched_at=raw_existing.fetched_at,
    )
    session.add(sat)
    await session.commit()

    # Новая raw, мэтчится на ту же canonical
    raw_new = await _mk_raw(session, slug="myth-new", title_ru="Mythologies")
    _, candidates = await promo.match_candidates(session, raw_new.id, threshold=0.3)
    assert len(candidates) >= 1
    top = candidates[0]
    assert top["game_id"] == g.id
    assert top["has_satellite_for_provider"] is True


# ─── 3. promote link → alias + satellite ──────────────────────────────────────


async def test_promote_link_creates_alias_and_satellite(session: AsyncSession) -> None:
    g = await _mk_game(session, slug="myth", title="Mythologies")
    raw = await _mk_raw(
        session, slug="mythologies", title_ru="Mythologies",
        title_en="Mythologies", publisher="4GAMES",
        preorder_price=290000,                # 2900 руб
        external_links=[
            {"kind": "bgg", "url": "https://boardgamegeek.com/boardgame/447570/mythologies",
             "label": "Перейти на BGG", "external_id": "447570"},
            {"kind": "shop", "url": "https://4games.shop/mythologies/",
             "label": "На страницу предзаказа"},
        ],
    )

    result = await promo.promote(
        session, raw.id, action="link", target_game_id=g.id,
    )
    assert result["status"] == "promoted"
    assert result["game_id"] == g.id
    assert result["alias_id"] is not None
    assert result["satellite_id"] is not None

    # alias source='dicefest', verified=True
    alias = await session.get(GameAlias, result["alias_id"])
    assert alias is not None
    assert alias.source == "dicefest"
    assert alias.language == "ru"
    assert alias.verified is True
    assert alias.alias == "Mythologies"

    # satellite в game_dicefest — копируются publisher + новые поля PR-4
    sat = await session.get(GameDicefest, result["satellite_id"])
    assert sat is not None
    assert sat.publisher == "4GAMES"
    assert sat.preorder_price == 290000
    # external_links перенесены целиком (BGG + shop)
    sat_kinds = sorted(link["kind"] for link in sat.external_links)
    assert sat_kinds == ["bgg", "shop"]

    # raw статус
    raw_after = await session.get(DicefestRawGame, raw.id)
    assert raw_after is not None
    assert raw_after.status == "promoted"
    assert raw_after.promoted_to_game_id == g.id

    # log
    log = await session.get(ImportPromotionLog, result["log_id"])
    assert log is not None
    assert log.action == "link"
    assert log.satellite_created is True

    # Денормализация в games (миграция 0006): publisher / preorder_price /
    # dicefest_id / is_localized_ru / bgg_id из external_links.
    await session.refresh(g)
    assert g.ru_publisher == "4GAMES"
    assert g.preorder_price == 290000
    assert g.dicefest_id == raw.id
    assert g.is_localized_ru is True
    assert g.bgg_id == 447570       # извлечён из external_links


# ─── 4. promote create → new game + alias + satellite ────────────────────────


async def test_promote_create_creates_new_game(session: AsyncSession) -> None:
    raw = await _mk_raw(
        session, slug="newgame", title_ru="Новая Игра",
        publisher="4GAMES",
    )
    result = await promo.promote(
        session, raw.id, action="create",
    )
    assert result["game_id"] is not None
    g = await session.get(Game, result["game_id"])
    assert g is not None
    assert g.slug == "dicefest-newgame"
    assert g.title == "Новая Игра"
    # year НЕ выставляется при action='create' (PR-4): release_year убран,
    # т.к. соответствовал РФ-релизу. year заполнят последующие импортёры.
    assert g.year is None
    assert g.source == "dicefest"

    sat = await session.get(GameDicefest, result["satellite_id"])
    assert sat is not None
    assert sat.game_id == g.id


# ─── 5. idempotent on double click ───────────────────────────────────────────


async def test_promote_idempotent_on_double_click(session: AsyncSession) -> None:
    g = await _mk_game(session, slug="m", title="Mythologies")
    raw = await _mk_raw(session, slug="m1", title_ru="Mythologies")

    # Первый промоушен
    await promo.promote(session, raw.id, action="link", target_game_id=g.id)

    # Второй (имитируем двойной клик) — должен дать HTTPException 409
    with pytest.raises(HTTPException) as ei:
        await promo.promote(session, raw.id, action="link", target_game_id=g.id)
    assert ei.value.status_code == 409


# ─── 6. revert link undoes alias + satellite ─────────────────────────────────


async def test_revert_undoes_link(session: AsyncSession) -> None:
    g = await _mk_game(session, slug="m", title="Mythologies")
    raw = await _mk_raw(session, slug="m1", title_ru="Mythologies")

    res = await promo.promote(session, raw.id, action="link", target_game_id=g.id)
    log_id = res["log_id"]
    alias_id = res["alias_id"]
    satellite_id = res["satellite_id"]

    # revert
    revert_res = await promo.revert(session, log_id)
    assert revert_res["status_after_revert"] == "new"

    # alias удалён
    alias = await session.get(GameAlias, alias_id)
    assert alias is None

    # satellite удалён
    sat = await session.get(GameDicefest, satellite_id)
    assert sat is None

    # raw обратно в new
    raw_after = await session.get(DicefestRawGame, raw.id)
    assert raw_after.status == "new"
    assert raw_after.promoted_to_game_id is None

    # game НЕ удалён (action='link', не 'create')
    g_after = await session.get(Game, g.id)
    assert g_after is not None

    # log помечен reverted
    log = await session.get(ImportPromotionLog, log_id)
    assert log.reverted_at is not None


# ─── 7. revert after merge fails loudly ──────────────────────────────────────


async def test_revert_after_merge_fails_loudly(session: AsyncSession) -> None:
    g = await _mk_game(session, slug="m", title="Mythologies")
    raw = await _mk_raw(session, slug="m1", title_ru="Mythologies")

    res = await promo.promote(session, raw.id, action="link", target_game_id=g.id)
    log_id = res["log_id"]

    # Имитируем merge — game.status='merged'
    g.status = "merged"
    await session.commit()

    # revert должен упасть с 409
    with pytest.raises(HTTPException) as ei:
        await promo.revert(session, log_id)
    assert ei.value.status_code == 409
    assert "merged" in ei.value.detail.lower()


# ─── 8. revert не трогает offers.game_id ─────────────────────────────────────


async def test_revert_does_not_touch_offers(session: AsyncSession) -> None:
    g = await _mk_game(session, slug="m", title="Mythologies")
    raw = await _mk_raw(session, slug="m1", title_ru="Mythologies")

    # Создаём offer, прикреплённый к game
    offer = Offer(
        store_slug="hobbygames",
        external_id="123",
        title_raw="Mythologies (HG)",
        url="https://hobbygames.ru/g/123",
        game_id=g.id,
        match_status="auto",
        match_score=0.9,
    )
    session.add(offer)
    await session.commit()
    offer_id = offer.id

    res = await promo.promote(session, raw.id, action="link", target_game_id=g.id)
    await promo.revert(session, res["log_id"])

    # Offer всё ещё прикреплён к g.id
    offer_after = await session.get(Offer, offer_id)
    assert offer_after is not None
    assert offer_after.game_id == g.id   # explicit contract
    assert offer_after.match_status == "auto"


# ─── bonus: skip / reject ─────────────────────────────────────────────────────


async def test_promote_skip_just_changes_status(session: AsyncSession) -> None:
    raw = await _mk_raw(session, slug="x", title_ru="X")
    res = await promo.promote(session, raw.id, action="skip", notes="not interested")
    assert res["status"] == "skipped"
    assert res["alias_id"] is None
    assert res["satellite_id"] is None
    raw_after = await session.get(DicefestRawGame, raw.id)
    assert raw_after.status == "skipped"
    assert raw_after.notes == "not interested"


async def test_promote_reject_can_be_reverted(session: AsyncSession) -> None:
    raw = await _mk_raw(session, slug="x", title_ru="X")
    res = await promo.promote(session, raw.id, action="reject")
    revert_res = await promo.revert(session, res["log_id"])
    assert revert_res["status_after_revert"] == "new"


# ─── PR-5: batch auto-link ────────────────────────────────────────────────────


async def test_batch_link_dry_run_does_not_modify_state(session: AsyncSession) -> None:
    """dry_run=True не создаёт alias/satellite/log; raw.status остаётся 'new'."""
    g = await _mk_game(session, slug="myth", title="Mythologies")
    raw = await _mk_raw(session, slug="myth1", title_ru="Mythologies")

    res = await promo.batch_auto_link(
        session, threshold=0.95, max_items=10, dry_run=True,
    )
    assert res["scanned"] == 1
    assert res["linked"] == 0
    assert res["would_link"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["game_id"] == g.id

    # Никаких побочных эффектов
    raw_after = await session.get(DicefestRawGame, raw.id)
    assert raw_after.status == "new"
    aliases = (
        await session.execute(text("SELECT count(*) FROM game_aliases WHERE source='dicefest'"))
    ).scalar_one()
    assert aliases == 0
    satellites = (
        await session.execute(text("SELECT count(*) FROM game_dicefest"))
    ).scalar_one()
    assert satellites == 0
    logs = (
        await session.execute(text("SELECT count(*) FROM import_promotion_log"))
    ).scalar_one()
    assert logs == 0


async def test_batch_link_links_above_threshold_only(session: AsyncSession) -> None:
    """raw c score≥0.95 линкуется; raw с score<0.95 → skipped[reason='no_candidates']."""
    g_myth = await _mk_game(session, slug="myth", title="Mythologies")
    await _mk_game(session, slug="pandemic", title="Pandemic")
    # raw1 — точное совпадение → score=1.0 ≥0.95
    raw1 = await _mk_raw(session, slug="myth1", title_ru="Mythologies")
    # raw2 — что-то непохожее → ни одного кандидата ≥0.95
    raw2 = await _mk_raw(session, slug="weird", title_ru="Quantum Physics 42")

    res = await promo.batch_auto_link(
        session, threshold=0.95, max_items=10, dry_run=False,
    )
    assert res["scanned"] == 2
    assert res["linked"] == 1
    skipped_reasons = [s["reason"] for s in res["skipped"]]
    # Для raw2 либо 'no_candidates' (если pg_trgm % не находит ничего вообще),
    # либо 'low_score' (если нашёл, но ниже threshold).
    assert any(r in ("no_candidates", "low_score") for r in skipped_reasons)

    # raw1 действительно promoted → game_myth
    r1_after = await session.get(DicefestRawGame, raw1.id)
    assert r1_after.status == "promoted"
    assert r1_after.promoted_to_game_id == g_myth.id
    # raw2 остался new
    r2_after = await session.get(DicefestRawGame, raw2.id)
    assert r2_after.status == "new"


async def test_batch_link_skips_when_satellite_exists(session: AsyncSession) -> None:
    """Если у game уже есть satellite от dicefest — пропускаем (не подменяем)."""
    g = await _mk_game(session, slug="myth", title="Mythologies")
    raw_old = await _mk_raw(session, slug="myth-v1", title_ru="Mythologies")
    # Имитируем — этот raw уже промоушен и satellite на g существует
    sat = GameDicefest(
        game_id=g.id, raw_id=raw_old.id, slug=raw_old.slug,
        title_ru=raw_old.title_ru, fetched_at=raw_old.fetched_at,
    )
    session.add(sat)
    raw_old.status = "promoted"
    raw_old.promoted_to_game_id = g.id
    await session.commit()

    # Новый raw с тем же названием → top-1 будет та же game_id с has_satellite_for_provider=True
    raw_new = await _mk_raw(session, slug="myth-v2", title_ru="Mythologies")
    res = await promo.batch_auto_link(
        session, threshold=0.95, max_items=10, dry_run=False, skip_with_satellite=True,
    )
    # scanned=1 (только raw_new — у raw_old статус 'promoted', не 'new')
    assert res["scanned"] == 1
    assert res["linked"] == 0
    reasons = [s["reason"] for s in res["skipped"]]
    assert "already_linked" in reasons


async def test_batch_link_idempotent_on_rerun(session: AsyncSession) -> None:
    """Второй запуск не делает ничего — все promoted-raw уже не в 'new'."""
    g = await _mk_game(session, slug="myth", title="Mythologies")
    await _mk_raw(session, slug="myth1", title_ru="Mythologies")

    res1 = await promo.batch_auto_link(session, threshold=0.95, dry_run=False)
    assert res1["linked"] == 1
    assert g  # noqa: для линтера

    res2 = await promo.batch_auto_link(session, threshold=0.95, dry_run=False)
    assert res2["scanned"] == 0
    assert res2["linked"] == 0
    assert res2["would_link"] == 0


async def test_batch_link_writes_audit_with_auto_marker(session: AsyncSession) -> None:
    """import_promotion_log.notes начинается с 'auto-batch'."""
    await _mk_game(session, slug="myth", title="Mythologies")
    await _mk_raw(session, slug="myth1", title_ru="Mythologies")

    await promo.batch_auto_link(session, threshold=0.95, dry_run=False)

    log_notes = (
        await session.execute(text("SELECT notes FROM import_promotion_log ORDER BY id DESC LIMIT 1"))
    ).scalar_one()
    assert log_notes is not None and log_notes.startswith("auto-batch")
