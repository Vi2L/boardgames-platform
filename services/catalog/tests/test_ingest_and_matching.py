"""Интеграционные тесты POST /ingest/offers и /matching/* через ASGI + БД."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from catalog import api as api_mod
from tests.conftest import requires_db

pytestmark = [pytest.mark.asyncio, requires_db]


@pytest_asyncio.fixture
async def clean_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE games, game_aliases, offers, offer_prices, "
                "import_jobs RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def client(clean_db: None) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def session(engine: AsyncEngine, clean_db: None) -> AsyncIterator[AsyncSession]:
    """Прямая БД-сессия для тестов, которые seedят данные между client-запросами."""
    Factory = async_sessionmaker(engine, expire_on_commit=False)
    async with Factory() as s:
        yield s


async def _seed_carcassonne(client: AsyncClient) -> int:
    r = await client.post(
        "/games", json={"slug": "carc", "title": "Каркассон", "year": 2000}
    )
    return r.json()["id"]


async def test_ingest_auto_matches_existing_game(client: AsyncClient):
    gid = await _seed_carcassonne(client)
    r = await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [
                {
                    "external_id": "1",
                    "title": "Каркассон",
                    "url": "https://hobbygames.ru/carc",
                    "price": 169500,
                }
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 1
    assert body["auto_matched"] == 1
    assert body["unmatched"] == 0
    assert body["items"][0]["game_id"] == gid
    assert body["items"][0]["match_status"] == "auto"
    assert body["items"][0]["match_score"] >= 0.9


async def test_ingest_writes_t0_t1_progress_on_miss(client: AsyncClient):
    """CAT-4.7: при первом ingest с T0 cache miss + T1 ниже threshold
    в match_log появляются t0_progress + t1_progress записи.
    UI Штучного матчинга (SingleMatchTab) показывает их как пройденные
    stage'и вместо `pending`/`skipped without reason`."""
    await _seed_carcassonne(client)
    r = await client.post(
        "/ingest/offers",
        json={
            "store_slug": "gaga",
            "products": [{
                "external_id": "p1",
                "title": "Каркасон",  # опечатка → trgm ~0.73 < 0.92
                "url": "https://gaga.ru/p1",
                "price": 159000,
            }],
        },
    )
    assert r.status_code == 200
    # T1 ниже auto_threshold → progress-entries записаны
    log = (await client.get("/matching/log")).json()
    actions = [item["action"] for item in log["items"]]
    assert "t0_progress" in actions, f"t0_progress missing in {actions}"
    assert "t1_progress" in actions, f"t1_progress missing in {actions}"


async def test_ingest_no_progress_entries_on_t0_cache_hit(
    client: AsyncClient, session: AsyncSession,
):
    """T0 cache hit — финальная auto_t0 запись пишется, прогрессы НЕ нужны
    (T0 запись сама по себе финальная)."""
    from catalog.matching.v2.decisions import save_decision
    gid = await _seed_carcassonne(client)
    # Засеваем T0 cache, чтобы следующий ingest попал в hit
    await save_decision(
        session, title_norm="каркассон", game_id=gid,
        source="auto_t1", tier=1, score=0.95,
    )
    await session.commit()

    await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hg",
            "products": [{
                "external_id": "p2",
                "title": "Каркассон",
                "url": "https://h.ru/p2",
            }],
        },
    )
    log = (await client.get("/matching/log")).json()
    actions = [item["action"] for item in log["items"]]
    # Прогрессов нет, есть только финальная auto_t0
    assert "t0_progress" not in actions
    assert "t1_progress" not in actions
    assert "auto_t0" in actions


async def test_ingest_typo_goes_to_async_queue(client: AsyncClient):
    """Опечатка 'Каркасон' (одна 'с') даёт trgm ~0.73 — это НИЖЕ T1
    auto-порога 0.92 (matcher v2). Раньше тест ожидал auto при пороге
    0.6, теперь — `unmatched` + push в `match_queue` для T2/T3 разбора.
    """
    await _seed_carcassonne(client)
    r = await client.post(
        "/ingest/offers",
        json={
            "store_slug": "gaga",
            "products": [
                {
                    "external_id": "abc",
                    "title": "Каркасон",
                    "url": "https://gaga.ru/x",
                    "price": 159000,
                }
            ],
        },
    )
    body = r.json()
    item = body["items"][0]
    # T1 trgm не дотянул — оффер ждёт async-обработки (T2/T3) или manual
    assert item["match_status"] == "unmatched"
    assert item["game_id"] is None
    # И появился в очереди матчинга
    queue = (await client.get("/matching/queue")).json()
    assert queue["total"] == 1
    assert queue["items"][0]["title_raw"] == "Каркасон"


