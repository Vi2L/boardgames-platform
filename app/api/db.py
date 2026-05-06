"""Эндпоинты локальной БД портала.

Источник данных — `data/portal.sqlite` (см. app/db_local.py), который
накапливает результаты search-запросов, прошедших через сам портал.

Это НЕ зеркало БД parsers — у parsers полный кеш всех клиентов. Если в
будущем parsers получит /products эндпоинт (см. parsers-wishlist.md
п. 2), часть этого роутера можно будет переписать на проксирование.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db_local import PortalDB, get_portal_db
from app.deps import get_parsers_client
from app.parsers_client import ParsersClient
from app.schemas import (
    PricePointOut,
    ProductDetailOut,
    ProductOut,
    ProductsPage,
    SearchesPage,
    SearchLogOut,
)

router = APIRouter(prefix="/db", tags=["db"])

SortKey = Literal["fetched_desc", "price_asc", "price_desc", "title_asc"]


@router.get("/products", response_model=ProductsPage)
async def list_products(
    db: Annotated[PortalDB, Depends(get_portal_db)],
    q: str | None = Query(None, description="Подстрока в нормализованном title"),
    store: str | None = Query(None, description="Фильтр по slug магазина"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: SortKey = Query("fetched_desc"),
) -> ProductsPage:
    result = await db.list_products(
        q=q, store=store, page=page, page_size=page_size, sort=sort,
    )
    return ProductsPage(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/products/{product_id}", response_model=ProductDetailOut)
async def get_product(
    product_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
    client: Annotated[ParsersClient, Depends(get_parsers_client)],
) -> ProductDetailOut:
    """Полная карточка из локальной БД + история цен из parsers.

    Если товара нет в локальной БД — 404. Историю цен пытаемся загрузить из
    parsers; на ошибку возвращаем пустой массив, чтобы страница всё равно
    рендерилась.
    """
    product = await db.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден в локальной БД")

    history: list[PricePointOut] = []
    try:
        history = await client.get_history(product_id)
    except Exception:  # noqa: BLE001 — деградируем мягко, см. wishlist п. 3
        pass

    return ProductDetailOut(
        **product.model_dump(),
        observations=history,
    )


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    db: Annotated[PortalDB, Depends(get_portal_db)],
) -> dict:
    """Удаляет запись только из локальной БД (parsers не трогаем)."""
    deleted = await db.delete_product(product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Товар не найден в локальной БД")
    return {"deleted": True, "id": product_id}


@router.get("/searches", response_model=SearchesPage)
async def list_searches(
    db: Annotated[PortalDB, Depends(get_portal_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    query: str | None = Query(None, description="Подстрока в query"),
) -> SearchesPage:
    """Журнал поисковых запросов, выполненных через портал."""
    result = await db.list_searches(page=page, page_size=page_size, query=query)
    return SearchesPage(
        items=[SearchLogOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )
