#!/usr/bin/env python3
"""WB probe шаг 2 — один запрос, полный дамп JSON.

Первый probe показал странное: `v13+curl-cffi+subject=1144` → 200, но
products=0; `v5+curl-cffi+subject=1144` → 200, body=124KB, но products=0.
Подозрение: формат JSON отличается между версиями, либо WB shadow-banит
запрос с DC-IP.

Этот скрипт делает ОДИН целевой запрос (v13 + curl-cffi + без фильтра)
и сохраняет ответ в /scratch/wb_response.json, плюс печатает top-level
keys и первые 3 элемента из всех list-полей.

Run:
    docker compose --profile full run --rm --no-deps \\
        -v "$PWD/bin:/probe:ro" -v "$PWD/.scratch:/scratch" \\
        parsers python /probe/probe_wb2.py
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import quote_plus, urlencode

QUERY = os.environ.get("PROBE_QUERY", "Каркассон")
VERSION = os.environ.get("PROBE_VERSION", "v13")

_PARAMS = {
    "ab_testing": "false",
    "appType": "1",
    "curr": "rub",
    "dest": "-1257786",
    "lang": "ru",
    "query": QUERY,
    "resultset": "catalog",
    "sort": "popular",
    "spp": "30",
    "suppressSpellcheck": "false",
}

HEADERS = {
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

    url = f"https://search.wb.ru/exactmatch/ru/common/{VERSION}/search?" + urlencode(_PARAMS)
    print(f"[probe-wb2] GET {url}\n")

    with Session(impersonate="chrome124") as s:
        resp = s.get(url, headers=HEADERS, timeout=20)

    print(f"HTTP {resp.status_code}  body {len(resp.content)} bytes")
    print(f"content-type: {resp.headers.get('content-type', '')}")
    if resp.status_code != 200:
        print("[FAIL] non-200, body preview:")
        print(resp.text[:500])
        return 1

    try:
        data = resp.json()
    except Exception as exc:
        print(f"[FAIL] JSON decode: {exc}")
        print(resp.text[:500])
        return 1

    # Сохраняем полный ответ для офлайн-разбора.
    out = f"/scratch/wb_response_{VERSION}.json"
    try:
        os.makedirs("/scratch", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[saved] {out}")
    except OSError as exc:
        print(f"[warn] не сохранил: {exc}")

    # Анализ shape.
    print(f"\nTop-level keys: {list(data.keys())}")

    def show(node, prefix: str = "", depth: int = 0):
        if depth > 3:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                path = f"{prefix}.{k}" if prefix else k
                if isinstance(v, (str, int, float, bool)) or v is None:
                    sval = repr(v)[:60]
                    print(f"   {path}: {sval}")
                elif isinstance(v, list):
                    print(f"   {path}: list[{len(v)}]")
                    if v and isinstance(v[0], dict):
                        # Печатаем ключи первого элемента для понимания shape карточки.
                        print(f"     [0] keys: {list(v[0].keys())[:25]}")
                        # И первый карточек, если это похоже на products.
                        if path.endswith(("products", "items", "data.products", "results")) and len(v) > 0:
                            print(f"     [0] sample (truncated):")
                            preview = {k: (str(v[0][k])[:80] if v[0][k] is not None else None) for k in list(v[0].keys())[:15]}
                            for kk, vv in preview.items():
                                print(f"        {kk}: {vv}")
                    elif depth < 2:
                        show(v[0] if v else None, f"{path}[0]", depth + 1)
                elif isinstance(v, dict):
                    print(f"   {path}: dict({len(v)} keys)")
                    show(v, path, depth + 1)

    show(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
