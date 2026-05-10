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
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.list_games(q=q, limit=limit, offset=offset)
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
