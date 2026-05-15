# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Проект

Сервис сравнения цен на настольные игры в российских интернет-магазинах.
Предназначен для мобильного приложения (React Native). Python ≥ 3.12, полностью async.

User-facing документация — в `README.md`. Этот файл — для разработчика/Claude.

## Команды

```bash
# Установка (один раз, из корня монорепо)
uv sync --all-packages --group dev

# Запуск API (http://127.0.0.1:8001) — из корня монорепо
uv run --package parsers uvicorn parsers.api:app --reload --port 8001

# С raw-snapshot recorder'ом (диагностика парсеров через /dashboard)
ENABLE_RAW_SNAPSHOTS=1 uv run --package parsers uvicorn parsers.api:app --reload --port 8001

# Тесты (без сети, без БД — только моки и временные SQLite). Запускать из services/parsers/
cd services/parsers && uv run pytest tests/ -v

# Один тест или один класс
cd services/parsers && uv run pytest tests/test_service.py::TestPriceService::test_cold_cache_hits_parser -v
cd services/parsers && uv run pytest tests/test_db_analytics.py -v
cd services/parsers && uv run pytest tests/test_db_explorer.py -v

# Тест поиска через API
curl "http://127.0.0.1:8001/search?q=Каркассон"
curl "http://127.0.0.1:8001/search?q=Каркассон&refresh=true"
curl "http://127.0.0.1:8001/stores"
curl "http://127.0.0.1:8001/history/1"

# Dashboard и аналитика (HTML + REST)
open http://127.0.0.1:8001/dashboard
curl "http://127.0.0.1:8001/api/stats"
curl "http://127.0.0.1:8001/api/stats/top-queries?hours=168"
curl "http://127.0.0.1:8001/api/stats/parser-breakdown"
curl "http://127.0.0.1:8001/api/db/meta"
curl "http://127.0.0.1:8001/api/db/products?store=lavkaigr&q=Каркассон&limit=5"

# Live Test — запустить парсеры мимо кеша, без записи в БД
curl "http://127.0.0.1:8001/api/debug/parse?q=Каркассон&stores=hobbygames,gaga&limit=3"
```

## Переменные окружения

Скопировать `.env.example` → `.env` при необходимости.

| ENV | по умолчанию | описание |
|---|---|---|
| `DB_PATH` | `data/prices.sqlite` | Путь к SQLite-файлу |
| `CACHE_TTL_HOURS` | `4` | Время жизни кеша в часах |
| `PROXY` | — | SOCKS5/HTTP-прокси для HTTP-парсеров |
| `ENABLE_RAW_SNAPSHOTS` | — | `1` → каждый HTTP-ответ парсера пишется в `parser_snapshot` (для отладки через /dashboard). По умолчанию выключено, нулевой оверхед. |
| `CATALOG_INGEST_URL` | — | URL webhook'а `boardgames-catalog`. Если задан — после успешного парсинга батча offers пушатся туда. Не задан → publisher отключён, нулевой оверхед. См. секцию «Интеграция с boardgames-catalog». |
| `CATALOG_API_KEY` | — | API-ключ для `boardgames-catalog` со scope `ingest`. Используется publisher'ом, если `boardgames-catalog` запущен с `REQUIRE_AUTH=1`. |

## Соседи (монорепо `boardgames-platform`)

`parsers` — один из 3 backend-сервисов монорепо. Полная карта стека —
в корневом [`CLAUDE.md`](../../CLAUDE.md) и [`docs/architecture.md`](../../docs/architecture.md).

| Сервис | Роль | URL в dev |
|---|---|---|
| `services/catalog` | канонический каталог + матчинг offers | `http://localhost:8002` |
| `services/web-test` | дебаг-портал, UI ручного матчинга | `http://localhost:8000` (backend) / `5173` (frontend) |

## Интеграция с boardgames-catalog

`parsers/catalog_publisher.py` — opt-in side-channel: после успешного парсинга
батча `PriceService` шлёт `POST /ingest/offers` на `CATALOG_INGEST_URL`.

- **Fire-and-forget** через `asyncio.create_task` — ошибки не влияют на ответ
  `/search` (см. `service.py` рядом с `_save_observations`).
