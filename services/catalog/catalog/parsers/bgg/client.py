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

# CAT-10: HTML browse-страницы НЕ под /xmlapi2, а на корне сайта.
# Это не XML API, а обычный HTML, без bearer'а, без 202.
BGG_BROWSE_URL = "https://boardgamegeek.com/browse/boardgame"

# 202 Accepted = «запрос принят, попробуйте снова». Стандартный паттерн BGG.
# Кортеж задержек = количество попыток (4 ретрая до фейла).
_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)

# /thing поддерживает множественные ID в одном запросе. По документации BGG —
# до 20 одновременно. Превышение → 414 URI Too Long или silent truncation.
THING_BATCH_MAX = 20

# CAT-10: для HTML-страниц boardgamegeek.com BGG плохо реагирует на запросы без
# реалистичного User-Agent — может вернуть 403 или статическую страницу-капчу.
# Используем актуальный Chrome UA (на 2026-05); обновлять не чаще раза в год.
_BROWSE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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
        """Обёртка `_get_with_backoff` для `/thing` (одиночный и batch)."""
        url = f"{self._base_url}/thing"
        params: dict[str, str | int] = {"id": ",".join(str(i) for i in ids), "stats": 1}
        return await self._get_with_backoff(url, params=params)

    async def _get_with_backoff(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> str:
        """GET с экспоненциальным backoff для 202 (BGG «прогревает кеш»).

        Используется для endpoint'ов которые могут вернуть 202 при первом
        запросе — `/thing`, `/geeklist`, `/collection`, `/plays`.

        Логика: N=`len(_RETRY_DELAYS)` попыток подряд с sleep между ними,
        потом ОДНА финальная попытка после последнего sleep'а. Без финальной
        попытки последний sleep был бы потрачен впустую (мы бы засыпали и
        тут же поднимали ошибку без проверки). Итого до N+1 попытки.
        """
        client = await self._ensure_client()
        for delay in _RETRY_DELAYS:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return response.text
            if response.status_code == 202:
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()

        # Финальная попытка после последнего sleep'а из цикла.
        response = await client.get(url, params=params)
        if response.status_code == 200:
            return response.text
        response.raise_for_status()
        raise httpx.HTTPError(
            f"BGG не отдал данные за {len(_RETRY_DELAYS) + 1} попыток"
        )

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

    async def fetch_family(self, family_id: int) -> str:
        """CAT-8: GET `/xmlapi2/family/{id}` → raw XML тематической семьи BGG.

        Family — это связанная группа игр (Catan series, Carcassonne series,
        etc.). Endpoint возвращает список thing-id членов семьи + name +
        description семьи. Используется для cascade-обогащения и периодического
        refresh'а через bgg_family_refresh scheduler-job.

        Поведение 202 — иногда «прогревает кеш» как `/thing` и `/geeklist`,
        поэтому идём через `_get_with_backoff`.
        """
        return await self._get_with_backoff(f"{self._base_url}/family/{family_id}")

    async def fetch_geeklist(self, geeklist_id: int) -> str:
        """GET `/xmlapi2/geeklist/{id}` → raw XML кураторского списка.

        BGG GeekList — кураторский список thing-id с заголовком, описанием и
        опциональным комментарием на каждую позицию. Используется для
        monthly «BGG Top 50 Most Played» (id типа 367126) и любых других топов.

        `/geeklist/{id}` иногда возвращает 202 при «прогреве» — поэтому идём
        через `_get_with_backoff` как `/thing`.
        """
        return await self._get_with_backoff(f"{self._base_url}/geeklist/{geeklist_id}")

    async def fetch_browse_year(self, year: int, page: int = 1) -> str:
        """CAT-10: GET HTML страницы `/browse/boardgame?sort=numvoters&yearpublished=YYYY&page=N`.

        BGG XML API не отдаёт фильтр по году + сортировку по numvoters — нужно скрейпить
        HTML. Bearer для browse-страниц не нужен (по обсуждениям BGG-форума работает
        без токена), но реалистичный User-Agent обязателен — иначе 403/капча.

        Не использует backoff на 202 — browse-страницы их не возвращают; любая
        ошибка сразу поднимет httpx.HTTPError.

        100 игр на страницу (стандарт BGG); максимум 10 страниц = топ-1000 года.
        """
        client = await self._ensure_client()
        params: dict[str, str | int] = {
            "sort": "numvoters",
            "yearpublished": year,
            "page": page,
        }
        # Подменяем UA для browse — XML API ходит без UA (там Bearer достаточно).
        response = await client.get(
            BGG_BROWSE_URL,
            params=params,
            headers={"User-Agent": _BROWSE_USER_AGENT, "Accept": "text/html"},
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
