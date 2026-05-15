#!/usr/bin/env python3
"""WB probe шаг 3 — двухшаговый поиск через preset.

Probe-2 показал: v13/search возвращает preset-routing metadata, а не товары.
Реальные products живут в catalog.wb.ru/catalog/{shardKey}/v{N}/catalog
с параметром preset=<id>, полученным на шаге 1.

Запрос:
  Step 1: search.wb.ru/exactmatch/ru/common/v13/search → preset + shardKey
  Step 2: catalog.wb.ru/catalog/{shardKey}/v9/catalog?preset=<id>&query=...

Тестирую:
  - что catalog.wb.ru возвращает 200
  - какая структура (ожидаем data.products[])
  - какие поля у карточки (id, name, price*, brand, sizes, etc.)
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import quote_plus, urlencode

QUERY = os.environ.get("PROBE_QUERY", "Каркассон")

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Origin": "https://www.wildberries.ru",
    "Referer": f"https://www.wildberries.ru/catalog/0/search.aspx?search={quote_plus(QUERY)}",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}


def main() -> int:
    from curl_cffi.requests import Session

    s = Session(impersonate="chrome124")

    # Step 1 — preset.
    s1_params = {
        "ab_testing": "false", "appType": "1", "curr": "rub",
        "dest": "-1257786", "lang": "ru", "query": QUERY,
        "resultset": "catalog", "sort": "popular", "spp": "30",
        "suppressSpellcheck": "false",
    }
    s1_url = "https://search.wb.ru/exactmatch/ru/common/v13/search?" + urlencode(s1_params)
    print(f"[step1] GET {s1_url[:120]}")
    r1 = s.get(s1_url, headers=_HEADERS, timeout=20)
    print(f"[step1] HTTP {r1.status_code}, body {len(r1.content)}b")
    if r1.status_code != 200:
        print("[FAIL]", r1.text[:300])
        return 1
    d1 = r1.json()
    print(f"[step1] keys: {list(d1.keys())}")

    preset_query = d1.get("query") or ""
    shard_key = d1.get("shardKey") or ""
    print(f"[step1] preset_query={preset_query!r}, shardKey={shard_key!r}")

    if not preset_query or not shard_key:
        print("[FAIL] preset routing missing")
        return 1

    # Step 2 — catalog. Версии v9/v8 живы; пробуем v9 → v8.
    s2_params = {
        "ab_testing": "false", "appType": "1", "curr": "rub",
        "dest": "-1257786", "lang": "ru", "query": QUERY,
        "sort": "popular", "spp": "30", "suppressSpellcheck": "false",
    }
    # preset_query уже сам в форме "preset=10006602" — разбираем и добавляем как key=value.
    for kv in preset_query.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            s2_params[k] = v

    # WB иногда требует subjectId явно. Пока без, чтобы убедиться что twin-search
    # OK на голом catalog: subject будет проверен на втором проходе.
    for version in ("v9", "v8", "v13"):
        time.sleep(0.4)
        s2_url = (
            f"https://catalog.wb.ru/catalog/{shard_key}/{version}/catalog?"
            + urlencode(s2_params)
        )
        print(f"\n[step2/{version}] GET {s2_url[:140]}")
        r2 = s.get(s2_url, headers=_HEADERS, timeout=20)
        print(f"[step2/{version}] HTTP {r2.status_code}, body {len(r2.content)}b")
        if r2.status_code != 200:
            print(f"       body preview: {r2.text[:200]}")
            continue
        try:
            d2 = r2.json()
        except Exception as exc:
            print(f"       JSON err: {exc}")
            continue

        products = (d2.get("data") or {}).get("products") or d2.get("products") or []
        print(f"       products={len(products)}")
        if not products:
            # дамп ключей для понимания shape
            print(f"       top-keys: {list(d2.keys())}")
            data_keys = list((d2.get('data') or {}).keys())
            print(f"       data keys: {data_keys}")
            continue

        # Сохраним для офлайн-разбора + покажем первые 3 карточки.
        try:
            out = f"/scratch/wb_catalog_{version}.json"
            with open(out, "w", encoding="utf-8") as f:
                json.dump(d2, f, ensure_ascii=False, indent=2)
            print(f"       [saved] {out}")
        except OSError:
            pass

        print(f"       sample card keys: {list(products[0].keys())[:25]}")
        for i, p in enumerate(products[:3]):
            price_u = p.get("salePriceU") or p.get("priceU")
            if not price_u:
                sz = (p.get("sizes") or [{}])[0]
                price_block = sz.get("price") or {}
                price_u = price_block.get("product") or price_block.get("basic")
            print(f"       [{i+1}] id={p.get('id')} subj={p.get('subjectId')} "
                  f"«{p.get('brand', '')} {(p.get('name') or '')[:50]}» price_u={price_u}")

        print(f"\n[OK ✓] catalog.wb.ru/{version} работает — products={len(products)}.")
        return 0

    print("\n[FAIL] ни v9/v8/v13 на catalog.wb.ru не дали products")
    return 1


if __name__ == "__main__":
    sys.exit(main())
