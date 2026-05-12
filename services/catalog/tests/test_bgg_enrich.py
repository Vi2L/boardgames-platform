"""Тесты этапа 2 BGG-парсера: client.fetch_things, service.enrich_batch.

Слои:
- `_parse_things_xml` (pure) — статичная фикстура с двумя `<item>`.
- `BggClient.fetch_things` — `httpx.MockTransport` подменяет ответ.
- `enrich_batch` — оркестрация без БД (dry_run + monkeypatch на отбор
  кандидатов). БД-зависимые тесты upsert'а вынесены отдельно с
  `@requires_db`.

Без сети, без БД для основной массы — быстро в CI.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from catalog.parsers.bgg import BggClient
from catalog.parsers.bgg.client import THING_BATCH_MAX
from catalog.parsers.bgg.service import (
    EnrichStats,
    _parse_things_xml,
    enrich_batch,
)

FIXTURE_BATCH = Path(__file__).parent / "fixtures" / "bgg_things_batch.xml"
FIXTURE_THING = Path(__file__).parent / "fixtures" / "bgg_carcassonne.xml"


# ---------- pure: _parse_things_xml ----------

def test_parse_things_xml_returns_all_items():
    """_parse_things_xml возвращает list[tuple[BggGame, sub_xml]] — sub_xml
    нужен для raw.xml в upsert_bgg_data (CAT-7)."""
    xml = FIXTURE_BATCH.read_text(encoding="utf-8")
    entries = _parse_things_xml(xml)
    assert len(entries) == 2
    bgg_ids = sorted(g.bgg_id for g, _ in entries)
    assert bgg_ids == [13, 822]
    titles = {g.title for g, _ in entries}
    assert titles == {"Carcassonne", "Catan"}
    # sub_xml — корректный XML c одним item (потребляется upsert'ом).
    for _bgg, sub_xml in entries:
        assert "<item" in sub_xml


def test_parse_things_xml_empty():
    entries = _parse_things_xml('<?xml version="1.0"?><items/>')
    assert entries == []


def test_parse_things_xml_preserves_aliases():
    xml = FIXTURE_BATCH.read_text(encoding="utf-8")
    entries = _parse_things_xml(xml)
    carc = next(g for g, _ in entries if g.bgg_id == 822)
    assert "Каркассон" in carc.aliases
    catan = next(g for g, _ in entries if g.bgg_id == 13)
    assert "The Settlers of Catan" in catan.aliases


# ---------- client.fetch_things ----------

@pytest.mark.asyncio
async def test_client_fetch_things_passes_comma_separated_ids():
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        return httpx.Response(200, text=FIXTURE_BATCH.read_text(encoding="utf-8"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            await bgg.fetch_things([822, 13])

    req = captured["req"]
    assert req.url.path == "/xmlapi2/thing"
    assert req.url.params["id"] == "822,13"
    assert req.url.params["stats"] == "1"


@pytest.mark.asyncio
async def test_client_fetch_things_empty_list_raises():
    async with BggClient() as bgg:
        with pytest.raises(ValueError):
            await bgg.fetch_things([])


@pytest.mark.asyncio
async def test_client_fetch_things_over_limit_raises():
    """Больше 20 ID должно ронять с понятной ошибкой — caller обязан разбить сам."""
    too_many = list(range(THING_BATCH_MAX + 1))
    async with BggClient() as bgg:
        with pytest.raises(ValueError, match="batch"):
            await bgg.fetch_things(too_many)


@pytest.mark.asyncio
async def test_client_fetch_things_handles_202_then_200():
    """202 Accepted → backoff → 200 — стандартный паттерн BGG для batch'а тоже."""
    fixture = FIXTURE_BATCH.read_text(encoding="utf-8")
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(202, text="queued")
        return httpx.Response(200, text=fixture)

    # Ускоряем тест: подменяем backoff'ы.
    import catalog.parsers.bgg.client as client_mod
    original = client_mod._RETRY_DELAYS
    client_mod._RETRY_DELAYS = (0.0, 0.0, 0.0, 0.0)
    try:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            async with BggClient(client=http) as bgg:
                xml = await bgg.fetch_things([822, 13])
    finally:
        client_mod._RETRY_DELAYS = original

    assert call_count["n"] == 2
    assert "Carcassonne" in xml and "Catan" in xml


# ---------- service.enrich_batch (dry_run, без БД) ----------


def _stub_select_candidates(ids: list[int]):
    """Хелпер: monkeypatch для `_select_enrich_candidates`, чтобы не ходить в БД."""

    async def _stub(session, *, rank_le, skip_recent_days, limit):
        return list(ids)

    return _stub


@pytest.mark.asyncio
async def test_enrich_batch_dry_run_no_db_writes(monkeypatch):
    """dry_run=True: HTTP идёт, но в БД ничего не пишем — проверяем счётчики."""
    import catalog.parsers.bgg.service as svc

    # Подменяем кандидаты — 2 ID, оба будут найдены в фикстуре.
    monkeypatch.setattr(svc, "_select_enrich_candidates", _stub_select_candidates([822, 13]))

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, text=FIXTURE_BATCH.read_text(encoding="utf-8"))
    )
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            stats = await enrich_batch(
                rank_le=1000,
                batch_size=20,
                skip_recent_days=30,
                dry_run=True,
                rate_limit_sec=0.0,
                client=bgg,
                # session_factory не нужен в dry_run, но _select_enrich_candidates
                # открывает session — даём заглушку, которая не пытается коннектиться.
                session_factory=_DummySessionFactory(),
            )

    assert stats.enriched == 2
    assert stats.skipped == 0
    assert stats.failed == 0


