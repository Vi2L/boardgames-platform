#!/usr/bin/env python3
"""PoC для WildberriesParser (WB.ru).

Цели:

1. Найти **актуальную версию** search-API (search.wb.ru эволюционирует:
   v4 → v5 → v8 → v9 → v13 — какие-то живы, какие-то 404).
2. Узнать, проходит ли запрос **обычным httpx** (без TLS-imp). Если да —
   AvitoQrator-style curl-cffi не нужен, что упрощает код и зависимости.
3. Сравнить **с фильтром по subjectId=1144 («Настольные игры»)** и без —
   проверить twin-search гипотезу.
4. Зафиксировать **shape JSON** (ключи в `data.products[]`), чтобы код
   парсера маппил поля без сюрпризов.

Запуск из контейнера (одной строкой):

    docker compose --profile full run --rm --no-deps \\
        -v "$PWD/bin:/probe:ro" \\
        parsers python /probe/probe_wb.py

Опции:
    PROBE_QUERY=Каркассон  — поисковая строка
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlencode

QUERY = os.environ.get("PROBE_QUERY", "Каркассон")

# WB разные версии endpoint живут параллельно (на разных audience-A/B).
# Берём по убыванию свежести — успех на верхней значит, что её и использовать.
_VERSIONS = ["v13", "v9", "v8", "v5"]

# WB требует параметр `dest` — это код назначения доставки (геокод).
# -1257786 = Москва, -2162196 = СПб; «-1257786» исторически работает по всей РФ.
_BASE_PARAMS = {
    "ab_testing": "false",
    "appType": "1",          # 1 = web; 128 = mobile
    "curr": "rub",
    "dest": "-1257786",
    "lang": "ru",
    "resultset": "catalog",
    "sort": "popular",
    "spp": "30",
    "suppressSpellcheck": "false",
}

_HEADERS_VANILLA = {
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Origin": "https://www.wildberries.ru",
    "Referer": "https://www.wildberries.ru/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _build_url(version: str, query: str, with_subject: bool) -> str:
    params = {**_BASE_PARAMS, "query": query}
    if with_subject:
        # 1144 — subjectId «Настольные игры». Параметр `f<subjectId>=1` в новых
        # версиях, в старых иногда `subject=1144`. Кладём оба — лишний игнорируется.
        params["f1144"] = "1"
        params["subject"] = "1144"
    return (
        f"https://search.wb.ru/exactmatch/ru/common/{version}/search?"
        + urlencode(params)
    )


def _peek(items: list[dict], n: int = 3) -> None:
    """Печатает первые N карточек кратко — чтобы понять shape."""
    for i, p in enumerate(items[:n]):
        # Цены в WB в копейках *уже* (умножены на 100). priceU старое,
        # salePriceU современное; в v13 sizes[].price.{basic,product}.
        price_u = p.get("salePriceU") or p.get("priceU")
        sizes = p.get("sizes") or []
        if not price_u and sizes:
            price_block = sizes[0].get("price") or {}
            price_u = price_block.get("product") or price_block.get("basic")
        name = p.get("name") or "(no name)"
        brand = p.get("brand", "")
        subj = p.get("subjectId") or p.get("subject")
        print(f"     [{i+1}] id={p.get('id')} subj={subj} «{brand} {name[:50]}» "
              f"price_u={price_u}")


def _try_request(label: str, url: str, backend: str) -> dict | None:
    print(f"\n  → {label}  ({backend})")
    print(f"     URL: {url[:140]}")

    try:
        if backend == "httpx":
            import httpx
            resp = httpx.get(url, headers=_HEADERS_VANILLA, timeout=15)
            body_bytes = resp.content
            status = resp.status_code
            ct = resp.headers.get("content-type", "")
        else:
            from curl_cffi.requests import Session
            with Session(impersonate="chrome124") as s:
                resp = s.get(url, headers=_HEADERS_VANILLA, timeout=15)
            body_bytes = resp.content
            status = resp.status_code
            ct = resp.headers.get("content-type", "")
    except Exception as exc:
        print(f"     EXC: {exc}")
        return None

    print(f"     HTTP {status}  ct={ct[:40]}  body={len(body_bytes)}b")
    if status != 200:
        return None
    if "json" not in ct.lower() and not body_bytes.startswith(b"{"):
        print("     (не JSON)")
        return None

    try:
        data = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        print(f"     JSON err: {exc}")
        return None

    products = (data.get("data") or {}).get("products") or []
    print(f"     products={len(products)}")
    _peek(products)
    return data


def main() -> int:
    print(f"[probe-wb] query={QUERY!r}")

    backends = ["httpx", "curl-cffi"]
    success_combos: list[tuple[str, str, bool]] = []  # (version, backend, with_subject)

    for version in _VERSIONS:
        for backend in backends:
            data_with = _try_request(
                f"{version} + subject=1144",
                _build_url(version, QUERY, with_subject=True),
                backend,
            )
            data_wo = _try_request(
                f"{version} (без фильтра)",
                _build_url(version, QUERY, with_subject=False),
                backend,
            )
            if data_with is not None:
                success_combos.append((version, backend, True))
            if data_wo is not None:
                success_combos.append((version, backend, False))

    print("\n" + "=" * 60)
    print("Результаты:")
    if not success_combos:
        print("  [FAIL] Ни одна комбинация не дала JSON-ответ.")
        print("  Возможные причины: блок WB по IP, изменения в API, региональные ограничения.")
        return 1
    print("  Рабочие комбинации (version, backend, with_subject):")
    for combo in success_combos:
        print(f"    ✓ {combo[0]:5s}  {combo[1]:10s}  subjectId={combo[2]}")

    # Эвристика: предпочитаем свежую версию + httpx + с фильтром
    preferred = sorted(
        success_combos,
        key=lambda c: (_VERSIONS.index(c[0]), 0 if c[1] == "httpx" else 1, 0 if c[2] else 1),
    )[0]
    print(f"\n  Рекомендация: API={preferred[0]}, backend={preferred[1]}, "
          f"subjectId={'on' if preferred[2] else 'off'} (twin-search OK).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
