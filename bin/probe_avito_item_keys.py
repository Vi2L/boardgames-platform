#!/usr/bin/env python3
"""Probe: смотрим, какие поля есть в item ответа /web/1/js/items, чтобы
понять, по какому маркеру отфильтровать «настольные игры» локально.

Печатает все ключи первого item и значения, относящиеся к категории.
"""
from __future__ import annotations

import asyncio
import json

from parsers.stores.avito_qrator import AvitoQratorClient

QUERIES = ["каркассон", "книга", "роман гарри поттер"]


async def main() -> None:
    client = AvitoQratorClient()
    try:
        for q in QUERIES:
            print(f"\n=== query={q!r} ===")
            try:
                payload = await client.search_items(q)
            except Exception as exc:
                print(f"  FAIL: {exc}")
                continue
            items = (payload.get("catalog") or {}).get("items") or []
            print(f"  total items: {len(items)}")
            for it in items[:8]:
                if not isinstance(it, dict):
                    continue
                cat = it.get("category") or {}
                title = (it.get("title") or "")[:50]
                url_path = (it.get("urlPath") or "")[:80]
                print(f"  - {title!r:55} cat={cat} urlPath={url_path}")
            # Печатаем все ключи первого item для диагностики
            if items and isinstance(items[0], dict):
                print(f"  KEYS: {sorted(items[0].keys())}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
