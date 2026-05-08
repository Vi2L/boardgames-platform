"""Browser-as-a-service: headless Chromium через Playwright.

Один Browser-процесс на весь lifecycle сервиса (запускается в lifespan).
На каждый запрос создаётся изолированный BrowserContext — собственные
cookies, localStorage, без утечек между клиентами.

Семафор BROWSER_MAX_CONCURRENT ограничивает параллельные контексты:
Chromium тратит ~150-200 MB RAM на контекст, поэтому по умолчанию 3.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from playwright.async_api import Browser, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth
from pydantic import BaseModel, Field

_MAX_CONCURRENT = int(os.getenv("BROWSER_MAX_CONCURRENT", "3"))
# Прокси по умолчанию для всех запросов: SOCKS5/HTTP URL.
# Авито и ряд других сайтов блокируют non-RU IP — без прокси они вернут 429.
# Пример: BROWSER_PROXY_URL=socks5://user:pass@proxy.ru:1080
_DEFAULT_PROXY: str | None = os.getenv("BROWSER_PROXY_URL") or None


# ---------------------------------------------------------------------------
# Схемы запрос / ответ
# ---------------------------------------------------------------------------

class FetchRequest(BaseModel):
    url: str
    # networkidle ждёт, пока сеть затихнет — надёжнее для SPA, но медленнее.
    # load — DOMContentLoaded + ресурсы; быстрее, но SPA может не достроиться.
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "networkidle"
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    extra_headers: dict[str, str] = {}
    # stealth патчит navigator, WebGL и прочие fingerprint-точки через
    # playwright-stealth — основная причина существования этого сервиса.
    stealth: bool = True
    # Переопределить прокси для этого запроса. None = использовать BROWSER_PROXY_URL.
    proxy: str | None = None


class FetchResponse(BaseModel):
    html: str
    status: int
    url: str               # финальный URL после редиректов
    headers: dict[str, str]
    cookies: list[dict]
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Lifespan: Browser стартует один раз, живёт весь lifecycle сервиса
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    app.state.browser = browser
    app.state.playwright = pw
    app.state.semaphore = semaphore

    yield

    await browser.close()
    await pw.stop()


app = FastAPI(title="browser-service", lifespan=lifespan)


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
    """Версии playwright и chromium — полезно для отладки совместимости."""
    from importlib.metadata import version as pkg_version
    browser: Browser = request.app.state.browser
    return {
        "playwright": pkg_version("playwright"),
        "chromium": browser.version,
        "max_concurrent": _MAX_CONCURRENT,
        "proxy_configured": _DEFAULT_PROXY is not None,
    }


@app.post("/fetch", response_model=FetchResponse)
async def fetch(req: FetchRequest, request: Request):
    """Загрузить страницу через headless Chromium и вернуть HTML + cookies + headers.

    Каждый запрос получает изолированный BrowserContext. Семафор ограничивает
    число одновременных контекстов (BROWSER_MAX_CONCURRENT, default 3).
    """
    browser: Browser = request.app.state.browser
    semaphore: asyncio.Semaphore = request.app.state.semaphore

    t0 = time.monotonic()

    async with semaphore:
        effective_proxy = req.proxy or _DEFAULT_PROXY
        context_kwargs = {}
        if effective_proxy:
            context_kwargs["proxy"] = {"server": effective_proxy}
        context = await browser.new_context(**context_kwargs)
        try:
            page = await context.new_page()

            if req.stealth:
                await Stealth().apply_stealth_async(page)

            if req.extra_headers:
                await page.set_extra_http_headers(req.extra_headers)

            try:
                response = await page.goto(
                    req.url,
                    wait_until=req.wait_until,
                    timeout=req.timeout_ms,
                )
            except PlaywrightTimeoutError as exc:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                raise HTTPException(
                    status_code=504,
                    detail=f"timeout {elapsed_ms}ms: {exc}",
                ) from exc
            except PlaywrightError as exc:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                raise HTTPException(
                    status_code=502,
                    detail=f"browser error after {elapsed_ms}ms: {exc}",
                ) from exc

            html = await page.content()
            cookies = await context.cookies()
            final_url = page.url
            elapsed_ms = int((time.monotonic() - t0) * 1000)

        finally:
            await context.close()

    return FetchResponse(
        html=html,
        status=response.status if response else 0,
        url=final_url,
        headers=dict(response.headers) if response else {},
        cookies=cookies,
        elapsed_ms=elapsed_ms,
    )
