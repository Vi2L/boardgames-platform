# Wishlist для пакета `parsers`

Это техническое задание на улучшения внешнего пакета
`/Users/vitaliy/Projects/parsers/`, которые **не реализуются в этом
репозитории** (parsers_web_test). Каждое — обоснованная необходимость,
без которой соответствующая фаза дебаг-портала вынужденно ограничена
или использует обходные пути.

Документ синхронизирован с планом
`~/.claude/plans/sunny-munching-hammock.md` (контекст архитектуры).

---

## 1. `external_id` в ответе `/search` и `/products/{id}`

**Что:** добавить поле `external_id: str` в `_product_to_dict`
(`parsers/parsers/api.py:106`) и в любой будущий ответ с продуктом.

**Зачем:** портал во фазе 4 (snapshots, regression diff) использует
устойчивый ключ продукта для сопоставления записей между прогонами:

```
key = sku → normalized_title → product_id   (текущая эвристика)
```

`product_id` нестабилен (пересоздание БД меняет id). `sku` есть не у всех
магазинов. `external_id` (id товара в магазине) уже хранится в БД parsers
(`products.external_id`) и идеально стабилен — нужно только пробросить
наружу.

**Сигнатура:**
```python
{
  "id": 123,
  "external_id": "UT-00018963",   # ← новое
  "store_slug": "hobbygames",
  "title": "...",
  ...
}
```

**Эффект на портал:** `app/diff.py:product_key` упрощается до
`f"{slug}:{external_id}"`, эвристика выкидывается.

---

## 2. `GET /products` — пагинированный список

**Что:** новый эндпоинт `GET /products` с параметрами:
- `q: str` (опц.) — фильтр по `normalized_title`;
- `store: str` (опц.) — slug магазина;
- `page: int = 1`, `page_size: int = 50` (max 200);
- `sort: 'fetched_desc' | 'price_asc' | 'price_desc' | 'title_asc' = 'fetched_desc'`;

**Возвращает:**
```json
{
  "items": [ProductOut, ...],   // те же поля, что в /search
  "total": 12345,
  "page": 1,
  "page_size": 50
}
```

**SQL:** `SELECT ... FROM products p LEFT JOIN price_observations po
ON po.product_id = p.id ...` с `ROW_NUMBER() OVER (PARTITION BY p.id
ORDER BY po.fetched_at DESC) = 1` для последней цены.

**Зачем:** фаза 3 (DatabasePage). Сейчас портал держит свой локальный
кеш `local_products` в `data/portal.sqlite`, который дублирует БД
parsers и пополняется только из запросов, прошедших через сам портал.
Это нормальный workaround, но настоящая БД magазинов — у parsers.

---

## 3. `GET /products/{id}` — единичный товар + последние N точек

**Что:** возвращает полный `ProductOut` плюс последние 30 точек
`PricePointOut` (поле `observations`).

```json
{
  "id": 123, "external_id": "...", "store_slug": "...", "title": "...",
  ...,
  "observations": [
    {"price": 199000, "fetched_at": "2026-05-07T10:00:00Z"},
    ...
  ]
}
```

**Зачем:** ProductPage с deep-link (`/products/:id` на портале) сейчас
склеивает данные из локального кеша + `/history/{id}`. Это два запроса
вместо одного и работает только если товар хоть раз искали через портал.

---

## 4. `GET /requests` — журнал поисковых запросов

**Что:** пагинированный список из таблицы `request_log` (она уже есть
в БД parsers, заполняется в `service.py:54`).

```json
{
  "items": [
    {
      "id": 1, "query": "Каркассон", "source": "cache",
      "result_count": 8, "error_count": 0, "duration_ms": 4230,
      "errors_json": "{}", "ts": "2026-05-07T10:00:00Z"
    }
  ],
  "total": ..., "page": ..., "page_size": ...
}
```

**Зачем:** вкладка «Журнал поисков» на DatabasePage. Сейчас портал ведёт
свой локальный лог `local_searches`, но он покрывает только запросы,
сделанные через сам портал — а в БД parsers есть полная история всех
вызовов из любых клиентов.

---

## 5. `DELETE /products/{id}` — удаление товара и его observations

**Что:** удаляет `products(id)` каскадом удаляя `price_observations
WHERE product_id = id`.

**Зачем:** bulk-cleanup устаревших записей через DatabasePage. Сейчас
портал может удалить только из `local_products`; БД parsers продолжает
хранить мёртвые товары.

**Безопасность:** опционально — авторизация через ENV-токен
`PARSERS_ADMIN_TOKEN` в заголовке.

---

## 6. `GET /search/debug` — SSE c step-events и сырыми HTTP-логами

**Что:** альтернативный эндпоинт поиска со streaming, который выдаёт
не только финальный JSON, но и пошаговый прогресс + сырые HTTP-вызовы
парсеров.

**SSE-события (предложение):**
```
store-start    {slug, name}
step           {slug, stage: "search-start" | "search-results" | "enrich-start" | "enrich-progress" | "enrich-done", count?, idx?, total?}
http-request   {slug, method, url, headers, body_preview?}
http-response  {slug, status, elapsed_ms, size_bytes, headers, body_preview}
captcha-detected {slug, url, hint}
store-done     {slug, count, elapsed_ms, error?}
results        {products, source, errors, total_ms}
```

