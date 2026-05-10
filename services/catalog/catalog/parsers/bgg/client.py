"""Тонкий httpx-клиент к BGG XML API v2.

Что делает:
- HTTP GET с правильными параметрами (`/thing`, `/search`).
- Обработка `202 Accepted` через экспоненциальный backoff (паттерн BGG:
  «запрос принят, попробуйте снова»).
- Группировка ID по 20 для batch-запроса `/thing?id=1,2,3,...,20` (этап 2).
- Опциональный rate-limit через `asyncio.Semaphore` (по умолчанию выключен —
  BGG не публикует жёсткий лимит, ~1 req/sec — рекомендация, см. wiki).

Не делает:
- Парсинг XML — это `parser.py`.
- Запись в БД — это `repository.py`.
- Оркестрация (search → fetch → upsert) — это `service.py`.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable

import httpx

BGG_BASE_URL = "https://boardgamegeek.com/xmlapi2"

# 202 Accepted = «запрос принят, попробуйте снова». Стандартный паттерн BGG.
# Кортеж задержек = количество попыток (4 ретрая до фейла).
_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)

# /thing поддерживает множественные ID в одном запросе. По документации BGG —
# до 20 одновременно. Превышение → 414 URI Too Long или silent truncation.
THING_BATCH_MAX = 20


class BggClient:
    """Async-клиент BGG XML API.

    Поддерживает context manager: `async with BggClient() as bgg: ...`.
    Можно передать готовый `httpx.AsyncClient` (например, в тестах с
    `MockTransport`) — тогда client его не закрывает.

    `api_token` — Bearer-токен для BGG XML API v2 (обязателен с 2025-го).
    Без токена запросы вернут 401. Передаётся в заголовке Authorization.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        base_url: str = BGG_BASE_URL,
        timeout: float = 30.0,
        api_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        # Создаём свой client лениво в __aenter__, чтобы не делать сетевых
        # инициализаций при простом конструировании (важно для тестов).
        self._client: httpx.AsyncClient | None = client
        self._timeout = timeout
        self._api_token = api_token

    @classmethod
    def from_settings(cls) -> "BggClient":
        """Фабрика: создаёт клиент с токеном из Settings (singleton через lru_cache).

        Используется вне FastAPI DI-контекста: в scheduler'е и importers.
        Тесты переопределяют через `app.dependency_overrides` или передают
        готовый `httpx.AsyncClient` с MockTransport напрямую в конструктор.
        """
        from catalog.config import get_settings
        return cls(api_token=get_settings().bgg_api_token)

    async def __aenter__(self) -> "BggClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=self._auth_headers(),
            )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _auth_headers(self) -> dict[str, str]:
        if self._api_token:
            return {"Authorization": f"Bearer {self._api_token}"}
        return {}

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=self._auth_headers(),
            )
            self._owns_client = True
        return self._client

    async def fetch_thing(self, bgg_id: int) -> str:
        """GET `/thing?id=<bgg_id>&stats=1` → raw XML.

        Обрабатывает 202 (BGG прогревает кеш) c экспоненциальным backoff.
        Поднимает `httpx.HTTPError` если за все ретраи не дождались 200.
        """
        return await self._fetch_thing_url(ids=(bgg_id,))

    async def fetch_things(self, bgg_ids: Iterable[int]) -> str:
        """GET `/thing?id=<id1,id2,...>&stats=1` (batch до 20 ID).

        Превышение `THING_BATCH_MAX` → ValueError. Разбиение на пачки —
        ответственность вызывающего (`service.enrich_batch` в этапе 2).
        """
        ids = list(bgg_ids)
        if not ids:
            raise ValueError("bgg_ids пуст")
        if len(ids) > THING_BATCH_MAX:
            raise ValueError(
                f"bgg_ids превышает лимит batch={THING_BATCH_MAX}; "
                f"разбейте на пачки в вызывающем коде"
            )
        return await self._fetch_thing_url(ids=tuple(ids))

    async def _fetch_thing_url(self, *, ids: tuple[int, ...]) -> str:
        """Общий код для одиночного и batch-запроса с 202-backoff."""
        client = await self._ensure_client()
        url = f"{self._base_url}/thing"
        params = {"id": ",".join(str(i) for i in ids), "stats": 1}
        for delay in _RETRY_DELAYS:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return response.text
            if response.status_code == 202:
                # BGG прогревает кеш — ждём и пробуем снова.
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
        raise httpx.HTTPError(f"BGG не отдал данные за {len(_RETRY_DELAYS)} попыток")

    async def fetch_hot(self) -> str:
        """GET `/hot?type=boardgame` → raw XML со списком 50 «горячих» игр.

        BGG обновляет hotness ежедневно. Endpoint не возвращает 202, поэтому
        backoff не нужен — любой не-200 ответ сразу поднимет исключение.
        """
        client = await self._ensure_client()
        response = await client.get(
            f"{self._base_url}/hot", params={"type": "boardgame"}
        )
        response.raise_for_status()
        return response.text

    async def search(self, query: str, *, exact: bool = False) -> str:
        """GET `/search?query=<q>&type=boardgame[&exact=1]` → raw XML.

        Параметр `exact=1` фильтрует только полное совпадение по primary
        name. Для оператора в UI обычно нужен fuzzy (exact=False) — иначе
        «карк» не найдёт «Каркассон».
        """
        client = await self._ensure_client()
        url = f"{self._base_url}/search"
        params: dict[str, str | int] = {"query": query, "type": "boardgame"}
        if exact:
            params["exact"] = 1
        response = await client.get(url, params=params)
        # /search не возвращает 202 (документировано BGG). Любая ошибка → exception.
        response.raise_for_status()
        return response.text


async def fetch_bgg_thing(
    bgg_id: int, client: httpx.AsyncClient | None = None
) -> str:
    """Legacy-функция — обёртка для обратной совместимости.

    Используется в `routers/imports.py` через shim `catalog.importers.bgg`.
    Новый код должен использовать `BggClient` напрямую.

    `client` — опциональный внешний httpx.AsyncClient (используется в тестах
    с MockTransport; в prod всегда None, и создаётся клиент с токеном из Settings).
    """
    if client is not None:
        # Тесты: используем готовый mock-клиент без auth-настройки.
        async with BggClient(client=client) as bgg:
            return await bgg.fetch_thing(bgg_id)
    async with BggClient.from_settings() as bgg:
        return await bgg.fetch_thing(bgg_id)
