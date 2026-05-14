#!/usr/bin/env python3
"""PoC L0 шаг 2 — найти XHR-endpoint avito.ru для items.

Контекст: probe_avito_l0.py показал, что avito перешёл на CSR — HTML 450KB,
Qrator пропускает curl-cffi из Docker и ставит _avisc, но items в первом
HTML нет. JS на странице дёргает какой-то JSON-endpoint после загрузки —
этот скрипт пытается его найти и дёрнуть тем же curl-cffi.

Что делает:

1. Cold-start GET https://www.avito.ru/ → получаем _avisc + базовые куки.
2. GET страницы поиска → теперь у нас полный набор кук от Qrator.
3. **Discovery**: ищем в HTML потенциальные XHR-endpoints (по regex).
   Сохраняем HTML в /tmp/avito_search.html для ручного разбора.
4. **Pings**: пробуем известные endpoints с накопленными куками и
   корректными Referer/X-Source headers (как делает avito-фронт).

Запуск:
    docker compose --profile full run --rm --no-deps \\
        -v "$PWD/bin:/probe:ro" \\
        -v "$PWD/.scratch:/scratch" \\
        parsers python /probe/probe_avito_l0_xhr.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import quote_plus

try:
    from curl_cffi.requests import Session
except ImportError:
    print("[FAIL] curl_cffi не установлен")
    sys.exit(2)

QUERY = os.environ.get("PROBE_QUERY", "Каркассон")

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# Заголовки имитирующие XHR-запрос фронта avito.
XHR_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": BASE_HEADERS["User-Agent"],
    # X-Source — частый avito-маркер из их фронтенда.
    "X-Source": "desktop",
}


def discover_endpoints(html: str) -> dict[str, list[str]]:
    """Ищем в HTML потенциальные XHR-endpoints. Возвращаем словарь
    {pattern → [найденные строки]} для просмотра."""
    patterns = {
        "/web/v*/...": re.findall(r'(?:"|\')((?:/web/[v\d][^"\'\s]+))(?:"|\')', html)[:20],
        "/api/...": re.findall(r'(?:"|\')(/api/[^"\'\s]+)(?:"|\')', html)[:20],
        "apiUrl/baseUrl": re.findall(r'(?:apiUrl|baseUrl|baseURL)["\'\s:]+["\']([^"\']+)["\']', html)[:10],
        "items endpoints": re.findall(r'["\'](https?://[^"\']*items[^"\']*)["\']', html)[:10],
    }
    return {k: v for k, v in patterns.items() if v}


def main() -> int:
    print(f"[probe] query={QUERY!r}\n")

    with Session(impersonate="chrome124") as s:
        # Шаг 1: главная — Qrator увидит "органический" заход.
        print("[1/4] GET https://www.avito.ru/")
        r1 = s.get("https://www.avito.ru/", headers=BASE_HEADERS, timeout=20)
        print(f"     → HTTP {r1.status_code}, cookies={list(r1.cookies.keys())}")
        if r1.status_code != 200:
            print("[FAIL] главная не пустила")
            return 1

        # Шаг 2: страница поиска — этот же URL, что в probe_avito_l0.
        search_url = f"https://www.avito.ru/rossiya?q={quote_plus(QUERY)}&isNewAds=1&s=104"
        print(f"\n[2/4] GET {search_url}")
        headers2 = {**BASE_HEADERS, "Referer": "https://www.avito.ru/", "Sec-Fetch-Site": "same-origin"}
        r2 = s.get(search_url, headers=headers2, timeout=20)
        print(f"     → HTTP {r2.status_code}, body {len(r2.content)} bytes")
        cookies_jar = {c.name: c.value for c in s.cookies.jar}
        print(f"     → accumulated cookies: {sorted(cookies_jar.keys())}")

        body = r2.text

        # Дамп для офлайн-исследования.
        scratch = "/scratch/avito_search.html"
        try:
            os.makedirs(os.path.dirname(scratch), exist_ok=True)
            with open(scratch, "w", encoding="utf-8") as f:
                f.write(body)
            print(f"     → HTML сохранён в {scratch}")
        except OSError as exc:
            print(f"     → (не могу сохранить HTML: {exc})")

        # Шаг 3: discovery — ищем кандидатов на endpoint.
        print("\n[3/4] discovery endpoints в HTML:")
        discovered = discover_endpoints(body)
        if not discovered:
            print("     (ничего не нашли — структура страницы могла поменяться)")
        for pattern, hits in discovered.items():
            print(f"     [{pattern}]")
            for h in hits[:10]:
                print(f"        {h}")

        # Шаг 4: пробуем известные публичные endpoints. Список собран из
        # старых обсуждений avito-парсеров (комьюнити, не reverse-engineering
        # mobile API — это публичные web-endpoints, которые дёргает сам avito.ru).
        print("\n[4/4] пробую известные XHR-endpoints:")
        q = quote_plus(QUERY)
        candidates = [
            f"https://www.avito.ru/web/1/main/items?q={q}&locationId=637640",
            f"https://www.avito.ru/web/1/items?q={q}",
            f"https://www.avito.ru/web/3/items?q={q}",
            f"https://www.avito.ru/web/4/items?q={q}",
            f"https://www.avito.ru/web/1/js/items?q={q}",
            f"https://www.avito.ru/js/v1/items?q={q}",
            f"https://www.avito.ru/web/9/items?q={q}",
            f"https://m.avito.ru/api/9/items?q={q}&key=af0deccbgcgidddjgnvljitntccdduijhdinfgjgfjir",
        ]

        for url in candidates:
            xhr_headers = {
                **XHR_HEADERS,
                "Referer": search_url,
                "Origin": "https://www.avito.ru",
            }
            try:
                r = s.get(url, headers=xhr_headers, timeout=15)
            except Exception as exc:
                print(f"     [{url[:80]}] EXC: {exc}")
                continue
            ct = r.headers.get("content-type", "")
            preview = ""
            if "json" in ct:
                try:
                    data = r.json()
                    if isinstance(data, dict):
                        preview = f"keys={list(data.keys())[:10]}"
                    elif isinstance(data, list):
                        preview = f"list[{len(data)}]"
                except (json.JSONDecodeError, ValueError):
                    preview = "(invalid json)"
            else:
                preview = f"ct={ct[:40]}, body={len(r.content)}b"
            print(f"     HTTP {r.status_code}  {preview}  ← {url[:90]}")
            if r.status_code == 200 and "json" in ct:
                print("       [HIT ✓] возможно живой endpoint! Сохраняю первые 1500 байт:")
                print("       " + r.text[:1500].replace("\n", "\n       "))

    print("\nГотово. Что делать дальше:")
    print("  - Если в шаге 4 виден [HIT ✓] с JSON — это наш L0 endpoint.")
    print("  - Если ничего не нашлось, смотрим .scratch/avito_search.html и ищем")
    print("    в нём конструкции fetch(...), api(...), /web/... — оттуда можно")
    print("    извлечь актуальный путь.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