- **No-op без env**: если `CATALOG_INGEST_URL` не задан, publisher выключен,
  нулевой оверхед.
- **Single shared client**: `CatalogPublisher` держит один `httpx.AsyncClient`
  на процесс — переиспользует TCP/TLS-соединения.
- **DLQ при сбое** (F5.1): если catalog не доступен или ответил 5xx,
  payload не теряется, а сохраняется в SQLite-таблицу `catalog_dlq`
  (publisher хранит ссылку на `_db` через `attach_db()` в lifespan).
  Поля DLQ-записи: `payload_json`, `attempt_count`, `last_error`,
  `created_at`, `last_attempt_at`. Через REST (`/api/dlq/*`) или
  web-test UI (`/dlq`) можно сделать replay одной записи или
  batch'ом — при успехе запись удаляется из DLQ.
- **Контракт webhook'а** — стабильный, **single source of truth**:
  [`services/catalog/CLAUDE.md`](../catalog/CLAUDE.md), секция
  «Контракты с соседями».
- **Нормализованные поля магазина** (миграция catalog 0006): publisher
  поднимает из `ParsedProduct.raw` в первоклассные поля payload —
  `sku`, `in_stock`, `original_price`, `is_preorder` — чтобы catalog
  писал их в индексируемые колонки `offers`, а не только в `raw_extra`.
  HobbyGames кладёт `sku`/`availability`/`original_price` в raw,
  Crowd Games — `in_stock`. Старые клиенты без этих полей продолжают
  работать (catalog умеет извлекать из `extra` как fallback).
- **При изменении формата** в `catalog_publisher.py` — синхронно править
  `services/catalog/catalog/routers/ingest.py` и общую схему в
  `services/catalog/catalog/schemas.py:IngestRequest`.

## Архитектура

```
FastAPI (api.py)
    ↓
PriceService (service.py)   ← оркестрация: TTL-кеш per-store + параллельный парсинг
    ├─ PriceDatabase (db.py)  ← aiosqlite: 3 таблицы, история цен
    └─ StoreParser (base.py)  ← абстрактный класс
           ├─ HobbyGamesParser  (stores/hobbygames.py)  — работает без ограничений
           ├─ LavkaIgrParser    (stores/lavkaigr.py)    — работает без ограничений
           ├─ GagaParser        (stores/gaga.py)        — cp1251, работает без ограничений
           ├─ CrowdGamesParser  (stores/crowdgames.py)  — каталог издателя, локальный поиск
           ├─ AvitoParser       (stores/avito.py)       — C2C-объявления;
           │                     L0-обход Qrator через curl-cffi + публичный
           │                     JSON /web/1/js/items (см. stores/avito_qrator.py)
           └─ WildberriesParser (stores/wildberries.py) — публичный JSON
                                 search.wb.ru/.../v5/search; pluggable backend
                                 (httpx | curl-cffi); локальный фильтр
                                 subjectId=120 = «Настольные игры»
```

**Ключевые модули:**

- `models.py` — frozen dataclasses: `StoreInfo`, `ParsedProduct` (от парсера), `ProductRecord` (из БД), `PricePoint`, `SearchResult`.
- `base.py` — `StoreParser` (ABC) + `ParserMetrics` dataclass + `SnapshotRecorder`. См. секцию «Контракт парсера».
- `db.py` — `PriceDatabase`: 7 таблиц (stores, products, price_observations, request_log, parser_log, parser_snapshot, catalog_dlq). Цены в **копейках** (int). `normalized_title` = `title.lower()` хранится отдельно — SQLite `lower()` не работает с Unicode/кириллицей. `_MIGRATIONS` — список идемпотентных `ALTER TABLE`, выполняются при `db.init()`.
- `service.py` — логика TTL per-store: читает кеш, определяет устаревшие магазины, параллельно парсит через `asyncio.gather` (per-parser таймер через `_run_one`), сохраняет наблюдения, graceful degradation. Метрики читает через `parser.last_metrics` и пишет в `parser_log`.
- Каждый парсер делает два параллельных этапа: поиск → обогащение (`_enrich`). `_enrich` запрашивает страницу каждого товара в параллели через `asyncio.gather` и возвращает `dict` для `dataclasses.replace(product, **extra)`.
- `api.py` — FastAPI: `/search`, `/history/{id}`, `/stores`, `/api/debug/parse`. **Форматы цены различаются**: `/search` отдаёт `price_rub` (рубли, float), `/history/{id}` — `price` (копейки, int), `/api/debug/parse` — оба формата для удобства отладки.
- `stats_api.py` — все аналитические endpoints под `/api/stats/*`, `/api/db/*`, `/api/debug/*` + сам `/dashboard` (HTML).
- `dashboard.html` — single-page UI на vanilla JS + Chart.js по CDN (4.4.0). Шесть табов: Обзор, Парсеры, Запросы, Ошибки, База данных, Live Test. Hash-based router (`#tab=database`), polling 30s только для активного таба.

