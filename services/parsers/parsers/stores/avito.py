"""Парсер Авито — C2C доска объявлений.

Стратегия обхода Qrator (многоуровневая):

1. curl-cffi с impersonate='chrome124' — имитирует TLS-отпечаток реального
   Chrome, включая JA3/JA4 и GREASE. Qrator пропускает запрос и в ответ
   устанавливает свежий _avisc (Max-Age=60) и v-куки.

2. Инжекция _avisc в Playwright-профиль — используем только что полученный
   _avisc (и остальные свежие куки) в персистентном профиле браузера.
   Playwright с реальным _avisc проходит Qrator-проверку на основной странице.

3. AVITO_COOKIES (опционально) — JSON-файл или строка с куками из реального
   браузера. Помогает скрипту на шаге 1 пройти Qrator за один запрос
   (вместо нескольких cold-start визитов).

Переменные окружения:
  AVITO_COOKIES  — путь к .json или JSON-строка с куками из браузера.
                   Экспорт через Cookie-Editor (Chrome) → Export as JSON.

Поля ParsedProduct.raw:
  location   — город/регион продавца
  posted_at  — дата/время объявления
  in_stock   — True (факт наличия объявления)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote_plus

from ..base import ParserMetrics, StoreParser
from ..models import ParsedProduct, StoreInfo

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.avito.ru"
_SEARCH_URL_TPL = "https://www.avito.ru/rossiya?q={query}&isNewAds=1&s=104"

# JS выполняется в браузере (page.evaluate) через Playwright.
# Возвращает {pageTitle, blocked, items} — blocked детектирует Qrator-страницу.
_SEARCH_JS = """() => {
    const out = [];
    const seen = new Set();

    function toInt(s) {
        if (!s) return null;
        const n = parseInt(String(s).replace(/[^\\d]/g, ''));
        return isNaN(n) || n === 0 ? null : n;
    }

    const pageTitle = document.title || '';
    const blocked = /ограничен|captcha|firewall|робот|Access Denied|заблокирован/i.test(pageTitle);

    document.querySelectorAll('[data-item-id]').forEach(item => {
        const id = item.getAttribute('data-item-id');
        if (!id || seen.has(id)) return;

        const titleEl = item.querySelector('[itemprop="name"]');
        const title = titleEl ? titleEl.textContent.trim() : '';
        if (!title) return;

        const linkEl = item.querySelector('a[href*="' + id + '"]') || item.querySelector('a[href]');
        const url = linkEl ? linkEl.href.split('?')[0] : '';
        if (!url) return;

        seen.add(id);

        const priceMeta = item.querySelector('[itemprop="price"]');
        let price = priceMeta ? toInt(priceMeta.getAttribute('content')) : null;
        if (price === null) {
            const priceEl = item.querySelector('[class*="price"]');
            if (priceEl) price = toInt(priceEl.textContent.replace(/[\\u00a0\\u202f]/g, ''));
        }

        const imgEl = item.querySelector('img[src*="avito"], img[src*="img.avito"]') || item.querySelector('img');
        const image = imgEl ? (imgEl.src || imgEl.getAttribute('data-src') || '').split('?')[0] : '';

        const geoEl = item.querySelector('[data-marker="item-address"]');
        const location = geoEl ? geoEl.textContent.trim() : '';

        const dateEl = item.querySelector('[data-marker="item-date"] time, [data-marker="item-date"]');
        const posted_at = dateEl
            ? (dateEl.getAttribute('datetime') || dateEl.textContent.trim())
            : '';

        out.push({ title, url, price, image, itemId: id, location, posted_at });
    });

    return { pageTitle, blocked, items: out };
}"""

_SAME_SITE_MAP = {
    "no_restriction": "None",
    "unspecified": "None",
    "lax": "Lax",
    "strict": "Strict",
    "none": "None",
    "None": "None",
    "Lax": "Lax",
    "Strict": "Strict",
}


def _load_avito_cookies() -> list[dict] | None:
    """Читает AVITO_COOKIES из env — JSON-строка или путь к файлу."""
    raw = os.environ.get("AVITO_COOKIES", "").strip()
    if not raw:
        return None
    if raw.startswith("/") or raw.endswith(".json"):
        p = Path(raw)
        if not p.exists():
            return None
        raw = p.read_text()
    try:
        cookies = json.loads(raw)
        if isinstance(cookies, list) and cookies:
            return _normalize_cookies(cookies)
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _normalize_cookies(cookies: list[dict]) -> list[dict]:
    """Приводит cookie-объекты к формату Playwright.

    Chrome-расширения используют sameSite как "no_restriction"/"unspecified"/
    "lax"/"strict". Playwright принимает только "None"/"Lax"/"Strict".
    expirationDate (Chrome) → expires (Playwright).
    """
    normalized = []
    for c in cookies:
        name = c.get("name") or c.get("Name") or ""
        if not name:
            continue
        value = c.get("value") or c.get("Value") or ""
        domain = c.get("domain") or c.get("Domain") or ".avito.ru"
        host_only = bool(c.get("hostOnly"))
        if not host_only and not domain.startswith("."):
            domain = "." + domain

        raw_ss = c.get("sameSite") or c.get("SameSite") or "None"
        same_site = _SAME_SITE_MAP.get(str(raw_ss), "None")

        cookie: dict = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": c.get("path") or c.get("Path") or "/",
            "httpOnly": bool(c.get("httpOnly") or c.get("HttpOnly")),
            "secure": bool(c.get("secure") or c.get("Secure")),
            "sameSite": same_site,
        }
        exp = c.get("expirationDate") or c.get("expires")
        if exp is not None:
            cookie["expires"] = float(exp)
        normalized.append(cookie)
    return normalized


def _parse_set_cookie_header(header: str) -> list[dict]:
    """Извлекает куки из заголовка Set-Cookie browser-сервиса (объединённого в одну строку).

    Avito через Qrator устанавливает _avisc (Max-Age=60) и v.
    Парсим их чтобы инжектировать в Playwright-профиль до навигации.
    """
    cookies = []
    # Set-Cookie может содержать несколько кук через запятую (нестандартно,
    # но httpx/curl-cffi иногда объединяет их)
    # Разбиваем по ', name=' — граница между куками
    import re
    parts = re.split(r',\s*(?=[A-Za-z_][A-Za-z0-9_]+=)', header)
    for part in parts:
        segments = [s.strip() for s in part.split(";")]
        if not segments:
            continue
        name_val = segments[0]
        if "=" not in name_val:
            continue
        name, _, value = name_val.partition("=")
        cookie: dict = {
            "name": name.strip(),
            "value": value.strip(),
            "domain": ".avito.ru",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }
        for seg in segments[1:]:
            seg_l = seg.lower()
            if seg_l.startswith("domain="):
                d = seg.split("=", 1)[1].strip()
                cookie["domain"] = d if d.startswith(".") else "." + d
            elif seg_l.startswith("path="):
                cookie["path"] = seg.split("=", 1)[1].strip()
            elif seg_l.startswith("max-age="):
                try:
                    cookie["expires"] = time.time() + float(seg.split("=", 1)[1])
                except ValueError:
                    pass
            elif seg_l == "httponly":
                cookie["httpOnly"] = True
            elif seg_l == "secure":
                cookie["secure"] = True
            elif seg_l.startswith("samesite="):
                ss = seg.split("=", 1)[1].strip()
                cookie["sameSite"] = _SAME_SITE_MAP.get(ss.lower(), "Lax")
        cookies.append(cookie)
    return cookies


def _get_fresh_qrator_cookies(base_cookies: list[dict] | None) -> list[dict]:
    """Получает свежий _avisc через curl-cffi (Chrome TLS impersonation).

    Qrator проверяет TLS Client Hello. curl-cffi имитирует Chrome точнее,
    чем Python httpx или Playwright/BoringSSL. При успехе Qrator возвращает
    _avisc (Max-Age=60) и v в Set-Cookie.

    Возвращает список кук для инжекции в Playwright.
    """
    try:
        from curl_cffi.requests import Session
    except ImportError:
        logger.warning("[Авито] curl_cffi не установлен — пропускаем шаг получения _avisc")
        return base_cookies or []

    req_cookies = {}
    if base_cookies:
        req_cookies = {c["name"]: c["value"] for c in base_cookies}

    try:
        with Session(impersonate="chrome124") as s:
            resp = s.get(
                "https://www.avito.ru/",
                cookies=req_cookies,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                },
                timeout=15,
            )
    except Exception as exc:
        logger.warning("[Авито] curl_cffi warm-up failed: %s", exc)
        return base_cookies or []

    logger.debug("[Авито] curl_cffi warm-up status=%s", resp.status_code)

    # Собираем свежие куки из ответа
    fresh: list[dict] = list(base_cookies or [])
    set_cookie = resp.headers.get("set-cookie", "")
    if set_cookie:
        parsed = _parse_set_cookie_header(set_cookie)
        # Заменяем совпадающие имена (перезапись _avisc, v)
        existing_names = {c["name"] for c in fresh}
        for new_c in parsed:
            if new_c["name"] in existing_names:
                fresh = [c for c in fresh if c["name"] != new_c["name"]]
            fresh.append(new_c)
            logger.debug("[Авито] получен %s из curl_cffi response", new_c["name"])

    # Добавляем куки которые браузер установил в сессии (session cookies)
    for name, value in resp.cookies.items():
        if not any(c["name"] == name for c in fresh):
            fresh.append({
                "name": name, "value": value,
                "domain": ".avito.ru", "path": "/",
                "httpOnly": False, "secure": True, "sameSite": "Lax",
            })

    return fresh


class AvitoParser(StoreParser):
    """Парсер Авито через browser-as-a-service (services/browser/).

    Стратегия обхода Qrator:
    1. Куки из Chrome-расширения (включая httpOnly _avisc) — синхронизируются
       автоматически через POST /api/avito/cookies → .scratch/avito_cookies.json.
    2. curl-cffi (Chrome TLS impersonation) — разогревает сессию и получает
       свежий _avisc из Set-Cookie. Если _avisc уже есть в инжектированных куках,
       этот шаг пропускается.
    3. Playwright persistent profile + инжекция кук → JS-парсинг через evaluate.

    Без browser_client тихо возвращает [] — backward compat.
    """

    store = StoreInfo(slug="avito", name="Авито", base_url=_BASE_URL)

    def __init__(self, browser_client=None) -> None:
        super().__init__()
        self._browser_client = browser_client
        self._base_cookies: list[dict] | None = None
        self._cookie_file_mtime: float = 0  # для динамической перезагрузки
        self._reload_cookies()

    async def _wait_for_fresh_cookies(self, max_wait_sec: int = 90) -> bool:
        """Ждёт обновления файла кук (от Chrome-расширения) до max_wait_sec секунд.

        Возвращает True если файл обновился (cookies перезагружены).
        Chrome-расширение из services/parsers/chrome-extension POST-ит куки
        на /api/avito/cookies при каждом визите на avito.ru.
        """
        import asyncio
        cookie_path = os.environ.get("AVITO_COOKIES", "").strip()
        if not cookie_path:
            return False
        p = Path(cookie_path)
        old_mtime = self._cookie_file_mtime
        logger.info(
            "[Авито] заблокирован, жду свежих кук от Chrome-расширения (до %ds)... "
            "Откройте avito.ru в Chrome.", max_wait_sec
        )
        deadline = time.monotonic() + max_wait_sec
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            if p.exists():
                try:
                    new_mtime = p.stat().st_mtime
                except OSError:
                    continue
                if new_mtime > old_mtime:
                    self._reload_cookies()
                    has_avisc = any(c["name"] == "_avisc" for c in (self._base_cookies or []))
                    logger.info("[Авито] куки обновлены: %d шт, _avisc=%s",
                                len(self._base_cookies or []), has_avisc)
                    return True
        logger.warning("[Авито] куки не обновились за %ds", max_wait_sec)
        return False

    def _reload_cookies(self) -> None:
        """Перезагружает куки из файла если он изменился (проверка по mtime)."""
        cookie_path = os.environ.get("AVITO_COOKIES", "").strip()
        if not cookie_path:
            return
        p = Path(cookie_path)
        if not p.exists():
            return
        try:
            mtime = p.stat().st_mtime
        except OSError:
            return
        if mtime <= self._cookie_file_mtime:
            return  # файл не менялся
        self._cookie_file_mtime = mtime
        new_cookies = _load_avito_cookies()
        if new_cookies:
            old_count = len(self._base_cookies or [])
            self._base_cookies = new_cookies
            had_avisc_before = any(c["name"] == "_avisc" for c in ([] if old_count == 0 else []))
            has_avisc = any(c["name"] == "_avisc" for c in new_cookies)
            logger.info(
                "[Авито] куки перезагружены: %d шт, _avisc=%s",
                len(new_cookies), has_avisc
            )

    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        if not self._browser_client:
            return []

        # Динамически перезагружаем куки если файл изменился
        # (Chrome-расширение могло записать новые куки с _avisc)
        self._reload_cookies()

        self._http_counter = 0
        self.last_metrics = None

        url = _SEARCH_URL_TPL.format(query=quote_plus(query))

        t0 = time.monotonic()

        # Если в куках уже есть свежий _avisc (от Chrome-расширения) — пропускаем
        # curl-cffi warm-up. Иначе — получаем _avisc через curl-cffi.
        has_avisc = any(
            c["name"] == "_avisc" and c.get("expires", 0) > time.time()
            for c in (self._base_cookies or [])
        )

        import asyncio
        if has_avisc:
            fresh_cookies = self._base_cookies or []
            logger.debug("[Авито] используем _avisc из Chrome-расширения")
        else:
            fresh_cookies = await asyncio.get_event_loop().run_in_executor(
                None, _get_fresh_qrator_cookies, self._base_cookies
            )

        # Playwright с профилем + инжекция кук
        warm_up = None if has_avisc else "https://www.avito.ru/"
        result = await self._browser_client.fetch(
            url,
            warm_up_url=warm_up,
            wait_until="domcontentloaded",
            timeout_ms=40_000,
            wait_ms=3500,
            stealth=True,
            profile_id="avito",
            evaluate_js=_SEARCH_JS,
            cookies=fresh_cookies,
        )
        self._http_counter = 1
        search_ms = int((time.monotonic() - t0) * 1000)

        status = result.get("status", 0)
        if status in (429, 403):
            # Ждём свежих кук от Chrome-расширения (до 90 сек).
            # Пользователь должен посетить avito.ru в Chrome — расширение
            # автоматически отправит куки включая _avisc на /api/avito/cookies.
            waited = await self._wait_for_fresh_cookies(max_wait_sec=90)
            if waited:
                logger.info("[Авито] куки обновлены, повторяю запрос...")
                result = await self._browser_client.fetch(
                    url,
                    warm_up_url=None,
                    wait_until="domcontentloaded",
                    timeout_ms=40_000,
                    wait_ms=3500,
                    stealth=True,
                    profile_id="avito",
                    evaluate_js=_SEARCH_JS,
                    cookies=self._base_cookies or [],
                )
                status = result.get("status", 0)
            if status in (429, 403):
                raise RuntimeError(
                    f"Авито заблокировал запрос (HTTP {status}). "
                    "Откройте avito.ru в Chrome с установленным расширением "
                    "(services/parsers/chrome-extension) — куки синхронизируются автоматически. "
                    "Или задайте CHROME_CDP_URL для подключения к реальному Chrome."
                )

        evaluated = result.get("evaluated") or {}
        if isinstance(evaluated, list):
            snippets: list[dict] = evaluated
        else:
            page_title = evaluated.get("pageTitle", "")
            blocked = evaluated.get("blocked", False)
            snippets = evaluated.get("items") or []

            if blocked:
                raise RuntimeError(
                    f"Авито: страница заблокирована Qrator (title: {page_title!r}). "
                    "Обновите AVITO_COOKIES."
                )

        if not snippets and result.get("html"):
            snippets = _parse_html_fallback(result["html"], limit)

        products = _build_products(snippets, limit)

        self.last_metrics = ParserMetrics(
            search_ms=search_ms,
            enrich_ms=None,
            http_requests=self._http_counter,
            result_after_enrich=len(products),
        )
        return products


def _build_products(snippets: list[dict], limit: int) -> list[ParsedProduct]:
    products: list[ParsedProduct] = []
    seen: set[str] = set()
    for s in snippets:
        if len(products) >= limit:
            break
        url = s.get("url", "")
        title = s.get("title", "")
        if not url or not title:
            continue
        item_id = str(s.get("itemId") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)

        price_rub = s.get("price")
        price_kopecks = int(price_rub * 100) if price_rub else 0

        raw: dict = {"in_stock": True}
        if s.get("location"):
            raw["location"] = s["location"]
        if s.get("posted_at"):
            raw["posted_at"] = s["posted_at"]

        products.append(ParsedProduct(
            store_slug="avito",
            external_id=item_id,
            title=title,
            price=price_kopecks,
            url=url,
            image_url=s.get("image") or None,
            raw=raw,
        ))
    return products


def _parse_html_fallback(html: str, limit: int) -> list[dict]:
    """HTML-фолбэк когда evaluate_js вернул пустой список."""
    import re
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    results = []

    for item in soup.select("[data-item-id]")[:limit]:
        item_id = item.get("data-item-id", "")
        if not item_id:
            continue
        link = item.select_one(f'a[href*="{item_id}"]') or item.select_one("a[href]")
        if not link:
            continue
        href = link.get("href", "")
        url = f"https://www.avito.ru{href}".split("?")[0] if href.startswith("/") else href
        title_el = item.select_one("[itemprop='name']") or link
        title = (title_el.get("content") or title_el.get_text(strip=True)).strip()
        price_meta = item.select_one("meta[itemprop='price']")
        price = None
        if price_meta:
            digits = re.sub(r"[^\d]", "", price_meta.get("content", ""))
            price = int(digits) if digits else None
        geo_el = item.select_one("[data-marker='item-address']")
        location = geo_el.get_text(strip=True) if geo_el else ""
        results.append({
            "itemId": item_id, "title": title, "url": url,
            "price": price, "image": "", "location": location, "posted_at": "",
        })
    return results
