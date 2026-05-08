"""Контракт webhook'а POST /ingest/offers (parsers → catalog).

Один источник правды для:
- producer: services/parsers/parsers/catalog_publisher.py
- consumer: services/catalog/catalog/routers/ingest.py

При изменении формата правится только этот файл; оба сервиса подхватят
обновление через `uv sync`. См. docs/parallel-agents.md §8.3 / §10.2.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IngestOfferIn(BaseModel):
    """Один товар в payload webhook'а.

    Нормализованные поля магазина (sku/in_stock/original_price/is_preorder)
    появились в миграции catalog 0006. Все они опциональны: старый клиент
    может не отправлять их — поведение остаётся прежним (catalog умеет
    извлекать их из `extra` как fallback).
    """

    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str
    price: int | None = None  # копейки
    image_url: str | None = None
    sku: str | None = None
    in_stock: bool | None = None
    original_price: int | None = None  # копейки до скидки
    is_preorder: bool | None = None
    extra: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    """Payload POST /ingest/offers — батч оффер'ов от одного магазина."""

    store_slug: str = Field(min_length=1, max_length=64)
    fetched_at: datetime | None = None
    products: list[IngestOfferIn]
