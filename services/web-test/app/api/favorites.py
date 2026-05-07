"""CRUD сохранённых поисковых запросов."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.db_local import PortalDB, get_portal_db
from app.schemas import FavoriteIn, FavoriteOut

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.post("", response_model=FavoriteOut)
async def create_favorite(
    payload: FavoriteIn,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> FavoriteOut:
    preset: dict | None = None
    if payload.show_out_of_stock is not None or payload.loyalty is not None:
        preset = {
            "show_out_of_stock": payload.show_out_of_stock,
            "loyalty": payload.loyalty,
        }
    fid = await db.create_favorite(
        query=payload.query, stores=payload.stores,
        limit_n=payload.limit, refresh=payload.refresh,
        preset=preset,
    )
    items = await db.list_favorites()
    item = next((f for f in items if f["id"] == fid), None)
    assert item is not None
    return FavoriteOut(**item)


@router.get("", response_model=list[FavoriteOut])
async def list_favorites(
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> list[FavoriteOut]:
    return [FavoriteOut(**f) for f in await db.list_favorites()]


@router.delete("/{favorite_id}")
async def delete_favorite(
    favorite_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> dict:
    deleted = await db.delete_favorite(favorite_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Favorite не найден")
    return {"deleted": True, "id": favorite_id}
