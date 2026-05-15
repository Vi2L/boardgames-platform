#!/usr/bin/env python3
"""WB probe шаг 4 — добиваем v5/v4 legacy endpoint без preset-routing.

Текущая картина:
  - search.wb.ru v13 = preset-router (вернул shardKey без products).
  - catalog.wb.ru v9/v8/v13 = 403 Forbidden из Docker (Angie блокирует DC-IP).
  - search.wb.ru v5 с curl-cffi возвращал 124KB body — формат старый, без
    preset-redirect.

Если v5 ещё жив — берём его. Запасной вариант: попробовать v4 (legacy),
plus попробовать catalog.wb.ru через AsyncSession (cookies от search.wb.ru
могут открыть catalog).
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


def probe_search_endpoint(s, version: str, with_subject: bool) -> dict | None:
    params = {
        "ab_testing": "false", "appType": "1", "curr": "rub",
        "dest": "-1257786", "lang": "ru", "query": QUERY,
        "resultset": "catalog", "sort": "popular", "spp": "30",
        "suppressSpellcheck": "false",
    }
    if with_subject:
        params["xsubject"] = "1144"  # WB filter param пишется как xsubject
    url = f"https://search.wb.ru/exactmatch/ru/common/{version}/search?" + urlencode(params)
    print(f"\n[{version}{'+sub' if with_subject else ''}] {url[:140]}")
    r = s.get(url, headers=_HEADERS, timeout=20)
    print(f"  HTTP {r.status_code}, body {len(r.content)}b, ct={r.headers.get('content-type', '')[:30]}")
    if r.status_code != 200:
        return None
    try:
        d = r.json()
    except Exception as e:
        print(f"  json err: {e}; body[:200]={r.text[:200]}")
        return None

    # Где products: v5/v4 — data.products, v8/v9/v13 — иногда там, иногда нет
    products = (d.get("data") or {}).get("products") or d.get("products") or []
    print(f"  data keys: {list((d.get('data') or {}).keys())}")
    print(f"  products={len(products)}")
    if products:
        try:
            out = f"/scratch/wb_search_{version}{'_sub' if with_subject else ''}.json"
            with open(out, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            print(f"  [saved] {out}")
        except OSError:
            pass
        print(f"  sample card keys: {list(products[0].keys())[:25]}")
        for i, p in enumerate(products[:5]):
            sz = (p.get("sizes") or [{}])[0]
            pb = sz.get("price") or {}
            price_u = p.get("salePriceU") or p.get("priceU") or pb.get("product") or pb.get("basic")
            print(f"    [{i+1}] id={p.get('id')} subj={p.get('subjectId')} "
                  f"«{p.get('brand', '')[:20]} {(p.get('name') or '')[:40]}» price_u={price_u}")
    return d


def main() -> int:
    from curl_cffi.requests import Session
    s = Session(impersonate="chrome124")

    for v in ("v4", "v5", "v8", "v9"):
        time.sleep(0.3)
        probe_search_endpoint(s, v, with_subject=False)
        time.sleep(0.3)
        probe_search_endpoint(s, v, with_subject=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
