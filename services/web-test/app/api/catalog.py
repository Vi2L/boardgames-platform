"""Прокси к boardgames-catalog для UI ручного матчинга.

Все эндпоинты живут под /api/catalog. Контракт идентичен upstream'у — мы
лишь форвардим запросы, чтобы фронту не нужно было ходить cross-origin.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.matching_queue(store=store, limit=limit, offset=offset)
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


@router.post("/import/tesera")
async def import_tesera(
    body: dict,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict:
    try:
        return await client.import_tesera(body)
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
