#!/usr/bin/env python3
"""Probe: проверка фильтрации Avito по categoryId.

Берём существующий AvitoQratorClient (shared cold-start, _avisc) и
дёргаем /web/1/js/items с двумя разными categoryId:
- без фильтра (baseline) → ожидаем разнобой категорий в ответе
- categoryId=102 (Настольные игры по официальной структуре Avito) →
  ожидаем только category.name == «Настольные игры»

Запуск:
    docker compose exec parsers python /probe/probe_avito_category.py
или
    docker compose --profile full run --rm --no-deps \
        -v "$PWD/bin:/probe:ro" parsers python /probe/probe_avito_category.py
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter

from parsers.stores.avito_qrator import AvitoQratorClient

QUERY = "каркассон"
CANDIDATES = [None, 102, 99, 21, 24]


async def probe_one(client: AvitoQratorClient, cat_id: int | None) -> None:
    """Дёргаем search_items с опциональной подменой params."""
    orig = client._search_items_once

    async def patched(query: str, *, sort: int) -> dict:
        await client.refresh_if_stale()
        from urllib.parse import quote_plus

        from curl_cffi.requests.exceptions import RequestException

        params = {"q": query, "s": str(sort)}
        if cat_id is not None:
            params["categoryId"] = str(cat_id)
        referer = f"{client.BASE}/rossiya?q={quote_plus(query)}&s={sort}"
        from parsers.stores.avito_qrator import _XHR_HEADERS
        headers = {**_XHR_HEADERS, "Referer": referer, "Origin": client.BASE}
        resp = await client._session.get(
            client.SEARCH_API, headers=headers, params=params, timeout=20,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        return resp.json()

    client._search_items_once = patched
    try:
        payload = await client.search_items(QUERY)
    except Exception as exc:
        print(f"  [cat={cat_id}] FAIL: {exc}")
        return
    finally:
        client._search_items_once = orig

    items = (payload.get("catalog") or {}).get("items") or []
    cats: Counter[str] = Counter()
    sample_titles: list[str] = []
    for it in items[:30]:
        if not isinstance(it, dict):
            continue
        cat = (it.get("category") or {}).get("name") or "?"
        cats[cat] += 1
        if len(sample_titles) < 5:
            sample_titles.append(it.get("title", "")[:60])
    print(f"  [cat={cat_id}] items={len(items)} cats={dict(cats)} sample={sample_titles}")


async def main() -> None:
    client = AvitoQratorClient()
    try:
        for cat_id in CANDIDATES:
            print(f"--- categoryId={cat_id} ---")
            await probe_one(client, cat_id)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
