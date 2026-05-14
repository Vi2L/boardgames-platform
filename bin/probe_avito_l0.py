#!/usr/bin/env python3
"""PoC для стратегии L0 (Variant C, Avito Qrator bypass).

Цель: понять, можно ли парсить результаты поиска avito.ru через чистый
curl-cffi (TLS impersonation, без браузера). Если можно — L0 экономит
~80% запусков Playwright/camoufox для типичного объёма 5–1000 req/день.

Запуск ИЗ КОНТЕЙНЕРА (важно — проверяем условия prod-окружения, а не
"доверенный" IP домашнего Mac):

    docker compose --profile minimal up -d                # на случай если ничего не поднято
    docker compose run --rm --no-deps \\
        -v "$PWD/bin:/probe:ro" \\
        -e PROBE_QUERY="${PROBE_QUERY:-Каркассон}" \\
        parsers python /probe/probe_avito_l0.py

Что проверяем:

1. Какой HTTP-статус вернул Qrator. Если 200 — пропустил.
2. Установил ли Qrator куку `_avisc` в Set-Cookie. Это маркер «гость
   признан легитимным» — без неё дальше всё бесполезно.
3. Содержит ли тело страницы парсимый items-блок. Avito рендерит SSR
   с `window.__initialData` (URL-encoded JSON) и/или `<script type=
   "application/ld+json">` с ItemList. Если они есть и парсятся —
   L0 жизнеспособна.
4. Сколько items получилось вытащить и сколько из них с полным набором
   полей (title, url, price).

Выход: 0 = L0 работоспособна, 1 = L0 не годится (можно вычеркнуть из плана).
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import quote_plus, unquote

try:
    from curl_cffi.requests import Session
except ImportError:
    print("[FAIL] curl_cffi не установлен. Добавь в services/parsers/pyproject.toml")
    sys.exit(2)

QUERY = os.environ.get("PROBE_QUERY", "Каркассон")
URL = f"https://www.avito.ru/rossiya?q={quote_plus(QUERY)}&isNewAds=1&s=104"

# Заголовки максимально близкие к реальному Chrome (включая sec-ch-* hints,
# которые Qrator активно проверяет с конца 2024 года).
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


def extract_initial_data(html: str) -> dict | None:
    """Avito прячет SSR-state в window.__initialData = decodeURIComponent("...JSON...").

    URL-encoded потому что внутри много кириллицы и спецсимволов — так быстрее,
    чем сериализовать вручную.
    """
    m = re.search(
        r'window\.__initialData__\s*=\s*decodeURIComponent\(\s*"([^"]+)"\s*\)',
        html,
    )
    if not m:
        return None
    try:
        return json.loads(unquote(m.group(1)))
    except (json.JSONDecodeError, ValueError):
        return None


def extract_jsonld_items(html: str) -> list[dict]:
    """JSON-LD ItemList — стандартный SEO-блок, Avito его раздаёт всегда.

    Зачастую дублирует данные из __initialData, но без вложенной структуры —
    парсится надёжнее.
    """
    items: list[dict] = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL,
    ):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            for el in data.get("itemListElement", []):
                if isinstance(el, dict):
                    items.append(el)
    return items


def find_items_in_initial_data(data: dict) -> list[dict]:
    """В __initialData items лежат глубоко — структура нестабильна.
    Ищем по характерным ключам широким обходом."""
    found: list[dict] = []

    def walk(node, depth=0):
        if depth > 10:
            return
        if isinstance(node, dict):
            if {"id", "title", "price"}.issubset(node.keys()) or "itemId" in node:
                found.append(node)
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(data)
    return found


def main() -> int:
    print(f"[probe] URL: {URL}")
    print(f"[probe] impersonate=chrome124, query={QUERY!r}\n")

    with Session(impersonate="chrome124") as s:
        try:
            resp = s.get(URL, headers=HEADERS, timeout=20, allow_redirects=True)
        except Exception as exc:
            print(f"[FAIL] curl-cffi exception: {exc}")
            return 1

    print(f"[probe] HTTP {resp.status_code}, body {len(resp.content)} bytes, "
          f"final_url={resp.url}")

    cookies_received = dict(resp.cookies.items())
    has_avisc = "_avisc" in cookies_received
    has_v = "v" in cookies_received
    print(f"[probe] cookies set: {len(cookies_received)} — "
          f"_avisc={'YES' if has_avisc else 'NO'}, v={'YES' if has_v else 'NO'}")
    if cookies_received:
        names = sorted(cookies_received.keys())
        print(f"[probe] cookie names: {names}")

    body = resp.text

    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    page_title = title_match.group(1).strip() if title_match else "(no title)"
    print(f"[probe] <title>: {page_title!r}")

    blocked_re = re.compile(r"ограничен|captcha|firewall|робот|access denied|заблокирован", re.I)
    if blocked_re.search(page_title):
        print("[FAIL] страница похожа на Qrator challenge page")
        return 1

    initial = extract_initial_data(body)
    if initial:
        items_init = find_items_in_initial_data(initial)
        print(f"[probe] __initialData: parsed OK, items candidates={len(items_init)}")
    else:
        items_init = []
        print("[probe] __initialData: NOT FOUND")

    items_ld = extract_jsonld_items(body)
    print(f"[probe] JSON-LD ItemList: items={len(items_ld)}")

    items_attr = len(re.findall(r'data-item-id="(\d+)"', body))
    print(f"[probe] data-item-id markers in HTML: {items_attr}")

    if items_attr >= 5 or len(items_ld) >= 5 or len(items_init) >= 5:
        print("\n[OK ✓] L0 жизнеспособна — avito раздаёт SSR-данные без браузера.")
        print("       Можно вычитывать список объявлений без Playwright/camoufox.")
        if items_ld:
            sample = items_ld[0]
            print(f"\n[probe] пример JSON-LD item: {json.dumps(sample, ensure_ascii=False)[:300]}")
        return 0

    if has_avisc and items_attr == 0:
        print("\n[PARTIAL] Qrator пустил (есть _avisc), но SSR пустой — "
              "видимо отдаёт CSR-shell, items подтягиваются JS-ом. "
              "L0 не подойдёт для items, но _avisc можно фармить и инжектить в браузер.")
        return 1

    print("\n[FAIL] L0 не жизнеспособна в этом окружении.")
    print("       Avito не пропускает curl-cffi с DC/контейнер IP, либо "
          "поменял SSR-схему. Стратегия L0 из плана вычёркивается, "
          "Variant C сводится к B+ (L1/L2/L3).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
