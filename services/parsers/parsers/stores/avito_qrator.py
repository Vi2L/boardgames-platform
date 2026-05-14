"""AvitoQratorClient — обход Qrator на avito.ru через TLS-impersonation.

Стратегия L0 из roadmap «Avito container-only» (см. devlog 2026-05-14).

Ключевое открытие: avito.ru перешёл на CSR, и **публичный JSON-endpoint**
`/web/1/js/items` отдаёт результаты поиска в типизированном JSON. Этот же
endpoint дёргает фронт avito.ru после загрузки страницы — никакого
reverse-engineering мобильного API.

Главная инженерная задача — заставить Qrator пустить нас:
- TLS Client Hello (JA3/JA4 + GREASE) должен совпадать с настоящим Chrome.
  Это даёт ``curl-cffi`` с ``impersonate="chrome124"``.
- В сессии должна быть свежая кука ``_avisc`` (Max-Age=60). Её ставит Qrator
  при первом легитимном GET `/`. Дальше её используем для всех XHR-запросов.

Архитектура клиента:

* Один `AsyncSession` на инстанс — переиспользует TCP/TLS, не каждый раз
  делает handshake.
* Внутренний cookie-jar — curl-cffi сама накапливает Set-Cookie между
  запросами. Дополнительно сохраняем `expires` для `_avisc`, чтобы знать,
  когда пора рефрешить.
* `asyncio.Lock` на cold-start — параллельные вызовы не плодят `GET /`.
* `refresh_if_stale()` вызывается перед каждым `search()` — авторефрешит
  `_avisc`, если она протухла или вот-вот протухнет.

Что НЕ умеет (намеренно):
* Не работает с прокси на уровне клиента — `curl-cffi` принимает `proxy=`
  в `request()`, и при необходимости можно прокинуть, но для MVP не нужно.
* Не парсит HTML страницы — только JSON-endpoint. Если Qrator однажды
  закроет этот endpoint, надо будет писать L1-фоллбэк через camoufox.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# Max-Age _avisc = 60s. Рефрешим за 10s до истечения, чтобы не словить race
# между «проверка свежая» и фактическим запросом.
_AVISC_REFRESH_BEFORE_SEC = 10

# Headers близкие к настоящему Chrome 124 на macOS. sec-ch-* hints
# Qrator активно проверяет — без них быстро попадаем в challenge.
_HOME_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-Ch-Ua": (
        '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'
    ),
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# XHR-запросы фронт avito делает с этими специфичными заголовками.
# Без `X-Source: desktop` endpoint /web/1/js/items может вернуть 403.
_XHR_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-Ch-Ua": _HOME_HEADERS["Sec-Ch-Ua"],
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": _HOME_HEADERS["User-Agent"],
    "X-Source": "desktop",
}


class AvitoQratorError(RuntimeError):
    """Сигнал, что Qrator заблокировал запрос. Несёт http-статус для решений
    верхнего уровня (например, перейти на L1-fallback через браузер).
    """

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class AvitoQratorClient:
    """L0-клиент к avito.ru — curl-cffi + ротация `_avisc`.

    Не является `StoreParser` сам по себе — это инфраструктурный слой,
    `AvitoParser` дёргает `search_items()` и собирает `ParsedProduct`.
    """

    BASE = "https://www.avito.ru"
    HOME = BASE + "/"
    SEARCH_API = BASE + "/web/1/js/items"

    def __init__(self) -> None:
        # Lazy import — позволяет тестам мокать curl-cffi без обязательного
        # наличия libcurl в окружении тестов.
        from curl_cffi.requests import AsyncSession

        self._session: AsyncSession = AsyncSession(impersonate="chrome124")
        # Когда `_avisc` в куках устаревает (unix ts). 0 = ещё не получали.
        self._avisc_expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._session.close()

    # ---------------------------------------------------------------------
    # Cookie lifecycle
    # ---------------------------------------------------------------------

    def _has_fresh_avisc(self) -> bool:
        """`_avisc` существует и не истечёт в ближайшие 10 сек."""
        return self._avisc_expires_at - time.time() > _AVISC_REFRESH_BEFORE_SEC

    async def _cold_start(self) -> None:
        """GET https://www.avito.ru/ — Qrator ставит свежий `_avisc`.

        Делается под `self._lock` чтобы параллельные `search()` не плодили
        одинаковых cold-start'ов.
        """
        logger.debug("[avito-qrator] cold-start GET /")
        resp = await self._session.get(
            self.HOME, headers=_HOME_HEADERS, timeout=20, allow_redirects=True,
        )
        if resp.status_code != 200:
            raise AvitoQratorError(
                resp.status_code,
                f"cold-start failed: HTTP {resp.status_code}",
            )

        # `_avisc` пришёл? Если нет — challenge page, дальше идти нет смысла.
        # curl-cffi автоматически добавляет куки в jar, читаем оттуда.
        avisc_seen = False
        for cookie in self._session.cookies.jar:
            if cookie.name == "_avisc":
                avisc_seen = True
                # expires может быть None если кука session-only — это плохо
                # (значит Qrator не доверяет нам), но кладём хотя бы +60s.
                self._avisc_expires_at = cookie.expires or (time.time() + 60)
                break

        if not avisc_seen:
            raise AvitoQratorError(
                resp.status_code,
                "cold-start: Qrator не выдал _avisc — likely challenge page",
            )
        logger.info(
            "[avito-qrator] cold-start OK, _avisc expires in %.0fs",
            self._avisc_expires_at - time.time(),
        )

    async def refresh_if_stale(self) -> None:
        """Гарантирует, что `_avisc` в куках не протухла. Безопасно
        вызывать перед каждым `search_items`."""
        if self._has_fresh_avisc():
            return
        async with self._lock:
            # Двойная проверка — пока ждали лок, другой таск мог обновить.
            if self._has_fresh_avisc():
                return
            await self._cold_start()

    # ---------------------------------------------------------------------
    # Search
    # ---------------------------------------------------------------------

    async def search_items(self, query: str, *, sort: int = 104) -> dict[str, Any]:
        """Дёргает `/web/1/js/items` и возвращает распарсенный JSON.

        sort=104 — «по дате» (новые сверху), как в прежнем `_SEARCH_URL_TPL`.

        Стратегия retry: при 429/403 (Qrator забанил) один раз пробуем
        пересоздать сессию (новый cookie-jar, новый cold-start) и повторить
        запрос. Двух попыток обычно достаточно: первая может попасть на
        протухший edge-cache `_avisc`, вторая всегда стартует с чистого
        состояния. Дальше — отдаём ошибку наверх.
        """
        last_exc: AvitoQratorError | None = None
        for attempt in range(2):
            try:
                return await self._search_items_once(query, sort=sort)
            except AvitoQratorError as exc:
                last_exc = exc
                if exc.status not in (429, 403) or attempt == 1:
                    raise
                logger.warning(
                    "[avito-qrator] HTTP %d on attempt %d — пересоздаю "
                    "cookie-jar и повторяю", exc.status, attempt + 1,
                )
                await self._reset_session()
        # Недостижимо — последний цикл обязательно бросит, но mypy спокоен.
        raise last_exc  # type: ignore[misc]

    async def _search_items_once(self, query: str, *, sort: int) -> dict[str, Any]:
        await self.refresh_if_stale()

        params = {"q": query, "s": str(sort)}
        # Полный URL поиска кладём в Referer — фронт avito ставит именно его.
        referer = f"{self.BASE}/rossiya?q={quote_plus(query)}&s={sort}"
        headers = {**_XHR_HEADERS, "Referer": referer, "Origin": self.BASE}

        t0 = time.monotonic()
        resp = await self._session.get(
            self.SEARCH_API, headers=headers, params=params, timeout=20,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.debug(
            "[avito-qrator] /web/1/js/items q=%r → HTTP %d in %dms",
            query, resp.status_code, elapsed_ms,
        )

        if resp.status_code in (429, 403):
            raise AvitoQratorError(
                resp.status_code,
                f"Qrator blocked /web/1/js/items: HTTP {resp.status_code}",
            )
        if resp.status_code >= 500:
            raise AvitoQratorError(
                resp.status_code, f"upstream 5xx: HTTP {resp.status_code}",
            )
        if resp.status_code != 200:
            raise AvitoQratorError(
                resp.status_code, f"unexpected HTTP {resp.status_code}",
            )

        try:
            return resp.json()
        except Exception as exc:
            raise AvitoQratorError(
                resp.status_code, f"невалидный JSON в ответе: {exc}",
            ) from exc

    async def _reset_session(self) -> None:
        """Пересоздаёт `AsyncSession` с пустым cookie-jar.

        Нужно, если Qrator забанил конкретный набор кук (`_avisc` + `u` +
        `srv_id` могут быть помечены подозрительными). Чистый старт сбрасывает
        весь history-маркер.
        """
        from curl_cffi.requests import AsyncSession

        async with self._lock:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = AsyncSession(impersonate="chrome124")
            self._avisc_expires_at = 0.0
