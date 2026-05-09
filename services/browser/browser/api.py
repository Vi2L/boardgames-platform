"""Browser-as-a-service: headless Chromium через Playwright.

Два режима работы:

1. **Shared browser** (по умолчанию) — один Browser-процесс, новый
   BrowserContext на каждый запрос. Изолированные cookies, быстро.

2. **Persistent profile** (profile_id задан) — отдельный Playwright-процесс
   с PersistentContext для каждого profile_id. Cookies/localStorage сохраняются
   между запросами — ключевой механизм для обхода bot-challenge (Qrator).

Семафор BROWSER_MAX_CONCURRENT ограничивает суммарное число одновременных
запросов независимо от режима.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

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
# "chrome" на AMD64 (облако), "chromium" на ARM64 (Mac Apple Silicon).
# Задаётся через BROWSER_CHANNEL в .env / docker-compose.
_BROWSER_CHANNEL: str | None = os.getenv("BROWSER_CHANNEL") or None
# CDP URL реального Chrome (напр. ws://host.docker.internal:9222).
_CDP_URL: str | None = os.getenv("CHROME_CDP_URL") or None

# Патчим маркеры автоматизации — Авито проверяет их через JS.
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

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--no-first-run",
]


# ---------------------------------------------------------------------------
# Схемы
# ---------------------------------------------------------------------------

class FetchRequest(BaseModel):
    url: str
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "domcontentloaded"
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    extra_headers: dict[str, str] = {}
    stealth: bool = True
    proxy: str | None = None

    # Warm-up: зайти на этот URL перед основным (Авито — прогрев сессии).
    warm_up_url: str | None = None
    # Задержка после основного goto (мс). Даёт странице достроить DOM.
    wait_ms: int = Field(default=0, ge=0, le=15_000)
    # CSS-селектор — ждать появления элемента перед возвратом HTML.
    wait_for_selector: str | None = None
    wait_for_selector_timeout_ms: int = Field(default=15_000, ge=1_000, le=60_000)
    # JS для выполнения в контексте страницы; результат → поле evaluated.
    evaluate_js: str | None = None
    # ID профиля для persistent context (Qrator cookie persistence).
    profile_id: str | None = None
    # Куки для инжекции (формат Playwright: name/value/domain/path/...).
    # Применяются поверх профиля или в свежем контексте. Позволяет передать
    # реальные куки из браузера пользователя для обхода Qrator.
    cookies: list[dict] = []


class FetchResponse(BaseModel):
    html: str
    status: int
    url: str
    headers: dict[str, str]
    cookies: list[dict]
    elapsed_ms: int
    evaluated: Any = None       # результат evaluate_js


# ---------------------------------------------------------------------------
# Persistent profile sessions
# ---------------------------------------------------------------------------

class _PersistentSession:
    """Обёртка над launch_persistent_context для одного profile_id."""

    def __init__(self, profile_dir: Path, proxy: str | None) -> None:
        self.profile_dir = profile_dir
        self.proxy = proxy
        self.lock = asyncio.Lock()
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None

    async def start(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
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
    pw = await async_playwright().start()
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    if _CDP_URL:
        # Режим CDP: подключаемся к реальному Chrome пользователя.
        # Chrome запускается на хосте с --remote-debugging-port=9222.
        # На Mac с Docker Desktop: CHROME_CDP_URL=ws://host.docker.internal:9222
        import logging
        logging.getLogger(__name__).info("CDP mode: connecting to %s", _CDP_URL)
        browser = await pw.chromium.connect_over_cdp(_CDP_URL)
    else:
        launch_kwargs: dict = {"headless": True, "args": _LAUNCH_ARGS}
        if _BROWSER_CHANNEL:
            launch_kwargs["channel"] = _BROWSER_CHANNEL
        browser = await pw.chromium.launch(**launch_kwargs)

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    app.state.browser = browser
    app.state.playwright = pw
    app.state.semaphore = semaphore
    app.state.cdp_mode = bool(_CDP_URL)

    yield

    # Закрываем persistent sessions
    for s in _persistent_sessions.values():
        await s.close()
    _persistent_sessions.clear()

    if not _CDP_URL:
        await browser.close()
    await pw.stop()


app = FastAPI(title="browser-service", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _navigate_page(page, req: FetchRequest) -> Any:
    """Выполнить навигацию + все опциональные шаги. Возвращает (response, evaluated)."""
    effective_proxy = req.proxy or _DEFAULT_PROXY  # noqa: F841 (used via context)

    # Warm-up
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
    browser: Browser = request.app.state.browser
    if not browser.is_connected():
        raise HTTPException(status_code=503, detail="chromium disconnected")
    return {"status": "ok"}


@app.get("/info")
async def info(request: Request):
    from importlib.metadata import version as pkg_version
    browser: Browser = request.app.state.browser
    return {
        "playwright": pkg_version("playwright"),
        "chromium": browser.version,
        "max_concurrent": _MAX_CONCURRENT,
        "proxy_configured": _DEFAULT_PROXY is not None,
        "profiles_dir": str(_PROFILES_DIR),
        "active_profiles": list(_persistent_sessions.keys()),
    }


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
                if req.stealth:
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
                if req.stealth:
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