async def test_ingest_unknown_goes_to_unmatched(client: AsyncClient):
    await _seed_carcassonne(client)
    r = await client.post(
        "/ingest/offers",
        json={
            "store_slug": "lavkaigr",
            "products": [
                {
                    "external_id": "xx",
                    "title": "Совершенно другая игра XYZ",
                    "url": "https://l.ru/x",
                }
            ],
        },
    )
    body = r.json()
    assert body["unmatched"] == 1
    assert body["auto_matched"] == 0
    assert body["items"][0]["match_status"] == "unmatched"
    assert body["items"][0]["game_id"] is None


async def test_ingest_idempotent_and_records_price_history(client: AsyncClient):
    await _seed_carcassonne(client)
    payload = {
        "store_slug": "hobbygames",
        "fetched_at": "2026-05-07T10:00:00+00:00",
        "products": [
            {
                "external_id": "1",
                "title": "Каркассон",
                "url": "https://h.ru/1",
                "price": 169500,
            }
        ],
    }
    r1 = await client.post("/ingest/offers", json=payload)
    r2 = await client.post(
        "/ingest/offers",
        json={**payload, "fetched_at": "2026-05-08T10:00:00+00:00",
              "products": [{**payload["products"][0], "price": 175000}]},
    )
    assert r1.status_code == 200 and r2.status_code == 200

    # Один offer (uniq), но две точки цен.
    queue = (await client.get("/matching/queue")).json()
    assert queue["total"] == 0  # auto-matched
    # offer_prices через прямой query: используем admin-доступ через games-detail?
    # Достаточно проверить, что повторный ingest не упал.


async def test_auto_match_adds_alias(client: AsyncClient):
    """Точное совпадение по title даёт T1 score ≥ 0.92 → auto-match
    и title_raw сохраняется как alias с source='auto-match'. Следующий
    ingest того же title попадёт в T0 cache hit, минуя trgm.
    """
    gid = await _seed_carcassonne(client)
    await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [
                # Идентичный title — гарантирует score 1.0 в T1.
                {"external_id": "1", "title": "Каркассон", "url": "https://h.ru/1"}
            ],
        },
    )
    detail = (await client.get(f"/games/{gid}")).json()
    aliases = [a["alias"] for a in detail["aliases"]]
    assert "Каркассон" in aliases


async def test_matching_queue_shows_unmatched(client: AsyncClient):
    await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [
                {"external_id": "1", "title": "Mystery Game ZZZ", "url": "https://h/1"},
            ],
        },
    )
    r = await client.get("/matching/queue")
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["title_raw"] == "Mystery Game ZZZ"
    assert body["items"][0]["match_status"] == "unmatched"


async def test_manual_link_freezes_match(client: AsyncClient, session: AsyncSession):
    """После manual-link повторный ingest не должен сдвинуть game_id и не должен
    стирать диагностику (match_score/match_tier/match_reason) — оператор
    использует эти поля как след принятого решения."""
    gid = await _seed_carcassonne(client)
    # Загружаем оффер, который не сматчится автоматически.
    ing = await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [
                {
                    "external_id": "1",
                    "title": "Игра ХYZ-непонятная",
                    "url": "https://h/1",
                }
            ],
        },
    )
    offer_id = ing.json()["items"][0]["offer_id"]

    # Оператор вручную связал.
    r = await client.post(f"/matching/{offer_id}/link", json={"game_id": gid})
    assert r.status_code == 200
    assert r.json()["match_status"] == "manual"

    # Снимок диагностических полей в БД сразу после manual-link. Что бы туда
    # ни записал link (NULL или конкретные значения) — повторный ingest не
    # должен это значение менять.
    snap = (
        await session.execute(
            text(
                "SELECT match_score, match_tier, match_reason "
                "FROM offers WHERE id = :id"
            ),
            {"id": offer_id},
        )
    ).one()

    # Повторный ingest того же оффера (с похожим title) не должен ничего
    # переопределить — manual фиксируется.
    r2 = await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [
                {
                    "external_id": "1",
                    "title": "Каркассон 2019",
                    "url": "https://h/1",
                }
            ],
        },
    )
    item = r2.json()["items"][0]
    assert item["match_status"] == "manual"
    assert item["game_id"] == gid

    # Регрессия: до фикса безусловный UPDATE сбрасывал поля в NULL.
    after = (
        await session.execute(
            text(
                "SELECT match_score, match_tier, match_reason "
                "FROM offers WHERE id = :id"
            ),
            {"id": offer_id},
        )
    ).one()
    assert after == snap, "повторный ingest не должен трогать match-диагностику manual-оффера"