**`SearchResult.source`:**
| значение | смысл |
|---|---|
| `"cache"` | все магазины свежие, сеть не трогали |
| `"network"` | хотя бы один магазин обновился |
| `"partial-cache"` | все упали, вернули устаревший кеш |

## Контракт парсера (важно при добавлении новых)

`StoreParser` (`parsers/base.py`) — abstract base class. Все парсеры обязаны:

1. **Унаследоваться** и задать атрибут класса `store: StoreInfo`.
2. **Вызывать `super().__init__()`** в `__init__` — это инициализирует:
   - `self.last_metrics: ParserMetrics | None = None` — читается сервисом для аналитики.
   - `self._http_counter: int = 0` — счётчик HTTP-вызовов.
   - `self._db: PriceDatabase | None` — инжектируется в `lifespan()` через `p._db = _db`.
3. **Реализовать** `async def search(self, query, limit) -> list[ParsedProduct]`.
4. В `search()` следовать «протоколу метрик»:
   ```python
   self._http_counter = 0
   self.last_metrics = None
   recorder = self._make_recorder(query)  # для ENABLE_RAW_SNAPSHOTS
   client_kwargs = {**self._client_kwargs,
                    "event_hooks": recorder.merged_hooks(
                        {"request": [self._count_request]})}
   async with httpx.AsyncClient(**client_kwargs) as client:
       t0 = time.monotonic()
       # ... search request + parse list
       search_ms = int((time.monotonic() - t0) * 1000)
       t1 = time.monotonic()
       enriched = await asyncio.gather(*[self._enrich(c, p) for p in basic],
                                        return_exceptions=True)
       enrich_ms = int((time.monotonic() - t1) * 1000)
   self.last_metrics = ParserMetrics(
       search_ms=search_ms, enrich_ms=enrich_ms,
       http_requests=self._http_counter,
       result_after_enrich=sum(1 for e in enriched if not isinstance(e, Exception)),
   )
   ```
   Если у парсера нет enrich-этапа (как у CrowdGames) — ставь `enrich_ms=None`, `result_after_enrich=len(matched)`.
5. **Регистрация:**
   - Импорт в `parsers/stores/__init__.py`.
   - Экземпляр в списке `parsers` внутри `parsers/api.py:lifespan()` — там же будет автоматически `await _db.upsert_store(p.store)` и `p._db = _db`.

**Что вы получите автоматически за выполнение протокола:**

- `parser_log.search_ms / enrich_ms / http_requests` заполняются → видно в `/dashboard` → таб «Парсеры» (stacked bar chart, latency breakdown).
- При `ENABLE_RAW_SNAPSHOTS=1` каждый HTTP-ответ записывается в `parser_snapshot` → видно на табе «Парсеры» секция «Snapshots» (модалка с raw HTML/JSON, поддержка cp1251).
- Парсер появится в `/api/db/stores-inventory`, в heatmap `/api/stats/field-coverage` и в раскладе `/api/stats/raw-keys` без дополнительной работы.
- Live Test (`GET /api/debug/parse?stores=<slug>`) сразу будет работать с новым парсером.

**Что останется руками:**
- Тесты: добавить класс в `tests/test_service.py` (см. как сделано для HobbyGames/LavkaIgr/GaGa) — фейковый HTTP через `httpx.MockTransport`.
- Документация полей: дописать строку в таблицу магазинов в `README.md` (slug, что собирается).

