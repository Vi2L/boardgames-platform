#!/usr/bin/env python3
"""Probe #3: смотрим microCategoryId по разным query, чтобы выяснить
конкретное значение для «Настольные игры» (подкатегория внутри
category.id=39 «Спорт и отдых»).

Гипотеза: фильтр локальный — оставляем item только если microCategoryId
совпадает со значением «Настольные игры». Цель probe: определить это
значение.
"""
from __future__ import annotations

import asyncio
from collections import Counter

from parsers.stores.avito_qrator import AvitoQratorClient

QUERIES = [
    "каркассон",
    "монополия",
    "ужас аркхэма",
    "сыграй",
    "книга",
    "велосипед",
    "пазл",
    "детская игрушка",
]


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
            mc: Counter[tuple] = Counter()
            for it in items[:50]:
                if not isinstance(it, dict):
                    continue
                cat = it.get("category") or {}
                key = (
                    cat.get("id"),
                    cat.get("slug") or "",
                    it.get("microCategoryId"),
                )
                mc[key] += 1
            # сортируем по count desc
            for (cat_id, slug, micro), cnt in mc.most_common(10):
                print(f"  cat_id={cat_id:>4} slug={slug:<28} microId={micro!s:>6}  count={cnt}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
