"""Прокси к boardgames-catalog для UI ручного матчинга.

Все эндпоинты живут под /api/catalog. Контракт идентичен upstream'у — мы
лишь форвардим запросы, чтобы фронту не нужно было ходить cross-origin.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.catalog_client import CatalogClient, CatalogServiceError
from app.deps import get_catalog_client

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/health")
async def catalog_health(
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.health()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"catalog unreachable: {e}") from e


@router.get("/games")
async def list_games(
    q: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    no_bgg: bool = Query(False, description="только игры без bgg_id"),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.list_games(q=q, limit=limit, offset=offset, no_bgg=no_bgg)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/games/{game_id}")
async def get_game(
    game_id: int, client: CatalogClient = Depends(get_catalog_client)
) -> dict:
    try:
        return await client.get_game(game_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/games/{game_id}/offers")
async def list_game_offers(
    game_id: int, client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Все offers, связанные с игрой — для drawer-таба «Offers»."""
    try:
        return await client.list_game_offers(game_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/games/{game_id}/children")
async def list_game_children(
    game_id: int, client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Игры с parent_game_id=game_id (допы/промо/аксессуары базы)."""
    try:
        return await client.list_game_children(game_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/matching/stats")
async def matching_stats(
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.matching_stats()
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/matching/candidates")
async def match_candidates(
    title: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Топ-N матчинговых кандидатов c score."""
    try:
        return await client.match_candidates(title, limit=limit)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/matching/queue")
async def matching_queue(
    store: str | None = Query(None),
    was_linked: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.matching_queue(
            store=store, was_linked=was_linked, limit=limit, offset=offset
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/{offer_id}/link")
async def link_offer(
    offer_id: int,
    body: dict,  # {"game_id": int}
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    game_id = body.get("game_id")
    if not isinstance(game_id, int):
        raise HTTPException(status_code=400, detail="game_id (int) required")
    try:
        return await client.link_offer(offer_id, game_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/{offer_id}/unlink")
async def unlink_offer(
    offer_id: int, client: CatalogClient = Depends(get_catalog_client)
) -> dict:
    try:
        return await client.unlink_offer(offer_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/{offer_id}/reject")
async def reject_offer(
    offer_id: int, client: CatalogClient = Depends(get_catalog_client)
) -> dict:
    try:
        return await client.reject_offer(offer_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/{offer_id}/reassess")
async def reassess_offer(
    offer_id: int, client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.reassess_offer(offer_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/reassess-all")
async def reassess_all(
    store: str | None = Query(None),
    max_score: float | None = Query(None),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.reassess_all(store=store, max_score=max_score)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ── Game CRUD (manual create / edit) ───────────────────────────────────────


@router.post("/games/merge")
async def merge_games(
    body: dict,  # {source_id, target_id}
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    sid = body.get("source_id")
    tid = body.get("target_id")
    if not isinstance(sid, int) or not isinstance(tid, int):
        raise HTTPException(status_code=400, detail="source_id и target_id (int) required")
    try:
        return await client.merge_games(sid, tid)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/games")
async def create_game(
    body: dict,  # GameCreate-совместимый payload (slug + title обязательны)
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    if not isinstance(body.get("slug"), str) or not body["slug"].strip():
        raise HTTPException(status_code=400, detail="slug required")
    if not isinstance(body.get("title"), str) or not body["title"].strip():
        raise HTTPException(status_code=400, detail="title required")
    try:
        return await client.create_game(body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.patch("/games/{game_id}")
async def patch_game(
    game_id: int,
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.patch_game(game_id, body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ── Imports (BGG / Tesera) ─────────────────────────────────────────────────


@router.post("/import/bgg")
async def import_bgg(
    body: dict,  # {bgg_id?: int, ids?: int[], wait?: bool} — wait игнорируем
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Запуск async-импорта BGG. Возвращает ImportJob — затем polling /jobs/{id}."""
    try:
        return await client.import_bgg(body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/parsers/bgg/search")
async def bgg_search(
    body: dict,  # {query: str, exact?: bool, limit?: int}
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Поиск игр в BGG XML API (proxy → catalog `/parsers/bgg/search`).

    Без побочных эффектов в БД — UI показывает кандидатов, оператор кликает
    «Import» → `/catalog/import/bgg` для одной игры или `/import/bgg/batch`
    для массового обогащения.
    """
    try:
        return await client.bgg_search(
            query=body.get("query", ""),
            exact=body.get("exact", False),
            limit=body.get("limit", 20),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/import/bgg/batch")
async def import_bgg_batch(
    body: dict,  # {rank_le?: int, all_ranked?: bool, batch_size?, skip_recent_days?, ...}
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Запуск batch BGG XML enrich'а. Возвращает ImportJob — polling /jobs/{id}."""
    try:
        return await client.import_bgg_batch(body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/import/bgg/ranks")
async def import_bgg_ranks(
    csv_file: UploadFile = File(...),
    top_n: int | None = Form(None),
    dry_run: bool = Form(False),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Seed каталога из BGG ranks CSV. Multipart/form-data → proxy → catalog.

    Возвращает ImportJob — polling через GET /catalog/import/jobs/{id}.
    """
    try:
        content = await csv_file.read()
        return await client.import_bgg_ranks(
            content,
            csv_file.filename or "boardgames_ranks.csv",
            top_n=top_n,
            dry_run=dry_run,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/import/tesera")
async def import_tesera(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.import_tesera(body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/import/dicefest")
async def import_dicefest(
    body: dict,  # {max_items?: int, only_year?: int}
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Запуск парсера dicefest.ru. Пишет в staging dicefest_raw_games (PR-1)."""
    try:
        return await client.import_dicefest(body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/import/dicefest/reparse")
async def import_dicefest_reparse(
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Re-parse сохранённого raw_html (PR-4): без HTTP к dicefest.ru."""
    try:
        return await client.import_dicefest_reparse()
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ── Promotion (PR-2/PR-3) ──────────────────────────────────────────────────


@router.get("/promotion/{provider}/queue")
async def promotion_queue(
    provider: str,
    status: str = Query("new"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.promotion_queue(
            provider, status=status, limit=limit, offset=offset,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/promotion/{provider}/{raw_id:int}")
async def promotion_get_raw(
    provider: str, raw_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.promotion_get_raw(provider, raw_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/promotion/{provider}/{raw_id:int}/candidates")
async def promotion_candidates(
    provider: str, raw_id: int,
    threshold: float = Query(0.5, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=20),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.promotion_candidates(
            provider, raw_id, threshold=threshold, limit=limit,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/promotion/{provider}/batch-link")
async def promotion_batch_link(
    provider: str, body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Batch auto-link уверенных совпадений (PR-5).

    body: {threshold?: 0.95, max_items?: 100, dry_run?: true, skip_with_satellite?: true}
    """
    try:
        return await client.promotion_batch_link(provider, body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/promotion/{provider}/{raw_id:int}/apply")
async def promotion_apply(
    provider: str, raw_id: int, body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.promotion_apply(provider, raw_id, body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/promotion/log/{log_id:int}/revert")
async def promotion_revert(
    log_id: int, body: dict | None = None,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.promotion_revert(log_id, body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/promotion/log")
async def promotion_log(
    provider: str | None = Query(None),
    game_id: int | None = Query(
        None, description="фильтр по game_id (для audit-таба drawer)",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.promotion_log(
            provider=provider, game_id=game_id, limit=limit, offset=offset,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/promotion/log/{log_id:int}/details")
async def promotion_log_details(
    log_id: int, client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.promotion_log_details(log_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/import/jobs/{job_id}")
async def get_import_job(
    job_id: int, client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.get_import_job(job_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ── Aliases CRUD ───────────────────────────────────────────────────────────


@router.post("/games/{game_id}/aliases")
async def add_alias(
    game_id: int,
    body: dict,  # {alias, source?, language?, verified?}
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    if not isinstance(body.get("alias"), str) or not body["alias"].strip():
        raise HTTPException(status_code=400, detail="alias (str) required")
    try:
        return await client.add_alias(game_id, body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.patch("/games/{game_id}/aliases/{alias_id}")
async def patch_alias(
    game_id: int,
    alias_id: int,
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.patch_alias(game_id, alias_id, body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.delete("/games/{game_id}/aliases/{alias_id}", status_code=204)
async def delete_alias(
    game_id: int,
    alias_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> None:
    try:
        await client.delete_alias(game_id, alias_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ── Matcher v2 proxy ──────────────────────────────────────────────────────


@router.get("/matching/ml-status")
async def get_ml_status(
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Состояние Ollama моделей + queue counts. Для UI MlStatusBadge."""
    try:
        return await client.ml_status()
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/matching/log")
async def get_match_log(
    offer_id: int | None = Query(None),
    action: str | None = Query(None),
    tier: int | None = Query(None, ge=0, le=3),
    performed_by: str | None = Query(None),
    only_active: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.match_log(
            offer_id=offer_id, action=action, tier=tier,
            performed_by=performed_by, only_active=only_active,
            limit=limit, offset=offset,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/log/{log_id}/revert")
async def revert_match_log_one(
    log_id: int,
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.revert_match_log(
            log_id, delete_alias=body.get("delete_alias", False),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/log/bulk-revert")
async def bulk_revert_match_log(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.bulk_revert_match_log(
            log_ids=body.get("log_ids", []),
            delete_alias=body.get("delete_alias", False),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/log/batch-revert")
async def batch_revert_match_log(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.batch_revert_match_log(
            batch_id=body["batch_id"],
            delete_alias=body.get("delete_alias", False),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/lookup-batch")
async def lookup_batch(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """WT-F11: batch резолв game_id для SearchPage группировки.

    Принимает `{items: [{title, store_slug?}], include_related_offers?: bool}`,
    возвращает `{matches, games[].related_offers}`. Прозрачный proxy к catalog.
    """
    try:
        return await client.lookup_batch(
            items=body.get("items", []),
            include_related_offers=body.get("include_related_offers", True),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.delete("/matching/decisions/{title_norm}")
async def invalidate_decision(
    title_norm: str,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Точечная инвалидация Tier 0 кэша (CAT-12). Используется в MatchLog UI."""
    try:
        return await client.invalidate_decision(title_norm)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/decisions/invalidate")
async def invalidate_decisions_bulk(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Bulk-инвалидация: ILIKE %title_contains% и/или only_negative."""
    try:
        return await client.invalidate_decisions_bulk(
            title_contains=body.get("title_contains"),
            only_negative=body.get("only_negative", False),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/warmup-embeddings")
async def warmup_embeddings(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Запуск warmup в фоне. Возвращает {job_id, status}; UI polls /import/jobs/{id}."""
    try:
        return await client.warmup_embeddings(
            batch_size=body.get("batch_size", 32),
            limit=body.get("limit"),
            only_games=body.get("only_games", False),
            only_aliases=body.get("only_aliases", False),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ─── /matching admin panel (UI WT-F11) ───────────────────────────────────────

@router.get("/admin/runtime-flags/{key}")
async def get_runtime_flag(
    key: str,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Текущее состояние bool-флага (kill-switch ml_enabled и т.д.)."""
    try:
        return await client.get_runtime_flag(key)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.patch("/admin/runtime-flags/{key}")
async def set_runtime_flag(
    key: str,
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Обновить bool-флаг. Body: {"value": bool}. Без рестарта (TTL ≤ 5с)."""
    value = body.get("value")
    if not isinstance(value, bool):
        raise HTTPException(status_code=400, detail="body.value должно быть bool")
    try:
        return await client.set_runtime_flag(key, value)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/matching/queue/skipped")
async def list_skipped_queue(
    store_slug: list[str] = Query(default_factory=list),
    reason: list[str] = Query(default_factory=list),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Список skipped match_queue с фильтрами и breakdown по store/reason."""
    try:
        return await client.list_skipped_queue(
            store_slug=store_slug or None,
            reason=reason or None,
            limit=limit, offset=offset,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/queue/re-enqueue-skipped")
async def re_enqueue_skipped(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Возвращает skipped → pending. Body: {offer_ids?, store_slug?, reason?}."""
    try:
        return await client.re_enqueue_skipped(
            offer_ids=body.get("offer_ids"),
            store_slug=body.get("store_slug"),
            reason=body.get("reason"),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/{offer_id}/run-v2")
async def run_v2_on_offer(
    offer_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Точечный enqueue в очередь с priority=10. Воркер обработает следующим тиком."""
    try:
        return await client.run_v2_on_offer(offer_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ВАЖНО: `/matching/offers/search` декларируется ДО `/matching/offers/{offer_id}` —
# иначе FastAPI попытается парсить строку "search" как int.
@router.get("/matching/offers/search")
async def search_offers(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Fuzzy lookup offers по подстроке title (для UI поиска)."""
    try:
        return await client.search_offers(q, limit=limit)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/matching/offers/{offer_id}")
async def lookup_offer(
    offer_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Lookup одного offer с match-полями (для штучного матчинга)."""
    try:
        return await client.lookup_offer(offer_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ─── Scheduler proxy (для UI /matching → Контроль → match_worker) ────────────

@router.get("/scheduler/jobs")
async def list_scheduler_jobs(
    client: CatalogClient = Depends(get_catalog_client),
) -> list[dict]:
    """Все scheduler-job'ы (для UI карточки match_worker)."""
    try:
        return await client.list_scheduler_jobs()
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/scheduler/jobs/{job_id}/trigger")
async def trigger_scheduler_job(
    job_id: str,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Ручной trigger job'а. Работает для cron- и interval-job'ов (после фикса 2026-05-16)."""
    try:
        return await client.trigger_scheduler_job(job_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.patch("/scheduler/jobs/{job_id}")
async def reschedule_job(
    job_id: str,
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Hot-reload расписания. Body: {cron_expr?, enabled?, params?}."""
    try:
        return await client.reschedule_job(
            job_id,
            cron_expr=body.get("cron_expr"),
            enabled=body.get("enabled"),
            params=body.get("params"),
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ─── Matcher v2 UX-improvements proxy (handoff §A/§C/§D/§E) ──────────────────

@router.get("/matching/queue/depth")
async def queue_depth_history(
    range_hours: int = Query(24, ge=1, le=24 * 7),
    bucket_minutes: int = Query(60, ge=1, le=60 * 24),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Sparkline-данные глубины очереди — для UI header."""
    try:
        return await client.queue_depth_history(
            range_hours=range_hours, bucket_minutes=bucket_minutes,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/matching/queue/{queue_id}")
async def lookup_queue_item(
    queue_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Детали одной queue-записи + position_in_pending для UI Штучного."""
    try:
        return await client.lookup_queue_item(queue_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.delete("/matching/queue/{queue_id}")
async def cancel_queue_item(
    queue_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Отменить pending-запись. 409 если processing/done."""
    try:
        return await client.cancel_queue_item(queue_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/matching/ml-models/{name}/probe")
async def force_probe_model(
    name: str,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    """Force probe модели — закрывает цепь немедленно если Ollama жив."""
    try:
        return await client.force_probe_model(name)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ─── Auto-recovery rules proxy (handoff §D) ──────────────────────────────────

@router.get("/admin/auto-recovery-rules")
async def list_auto_recovery_rules(
    client: CatalogClient = Depends(get_catalog_client),
) -> list[dict]:
    try:
        return await client.list_auto_recovery_rules()
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/admin/auto-recovery-rules")
async def create_auto_recovery_rule(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.create_auto_recovery_rule(body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.patch("/admin/auto-recovery-rules/{rule_id}")
async def update_auto_recovery_rule(
    rule_id: int,
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.update_auto_recovery_rule(rule_id, body)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.delete("/admin/auto-recovery-rules/{rule_id}", status_code=204)
async def delete_auto_recovery_rule(
    rule_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> None:
    try:
        await client.delete_auto_recovery_rule(rule_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