**Реализация:** `parsers/parsers/debug_hooks.py` (новый модуль) с
функцией `inject_hooks(parser, queue)`, которая патчит
`parser._client_kwargs["event_hooks"]` для httpx — request/response хуки
кладут tuples в `asyncio.Queue`. Плюс ручные `step`-эмиты вокруг
`search()` и `_enrich()`.

**Зачем:** фаза «Глубокий debug HTTP-уровня» (отложена). Без этого
портал видит только финальный JSON и не может ответить на вопрос
«почему GaGa парсер вернул пустой результат, что было в HTTP».

**Совместимость:** новый эндпоинт, не трогает `/search`.

---

## 7. Retry с экспоненциальным бэкоффом

**Что:** новый модуль `parsers/parsers/retry.py`:

```python
async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[Exception], ...] = (httpx.HTTPError, httpx.TimeoutException),
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """Backoff: base * 2^attempt с jitter (0.5..1.5×). max_delay — потолок."""
```

Применить в `_enrich` каждого парсера (HobbyGames, Лавка, GaGa, CrowdGames)
и опционально в стадии поиска. `parser_log` расширить колонкой
`retry_count INTEGER DEFAULT 0`, писать туда суммарное количество ретраев
за вызов.

**Зачем:** production-надёжность. Сейчас единичный сетевой сбой при
обогащении ломает результат для одного товара (ловится `except
Exception → return {}`), но при массовом сбое (Wi-Fi, прокси) парсер
теряет 100% данных.

---

## 8. Rate-limiting per host

**Что:** `parsers/parsers/rate_limit.py`:

```python
class HostRateLimiter:
    def __init__(self, config: dict[str, dict]) -> None:
        # {"hobbygames.ru": {"rps": 5, "burst": 10}, ...}
    async def acquire(self, host: str) -> None: ...   # ждёт токен
```

Инжектится через httpx `event_hooks["request"]`: в хуке `await
limiter.acquire(host)`. Дефолтный конфиг — 3 rps, burst 5; переопределение
через ENV `RATE_LIMITS_JSON='{"hobbygames.ru": {"rps": 1}}'`.

**Зачем:** при `force_refresh=true` параллельное обогащение через
`asyncio.gather` создаёт burst 10+ одновременных запросов к одному
магазину. Это видимый паттерн для anti-bot систем.

---

## 9. Прокси-ротация

**Что:** `parsers/parsers/proxy_pool.py`:

- Читает `PROXY_LIST` из ENV (`socks5://...,http://user:pass@...`);
- round-robin или least-fail-rate;
- при ответе ≥ 5xx или connection error помечает прокси как degraded
  на N минут (`PROXY_DEGRADE_MINUTES=5` по умолчанию);
- инжектится в `parser._client_kwargs["proxy"]` per-request (нужно
  пересоздавать `httpx.AsyncClient` или использовать кастомный
  `AsyncBaseTransport`).

**Зачем:** при IP-блокировке без ротации парсер ложится надолго.

---

## 10. Captcha detector

**Что:** в `parsers/parsers/debug_hooks.py` (см. п. 6) добавить
эвристику в response-хук:

```python
CAPTCHA_PATTERNS = [
    re.compile(r"<title>\s*Just a moment", re.I),
    re.compile(r"cloudflare-challenge", re.I),
    re.compile(r"recaptcha", re.I),
    re.compile(r"<title>Attention Required!", re.I),
]
```

При срабатывании:
- эмитит SSE-событие `captcha-detected`;
- помечает результат парсера `errors[slug] = "captcha:cloudflare"`;
- агрегатно — отдельный счётчик `captcha_blocks_24h` в `parser_log`
  (через `error_msg LIKE 'captcha:%'`).

**Зачем:** сейчас при CAPTCHA парсер падает с `HTTPError 403/503` или
просто пустым HTML — пользователь видит «нет результатов» и ищет ошибку
в коде, хотя проблема инфраструктурная.

---

## Приоритизация (предложение)

| # | Приоритет | Зависит от                    | Эффект на portal       |
|---|-----------|-------------------------------|------------------------|
| 1 | high      | —                             | Упрощает diff в фазе 4 |
| 2 | medium    | —                             | Упрощает фазу 3        |
| 3 | medium    | (1)                           | Упрощает фазу 3        |
| 4 | medium    | —                             | Богатый журнал         |
| 5 | low       | (2)                           | Bulk-cleanup           |
| 6 | high      | (7) опц.                      | Фаза «глубокий debug»  |
| 7 | medium    | —                             | Production-надёжность  |
| 8 | medium    | —                             | Production-надёжность  |
| 9 | low       | (7)                           | Production-надёжность  |
| 10| medium    | (6)                           | Объясняет «нулевые» результаты |

---

## Контракт совместимости

Все новые эндпоинты — добавление, без изменения существующих
`/search`, `/stores`, `/history/{id}`. Существующие схемы
расширяются опциональными полями (`external_id`, `retry_count`,
`captcha_blocks_24h`), что не ломает старых клиентов.