## Подводные камни

- **HobbyGames**: работает с любого IP. URL поиска — `/catalog/search?keyword=`, данные в JSON-LD `ItemList` (не HTML). `players`/`age_min`/`playtime` недоступны в структурированном виде.
- **CrowdGames**: издатель (не магазин). Весь каталог `/collection/igry-crowd-games` (~167 игр, 8+ страниц). Поиск локальный: обходим все страницы через `data-collection-infinity`, фильтруем по запросу в памяти. Кеш TTL спасает от повторных обходов. `players`/`age_min`/`playtime` недоступны. `enrich_ms` в метриках = None (этапа нет).
- **Avito (L0-стратегия, 2026-05-14)**: парсер работает **только через `curl-cffi`** с TLS-impersonation Chrome 124 — никакого браузера/Playwright/Camoufox. Запрос идёт прямо в публичный JSON `/web/1/js/items` (тот же, что дёргает фронт avito.ru после CSR-загрузки). Низкоуровневый клиент — `stores/avito_qrator.py:AvitoQratorClient`: держит один `AsyncSession` на процесс, авто-ротация `_avisc` (Max-Age=60s, refresh ≥50s), retry-with-fresh-session при 429/403. Cold-start ~2.0–2.5s, hot ~500–700ms. **Без хост-зависимостей** — chrome-extension перенесён в `DEPRECATED/` (удалить после 2026-05-28), `POST /api/avito/cookies` отдаёт 410 Gone. Если когда-нибудь endpoint сломается — повторить `bin/probe_avito_l0_xhr.py` для diagnostics.
- **Wildberries (2026-05-14)**: парсер через публичный JSON `search.wb.ru/exactmatch/ru/common/v5/search` — тот же, что дёргает фронт WB. Один HTTP-запрос → 100 items (без pagination). **Pluggable backend** через env `WB_BACKEND=httpx|curl-cffi` (default `curl-cffi` — Angie/WB агрессивно rate-limit'ит DC-IP, TLS-impersonation проходит чаще). Override на лету — query-параметр `?wb_backend=...` в `/api/debug/parse`. WB endpoint v8+ требует preset-routing через `catalog.wb.ru` (тот всегда 403 из Docker) — поэтому используем legacy v5 без preset-redirect. **Soft twin-search**: локальный фильтр `subjectId=120` («Настольные игры»), при недоборе до `limit` — добиваем общей выдачей. Retry-once при HTTP 429 (через 2s). Если сломается — `bin/probe_wb4.py` для диагностики. См. roadmap [PRS-5] про enrichment через `card.wb.ru/cards/v{N}/detail`.
- **cp1251 (GaGa)**: gaga.ru возвращает тело в cp1251. httpx декодирует автоматически по `Content-Type`. Поисковый запрос нужно кодировать в cp1251 перед percent-encoding: `quote(query.encode('cp1251'))`. В `parser_snapshot` body хранится как BLOB и декодируется по сохранённому `encoding` при выдаче.
- **SQLite `lower()`**: не поддерживает Unicode → используем `normalized_title` (Python `.lower()`).
- **Цены в копейках**: `ParsedProduct.price` и `ProductRecord.price` — всегда копейки. `/search` конвертирует в рубли (`price_rub`), `/history` отдаёт сырые копейки (`price`). `/api/debug/parse` возвращает оба формата (`price` + `price_rub`) — для дебага удобно видеть raw.
- **COALESCE в upsert**: поля `image_url_hd`, `description` и т.д. не перезаписываются NULL — если новый парсинг не вернул значение, старое остаётся.
- **pytest-asyncio**: требует `asyncio_mode = "strict"` в `pyproject.toml` (уже настроен).
- **`is_test` фильтр**: все аналитические запросы по `parser_log` фильтруют `WHERE is_test = 0`. Live Test (`/api/debug/parse`) пишет с `is_test=1`, чтобы UI-эксперименты не искажали production-метрики.
- **Frozen `ParsedProduct`**: метрики не пытаемся хранить внутри dataclass — они идут «отдельным каналом» через `parser.last_metrics` → `service.py` → `db.log_parser(..., search_ms=...)`.
- **`asyncio.create_task` в service.py**: логирование `request_log`/`parser_log` — fire-and-forget. В Live Test (`api.py`) используем `await` — диагностический endpoint, гарантия записи важнее, чем доли мс.

## Аналитика и dashboard (этапы 1-8 расширения)

Полный граф эндпоинтов и виджетов dashboard'а описан в плане `~/.claude/plans/composed-toasting-quilt.md`. Краткая шпаргалка:

| Endpoint | Что отдаёт |
|---|---|
| `/api/stats` | KPI: total / cache_hit_rate / avg_response_ms / errors |
| `/api/stats/stores` | Здоровье парсеров за 24ч |
| `/api/stats/errors?limit=N` | Последние N ошибок |
| `/api/stats/top-queries?hours=&limit=` | Популярные запросы с cache_hit_rate |
| `/api/stats/latency?hours=` | p50 / p95 / p99 / max / avg по `/search` |
| `/api/stats/timeline?bucket=hour\|day` | Распределение запросов по времени |
| `/api/stats/cache-timeline` | Динамика cache hit rate |
| `/api/stats/store-distribution` | Доли вызовов парсеров |
| `/api/stats/empty-responses` | Тихие сбои (success, но 0 товаров) |
| `/api/stats/latency-histogram` | 5 фиксированных бинов |
| `/api/stats/field-coverage` | % товаров с непустыми полями per-store |
| `/api/stats/raw-keys?top_n=` | Топ ключей в `raw_json` per-store |
| `/api/stats/parser-breakdown` | Search vs Enrich latency per-store |
| `/api/stats/parser-breakdown-timeline` | То же по часам |
| `/api/db/meta` | Размер БД, counts таблиц, диапазон наблюдений |
| `/api/db/stores-inventory` | Per-store: products / observations / min/avg/max price |
| `/api/db/products?store=&q=&sort=&limit=&offset=` | Пагинация по товарам |
| `/api/db/product/{id}` | Карточка + последние 50 точек цен |
| `/api/db/price-distribution?store=` | Перцентили цены |
| `/api/debug/features` | Какие диагностические фичи включены (raw_snapshots) |
| `/api/debug/snapshots` | Список raw HTTP-snapshot'ов |
| `/api/debug/snapshots/{id}` | Полный snapshot с decoded body_text |
| `/api/debug/snapshots/{id}/raw` | Сырое тело как text/plain |
| `DELETE /api/debug/snapshots/{id}` | Удалить snapshot |
| `/api/debug/parse?q=&stores=&limit=` | Live Test — парсеры мимо кеша, без записи в БД |
| `/api/debug/contract` | Schema `ParsedProduct` (required/optional поля, types, defaults) — собирается через `dataclasses.fields()` |
| `/api/debug/fetch-url?url=&encoding_hint=` | URL probe — пробный GET через парсерский UA/proxy. Возвращает status, encoding, content_type, body_text (≤200KB), final_url, redirect history |
| `DELETE /api/cache?store=&q=&confirm=` | Cache invalidation: per-store / per-q (LIKE `%q%` по `normalized_title`) или wipe-all (требует `confirm=true`). Удаляет products + price_observations |
| `DELETE /api/db/observations/{id}` | Точечная чистка кривых price-observations (например, парсер однажды распарсил цену с буквой). Hard-delete, без восстановления |
| `GET /api/dlq?limit=&offset=` | DLQ-метаданные (без payload) — для UI-таблицы |
| `POST /api/dlq/{id}/replay` | Повторить отправку payload в catalog. При успехе запись удаляется; при ошибке — `attempt_count++` и обновление `last_error` |
| `POST /api/dlq/replay-all?limit=` | Batch-replay (по `created_at` ASC, лимит 50 по умолчанию). Возвращает `{replayed, success, failed}` |
| `DELETE /api/dlq/{id}` | Удалить DLQ-запись без replay (отказ от данных) |

**Безопасность `/api/debug/*` и `/api/dlq/*`**: сейчас без auth. В проде закрыть через reverse proxy (nginx auth_basic) или флагом окружения, который снимает router включение в `parsers/api.py`.