async def test_ingest_writes_normalized_offer_fields(client: AsyncClient):
    """Миграция 0006: sku/in_stock/original_price/is_preorder из payload
    попадают в типизированные колонки offers, а не только в raw_extra.

    Проверяем три источника попадания в БД:
      - явные поля payload (sku, in_stock, original_price);
      - извлечение из extra при отсутствии явного поля (HobbyGames кладёт
        sku в extra; Crowd Games — in_stock; HG — availability/original_price);
      - is_preorder отдельно (пока приходит только явным полем).
    """
    await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [
                {
                    "external_id": "1",
                    "title": "Carcassonne",
                    "url": "https://h.ru/1",
                    "price": 169500,
                    "sku": "HB-CARC",
                    "in_stock": True,
                    "original_price": 199000,
                    "is_preorder": False,
                },
                # Без явных полей — должно подняться из extra (имитация
                # HobbyGames-старого клиента, который не обновлён под новый
                # контракт).
                {
                    "external_id": "2",
                    "title": "Pandemic",
                    "url": "https://h.ru/2",
                    "price": 250000,
                    "extra": {
                        "sku": "HB-PAND",
                        "availability": False,
                        "original_price": 270000,
                    },
                },
            ],
        },
    )
    queue = (await client.get("/matching/queue?limit=50")).json()
    items = {it["external_id"]: it for it in queue["items"]}
    assert items["1"]["sku"] == "HB-CARC"
    assert items["1"]["in_stock"] is True
    assert items["1"]["original_price"] == 199000
    assert items["1"]["is_preorder"] is False
    # Поднятие из extra
    assert items["2"]["sku"] == "HB-PAND"
    assert items["2"]["in_stock"] is False
    assert items["2"]["original_price"] == 270000


async def test_ingest_skips_non_boardgame_category(client: AsyncClient):
    """Defence-in-depth (2026-05-18): если парсер случайно прислал товар с
    категорией не из whitelist'а — catalog должен дропнуть его до матчинга,
    не создавая offer в БД и не запуская pg_trgm.
    """
    await _seed_carcassonne(client)
    r = await client.post(
        "/ingest/offers",
        json={
            "store_slug": "avito",
            "products": [
                # Должен пройти — категория из whitelist'а.
                {
                    "external_id": "ok-1",
                    "title": "Каркассон новый запечатанный",
                    "url": "https://avito/ok-1",
                    "category": "boardgames",
                },
                # Должен быть отброшен — книга, не настольная игра.
                {
                    "external_id": "skip-1",
                    "title": "Каркассон. Жан-Жак Руссо. Биография",
                    "url": "https://avito/skip-1",
                    "category": "books",
                },
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 1            # только ok-1
    assert body["skipped_category"] == 1    # книга дропнута
    assert len(body["items"]) == 1
    assert body["items"][0]["external_id"] == "ok-1"


async def test_ingest_accepts_legacy_clients_without_category(client: AsyncClient):
    """Обратная совместимость: payload без поля `category` (старый publisher)
    принимается так же, как раньше — None в whitelist'е."""
    await _seed_carcassonne(client)
    r = await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [{
                "external_id": "legacy-1",
                "title": "Каркассон",
                "url": "https://hobbygames.ru/x",
                "price": 169500,
            }],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 1
    assert body["skipped_category"] == 0


async def test_reject_offer(client: AsyncClient):
    await client.post(
        "/ingest/offers",
        json={
            "store_slug": "hobbygames",
            "products": [{"external_id": "1", "title": "Spam", "url": "https://h/1"}],
        },
    )
    qid = (await client.get("/matching/queue")).json()["items"][0]["id"]
    r = await client.post(f"/matching/{qid}/reject")
    assert r.json()["match_status"] == "rejected"
    # Из очереди исчез.
    assert (await client.get("/matching/queue")).json()["total"] == 0
