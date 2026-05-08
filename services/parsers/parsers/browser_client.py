"""Тонкий httpx-клиент к services/browser/ (browser-as-a-service).

Используется парсерами, которым нужен JS-rendered HTML или обход
антибот-защиты. Остальные парсеры продолжают использовать httpx напрямую.

Активируется при наличии env BROWSER_SERVICE_URL. Если URL не задан —
клиент не создаётся, нулевой оверхед.

Пример использования в парсере:
    result = await app.state.browser_client.fetch(
        url, wait_until="load", timeout_ms=20_000,
    )
    html = result["html"]
"""
from __future__ import annotations

import httpx


class BrowserServiceError(RuntimeError):
    """Структурированная ошибка от browser-сервиса."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail or f"browser-service HTTP {status_code}")


class BrowserClient:
    """Клиент к POST /fetch → {html, status, url, headers, cookies, elapsed_ms}."""

    def __init__(self, base_url: str, timeout: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        # timeout с запасом над максимальным timeout_ms=120с в browser-сервисе
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(
        self,
        url: str,
        *,
        wait_until: str = "networkidle",
        timeout_ms: int = 30_000,
        extra_headers: dict[str, str] | None = None,
        stealth: bool = True,
        proxy: str | None = None,
        wait_for_selector: str | None = None,
        wait_for_selector_timeout_ms: int = 15_000,
    ) -> dict:
        """POST /fetch → словарь с ключами:
            html, status, url, headers, cookies, elapsed_ms.

        wait_for_selector: CSS-селектор, появление которого означает «контент загружен».
        Используется для сайтов с bot-challenge (Qrator, Cloudflare) — позволяет
        дождаться реальных данных после автоматического прохождения JS-challenge.

        Raises BrowserServiceError при HTTP-ошибке browser-сервиса.
        """
        payload: dict = {
            "url": url,
            "wait_until": wait_until,
            "timeout_ms": timeout_ms,
            "stealth": stealth,
        }
        if extra_headers:
            payload["extra_headers"] = extra_headers
        if proxy:
            payload["proxy"] = proxy
        if wait_for_selector:
            payload["wait_for_selector"] = wait_for_selector
            payload["wait_for_selector_timeout_ms"] = wait_for_selector_timeout_ms

        resp = await self._client.post("/fetch", json=payload)
        if resp.is_error:
            detail = _extract_detail(resp) or f"HTTP {resp.status_code}"
            raise BrowserServiceError(resp.status_code, detail)
        return resp.json()

    async def health(self) -> bool:
        """GET /health → True если browser-сервис доступен."""
        try:
            resp = await self._client.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False


def _extract_detail(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text[:500] if text else None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    return None