@pytest.mark.asyncio
async def test_enrich_batch_splits_into_chunks(monkeypatch):
    """25 ID → 2 запроса (20 + 5). Считаем количество HTTP-вызовов."""
    import catalog.parsers.bgg.service as svc

    fake_ids = list(range(1, 26))  # 25 штук
    monkeypatch.setattr(svc, "_select_enrich_candidates", _stub_select_candidates(fake_ids))

    request_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        ids_in_req = request.url.params["id"].split(",")
        # Возвращаем фикстуру; для теста важно лишь количество вызовов.
        # `enrich_batch` корректно посчитает skipped для тех ID, которые нет в ответе.
        return httpx.Response(200, text=FIXTURE_BATCH.read_text(encoding="utf-8"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            stats = await enrich_batch(
                rank_le=1000,
                batch_size=20,
                skip_recent_days=30,
                dry_run=True,
                rate_limit_sec=0.0,
                client=bgg,
                session_factory=_DummySessionFactory(),
            )

    assert request_count["n"] == 2  # 20 + 5
    # 25 кандидатов, в каждом ответе 2 «найдены» (822, 13). Запросы по 20+5
    # шли с другими ID — поэтому большинство будут skipped (нет в ответе).
    assert stats.enriched + stats.skipped + stats.failed == 25


@pytest.mark.asyncio
async def test_enrich_batch_5xx_marks_all_in_chunk_as_failed(monkeypatch):
    """503 от BGG для batch'а → весь chunk идёт в errors, прогон продолжается."""
    import catalog.parsers.bgg.service as svc

    fake_ids = [101, 102, 103]
    monkeypatch.setattr(svc, "_select_enrich_candidates", _stub_select_candidates(fake_ids))

    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="boom"))
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            stats = await enrich_batch(
                rank_le=1000,
                batch_size=20,
                skip_recent_days=30,
                dry_run=True,
                rate_limit_sec=0.0,
                client=bgg,
                session_factory=_DummySessionFactory(),
            )

    assert stats.failed == 3
    assert stats.enriched == 0
    assert len(stats.errors) == 3
    assert {e["bgg_id"] for e in stats.errors} == {101, 102, 103}


@pytest.mark.asyncio
async def test_enrich_batch_invalid_batch_size():
    with pytest.raises(ValueError, match="batch_size"):
        await enrich_batch(rank_le=10, batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        await enrich_batch(rank_le=10, batch_size=THING_BATCH_MAX + 1)


@pytest.mark.asyncio
async def test_enrich_batch_no_candidates(monkeypatch):
    """Пустой список кандидатов — функция возвращает пустую статистику без HTTP."""
    import catalog.parsers.bgg.service as svc

    monkeypatch.setattr(svc, "_select_enrich_candidates", _stub_select_candidates([]))

    request_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(200, text='<?xml version="1.0"?><items/>')

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            stats = await enrich_batch(
                rank_le=10,
                client=bgg,
                rate_limit_sec=0.0,
                session_factory=_DummySessionFactory(),
            )

    assert request_count["n"] == 0  # ни одного запроса
    assert stats.to_dict() == {"enriched": 0, "skipped": 0, "failed": 0, "errors": []}


@pytest.mark.asyncio
async def test_enrich_batch_progress_callback(monkeypatch):
    """progress_cb вызывается для каждой обработанной игры."""
    import catalog.parsers.bgg.service as svc

    monkeypatch.setattr(svc, "_select_enrich_candidates", _stub_select_candidates([822, 13]))

    events: list[tuple[int, int, int | None]] = []

    async def cb(i: int, total: int, bgg) -> None:
        events.append((i, total, bgg.bgg_id if bgg else None))

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, text=FIXTURE_BATCH.read_text(encoding="utf-8"))
    )
    async with httpx.AsyncClient(transport=transport) as http:
        async with BggClient(client=http) as bgg:
            await enrich_batch(
                rank_le=1000,
                dry_run=True,
                rate_limit_sec=0.0,
                progress_cb=cb,
                client=bgg,
                session_factory=_DummySessionFactory(),
            )

    assert len(events) == 2
    assert [e[0] for e in events] == [1, 2]
    assert all(e[1] == 2 for e in events)
    assert {e[2] for e in events} == {13, 822}


# ---------- helpers ----------


class _DummySessionFactory:
    """Stub для session_factory: открывает «сессию», которая ничего не делает.

    Используется в dry_run-тестах, где `_select_enrich_candidates` подменена
    monkeypatch'ем и реальные SQL-запросы не идут. Достаточно, чтобы async-CM
    не падал.
    """

    def __call__(self) -> "_DummySession":
        return _DummySession()


class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def execute(self, *args, **kwargs):  # pragma: no cover — не зовётся в dry_run
        raise AssertionError("DummySession.execute() called — должен быть dry_run")

    async def commit(self):  # pragma: no cover
        raise AssertionError("DummySession.commit() called — должен быть dry_run")


def test_enrich_stats_to_dict_truncates_errors():
    stats = EnrichStats()
    for i in range(100):
        stats.errors.append({"bgg_id": i, "error": "x"})
    d = stats.to_dict()
    assert len(d["errors"]) == 50
