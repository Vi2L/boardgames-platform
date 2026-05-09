"""Browser-as-a-service: Camoufox (primary) + Playwright (fallback).

Два backend'а, переключаемых через BROWSER_BACKEND env var:

1. **camoufox** (default) — Firefox с C++-level fingerprint patches.
   Обходит Qrator и аналогичные anti-bot системы без JS-патчинга.
   headless="virtual" использует встроенный Xvfb — скрывает headless-маркеры.

2. **playwright** (fallback) — Playwright Chromium/Chrome. Работает для сайтов
   без жёсткого bot-detection. Может быть заблокирован Qrator на avito.ru.

Три режима навигации (общие для обоих backend'ов):

A. **Shared browser** (profile_id не задан) — новый BrowserContext на каждый запрос.
B. **Persistent profile** (profile_id задан) — один контекст на profile_id,
   cookies/localStorage сохраняются между запросами.
C. **CDP mode** (CHROME_CDP_URL задан) — подключение к реальному Chrome по CDP.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from camoufox.async_api import AsyncCamoufox
from fastapi import FastAPI, HTTPException, Request
from playwright.async_api import (
    Browser, BrowserContext, Playwright,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth
from pydantic import BaseModel, Field

_MAX_CONCURRENT = int(os.getenv("BROWSER_MAX_CONCURRENT", "3"))
_DEFAULT_PROXY: str | None = os.getenv("BROWSER_PROXY_URL") or None
_PROFILES_DIR = Path(os.getenv("BROWSER_PROFILES_DIR", "/data/profiles"))
# "camoufox" (default) — Firefox + C++-level anti-detect, работает в Docker.
# "playwright" — Chromium fallback, требует playwright install в Dockerfile.
_BROWSER_BACKEND = os.getenv("BROWSER_BACKEND", "camoufox")
# Только для playwright-fallback: "chrome" или "chromium".
_BROWSER_CHANNEL: str | None = os.getenv("BROWSER_CHANNEL") or None
# CDP URL реального Chrome (напр. ws://host.docker.internal:9222).
_CDP_URL: str | None = os.getenv("CHROME_CDP_URL") or None

# Playwright-only stealth JS (не нужен для camoufox — патчится на C++ уровне).
_STEALTH_JS = """\
try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch(e) {}
if (!window.chrome) window.chrome = {};
if (!window.chrome.runtime) window.chrome.runtime = {};
try {
    Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU','ru','en-US','en'] });
} catch(e) {}
try {
    const _q = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = p => p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission }) : _q(p);
} catch(e) {}
"""

# Playwright-only launch args.
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--no-first-run",
]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FetchRequest(BaseModel):
    url: str
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "domcontentloaded"
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    extra_headers: dict[str, str] = {}
    stealth: bool = True
    proxy: str | None = None

    warm_up_url: str | None = None
    wait_ms: int = Field(default=0, ge=0, le=15_000)
    wait_for_selector: str | None = None
    wait_for_selector_timeout_ms: int = Field(default=15_000, ge=1_000, le=60_000)
    evaluate_js: str | None = None
    profile_id: str | None = None
    # Куки для инжекции (формат Playwright: name/value/domain/path/...).
    cookies: list[dict] = []


class FetchResponse(BaseModel):
    html: str
    status: int
    url: str
    headers: dict[str, str]
    cookies: list[dict]
    elapsed_ms: int
    evaluated: Any = None


# ---------------------------------------------------------------------------
# Persistent profile sessions
# ---------------------------------------------------------------------------

class _PersistentSession:
    """Persistent browser context для одного profile_id.

    Camoufox path: AsyncCamoufox(persistent_context=True, user_data_dir=...).
    Playwright path: launch_persistent_context (как раньше).
    """

    def __init__(self, profile_dir: Path, proxy: str | None) -> None:
        self.profile_dir = profile_dir
        self.proxy = proxy
        self.lock = asyncio.Lock()
        # Camoufox fields
        self._cam: AsyncCamoufox | None = None
        # Playwright fields (fallback)
        self._pw: Playwright | None = None
        # Общий: BrowserContext (оба path возвращают совместимый объект)
        self._ctx: BrowserContext | None = None

    async def start(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        if _BROWSER_BACKEND == "camoufox":
            cam_kwargs: dict = {
                "headless": "virtual",   # Xvfb: скрывает headless-маркеры
                "persistent_context": True,
                "user_data_dir": str(self.profile_dir),
            }
            if self.proxy:
                cam_kwargs["proxy"] = {"server": self.proxy}
            self._cam = AsyncCamoufox(**cam_kwargs)
            # __aenter__ возвращает BrowserContext (как playwright's launch_persistent_context)
            self._ctx = await self._cam.__aenter__()
            # Fingerprint патчится на C++ уровне — add_init_script не нужен
        else:
            # Playwright fallback (без изменений)
            self._pw = await async_playwright().start()
            kwargs: dict = {
                "headless": True,
                "args": _LAUNCH_ARGS,
                "viewport": {"width": 1366, "height": 768},
                "user_agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "locale": "ru-RU",
                "extra_http_headers": {"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8"},
            }
            if self.proxy:
                kwargs["proxy"] = {"server": self.proxy}
            if _BROWSER_CHANNEL:
                kwargs["channel"] = _BROWSER_CHANNEL
            self._ctx = await self._pw.chromium.launch_persistent_context(
                str(self.profile_dir), **kwargs,
            )
            await self._ctx.add_init_script(_STEALTH_JS)

    async def close(self) -> None:
        if self._cam:
            # __aexit__ закрывает и context, и Firefox процесс
            await self._cam.__aexit__(None, None, None)
        else:
            if self._ctx:
                await self._ctx.close()
            if self._pw:
                await self._pw.stop()

    @property
    def ctx(self) -> BrowserContext:
        assert self._ctx is not None
        return self._ctx


# dict profile_id → session (создаются лениво)
_persistent_sessions: dict[str, _PersistentSession] = {}
_sessions_create_lock = asyncio.Lock()


async def _get_persistent_session(profile_id: str, proxy: str | None) -> _PersistentSession:
    async with _sessions_create_lock:
        if profile_id not in _persistent_sessions:
            s = _PersistentSession(_PROFILES_DIR / profile_id, proxy)
            await s.start()
            _persistent_sessions[profile_id] = s
        return _persistent_sessions[profile_id]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    if _CDP_URL:
        # CDP mode: подключаемся к реальному Chrome.
        # BROWSER_BACKEND игнорируется — всегда используется playwright CDP.
        pw = await async_playwright().start()
        import logging
        logging.getLogger(__name__).info("CDP mode: connecting to %s", _CDP_URL)
        browser = await pw.chromium.connect_over_cdp(_CDP_URL)
        app.state.playwright = pw
        app.state.cam_cm = None

    elif _BROWSER_BACKEND == "camoufox":
        # Camoufox shared browser (один Browser, новый context на запрос)
        cam_cm = AsyncCamoufox(headless="virtual")
        browser = await cam_cm.__aenter__()   # возвращает Browser-совместимый объект
        app.state.playwright = None
        app.state.cam_cm = cam_cm

    else:
        # Playwright fallback
        pw = await async_playwright().start()
        launch_kwargs: dict = {"headless": True, "args": _LAUNCH_ARGS}
        if _BROWSER_CHANNEL:
            launch_kwargs["channel"] = _BROWSER_CHANNEL
        browser = await pw.chromium.launch(**launch_kwargs)
        app.state.playwright = pw
        app.state.cam_cm = None

    app.state.browser = browser
    app.state.semaphore = semaphore
    app.state.cdp_mode = bool(_CDP_URL)

    yield

    # Закрываем persistent sessions
    for s in _persistent_sessions.values():
        await s.close()
    _persistent_sessions.clear()

    if app.state.cam_cm:
        await app.state.cam_cm.__aexit__(None, None, None)
    else:
        if not _CDP_URL:
            await browser.close()
        if app.state.playwright:
            await app.state.playwright.stop()


app = FastAPI(title="browser-service", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _navigate_page(page, req: FetchRequest) -> Any:
    """Навигация + опциональные шаги. Возвращает (response, evaluated)."""
    if req.warm_up_url:
        try:
            await page.goto(req.warm_up_url, wait_until="domcontentloaded", timeout=req.timeout_ms)
            await page.wait_for_timeout(1200)
        except (PlaywrightTimeoutError, PlaywrightError):
            pass  # warm-up failure не критична

    t0 = time.monotonic()

    try:
        response = await page.goto(req.url, wait_until=req.wait_until, timeout=req.timeout_ms)
    except PlaywrightTimeoutError as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        raise HTTPException(status_code=504, detail=f"timeout {elapsed_ms}ms: {exc}") from exc
    except PlaywrightError as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        raise HTTPException(status_code=502, detail=f"browser error {elapsed_ms}ms: {exc}") from exc

    if req.wait_ms:
        await page.wait_for_timeout(req.wait_ms)

    if req.wait_for_selector:
        try:
            await page.wait_for_selector(req.wait_for_selector, timeout=req.wait_for_selector_timeout_ms)
        except PlaywrightTimeoutError:
            pass

    evaluated = None
    if req.evaluate_js:
        try:
            evaluated = await page.evaluate(req.evaluate_js)
        except PlaywrightError:
            pass

    return response, evaluated


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health(request: Request):
    browser = request.app.state.browser
    if not browser.is_connected():
        raise HTTPException(status_code=503, detail="browser disconnected")
    return {"status": "ok"}


@app.get("/info")
async def info(request: Request):
    from importlib.metadata import version as pkg_version
    browser = request.app.state.browser
    result: dict = {
        "backend": _BROWSER_BACKEND,
        "max_concurrent": _MAX_CONCURRENT,
        "proxy_configured": _DEFAULT_PROXY is not None,
        "profiles_dir": str(_PROFILES_DIR),
        "active_profiles": list(_persistent_sessions.keys()),
    }
    if _BROWSER_BACKEND == "camoufox" and not _CDP_URL:
        result["camoufox"] = pkg_version("camoufox")
    else:
        try:
            result["playwright"] = pkg_version("playwright")
            result["chromium"] = browser.version
        except Exception:
            pass
    return result


@app.post("/fetch", response_model=FetchResponse)
async def fetch(req: FetchRequest, request: Request):
    semaphore: asyncio.Semaphore = request.app.state.semaphore
    effective_proxy = req.proxy or _DEFAULT_PROXY

    async with semaphore:
        t_total = time.monotonic()

        if req.profile_id:
            # ── Persistent profile mode ──────────────────────────────────
            session = await _get_persistent_session(req.profile_id, effective_proxy)
            async with session.lock:
                page = await session.ctx.new_page()
                # Stealth применяется только для playwright (camoufox — на C++ уровне)
                if req.stealth and _BROWSER_BACKEND != "camoufox":
                    await Stealth().apply_stealth_async(page)
                if req.cookies:
                    await session.ctx.add_cookies(req.cookies)
                if req.extra_headers:
                    await page.set_extra_http_headers(req.extra_headers)
                try:
                    response, evaluated = await _navigate_page(page, req)
                    html = await page.content()
                    cookies = await session.ctx.cookies()
                    final_url = page.url
                finally:
                    await page.close()
        else:
            # ── Shared browser mode (per-request context) ────────────────
            context_kwargs: dict = {}
            if effective_proxy:
                context_kwargs["proxy"] = {"server": effective_proxy}
            context = await request.app.state.browser.new_context(**context_kwargs)
            try:
                page = await context.new_page()
                if req.stealth and _BROWSER_BACKEND != "camoufox":
                    await Stealth().apply_stealth_async(page)
                if req.cookies:
                    await context.add_cookies(req.cookies)
                if req.extra_headers:
                    await page.set_extra_http_headers(req.extra_headers)
                response, evaluated = await _navigate_page(page, req)
                html = await page.content()
                cookies = await context.cookies()
                final_url = page.url
            finally:
                await context.close()

        elapsed_ms = int((time.monotonic() - t_total) * 1000)

    return FetchResponse(
        html=html,
        status=response.status if response else 0,
        url=final_url,
        headers=dict(response.headers) if response else {},
        cookies=cookies,
        elapsed_ms=elapsed_ms,
        evaluated=evaluated,
    )
