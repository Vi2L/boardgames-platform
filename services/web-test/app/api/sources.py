"""Прокси к /sources/* эндпоинтам catalog'а.

Всё под /api/sources. Контракт идентичен upstream'у — это тонкий форвард,
чтобы фронту не нужно было ходить cross-origin и держать `X-API-Key`.

Покрывает:
  - detection runs: запуск/листинг/просмотр/apply/discard
  - match profiles: CRUD сохранённых конфигов матчинга
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.catalog_client import CatalogClient, CatalogServiceError
from app.deps import get_catalog_client

router = APIRouter(prefix="/sources", tags=["sources"])


# ─── Detection runs ───────────────────────────────────────────────────────────


@router.post("/{provider}/runs")
async def start_run(
    provider: str,
    payload: dict[str, Any],
    client: CatalogClient = Depends(get_catalog_client),
) -> dict[str, Any]:
    """Запустить сухой прогон. Возвращается run сразу с status='running' —
    UI начинает polling до status='ready'/'failed'."""
    try:
        return await client.start_source_run(provider, payload)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/{provider}/runs")
async def list_runs(
    provider: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict[str, Any]:
    try:
        return await client.list_source_runs(provider, limit=limit, offset=offset)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/{provider}/runs/{run_id}")
async def get_run(
    provider: str,
    run_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict[str, Any]:
    try:
        return await client.get_source_run(provider, run_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/{provider}/runs/{run_id}/items")
async def list_run_items(
    provider: str,
    run_id: int,
    change_type: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict[str, Any]:
    try:
        return await client.list_source_run_items(
            provider,
            run_id,
            change_type=change_type,
            search=search,
            limit=limit,
            offset=offset,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/{provider}/runs/{run_id}/apply")
async def apply_run(
    provider: str,
    run_id: int,
    payload: dict[str, Any],
    client: CatalogClient = Depends(get_catalog_client),
) -> dict[str, Any]:
    try:
        return await client.apply_source_run(provider, run_id, payload)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/{provider}/runs/{run_id}/discard")
async def discard_run(
    provider: str,
    run_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> dict[str, Any]:
    try:
        return await client.discard_source_run(provider, run_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ─── Match profiles ───────────────────────────────────────────────────────────


@router.get("/{provider}/match-profiles")
async def list_match_profiles(
    provider: str,
    client: CatalogClient = Depends(get_catalog_client),
) -> list[dict[str, Any]]:
    try:
        return await client.list_match_profiles(provider)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/{provider}/match-profiles")
async def upsert_match_profile(
    provider: str,
    payload: dict[str, Any],
    client: CatalogClient = Depends(get_catalog_client),
) -> dict[str, Any]:
    try:
        return await client.upsert_match_profile(provider, payload)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.delete("/{provider}/match-profiles/{profile_id}", status_code=204)
async def delete_match_profile(
    provider: str,
    profile_id: int,
    client: CatalogClient = Depends(get_catalog_client),
) -> None:
    try:
        await client.delete_match_profile(provider, profile_id)
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


# ─── Promotion candidates с MatchParams ───────────────────────────────────────


@router.get("/{provider}/promotion/{raw_id}/candidates")
async def promotion_candidates_with_params(
    provider: str,
    raw_id: int,
    threshold: float = Query(0.5, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=20),
    prefer_external_id: bool = Query(False),
    weight_ru: float = Query(1.0, ge=0.0, le=2.0),
    weight_en: float = Query(1.0, ge=0.0, le=2.0),
    weight_alias: float = Query(1.0, ge=0.0, le=2.0),
    client: CatalogClient = Depends(get_catalog_client),
) -> dict[str, Any]:
    """Кандидаты с настраиваемыми параметрами матчинга.

    Дублирует /api/catalog/promotion/{provider}/{raw_id}/candidates, но
    плоско прокидывает MatchParams в query. UI MatchParamsForm зовёт
    эту ручку.
    """
    try:
        return await client.promotion_candidates_with_params(
            provider,
            raw_id,
            threshold=threshold,
            limit=limit,
            prefer_external_id=prefer_external_id,
            weight_ru=weight_ru,
            weight_en=weight_en,
            weight_alias=weight_alias,
        )
    except CatalogServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
