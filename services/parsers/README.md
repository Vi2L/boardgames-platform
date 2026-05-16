# Board Game Price Parser

Сервис сравнения цен на настольные игры в российских интернет-магазинах. Парсит 6 источников, кеширует результаты в SQLite и отдаёт REST API для мобильного приложения или веб-фронтенда.

В составе — встроенный dashboard на `/dashboard`: аналитика, мониторинг парсеров, обозреватель БД и Live Test для отладки.

## Магазины

| Магазин | slug | Что собирается |
|---------|------|----------------|
| [HobbyGames](https://hobbygames.ru) | `hobbygames` | цена, фото, описание, правила PDF, наличие, категория |
| [Лавка Игр](https://www.lavkaigr.ru) | `lavkaigr` | цена, фото, игроки, возраст, время, механики, галерея, правила PDF |
| [GaGa.ru](https://gaga.ru) | `gaga` | цена, фото, игроки, возраст, время, рейтинг, галерея, правила PDF, размеры |
| [Crowd Games](https://www.crowdgames.ru) | `crowdgames` | цена, фото, наличие; весь каталог издателя (~167 игр) |
| [Авито](https://www.avito.ru) | `avito` | цена, фото, описание, локация, категория (C2C-объявления) |
| [Wildberries](https://www.wildberries.ru) | `wildberries` | цена, бренд, рейтинг, отзывы (search-only, без обогащения со страницы товара) |
| [Ozon](https://www.ozon.ru) | `ozon` | цена с Ozon-картой, цена без скидки, бренд, фото (через browser-service: Antibot Challenge Page требует JS) |

## Быстрый старт

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn parsers.api:app --reload --port 8001
```

```bash
curl "http://127.0.0.1:8001/search?q=Каркассон"
curl "http://127.0.0.1:8001/search?q=Каркассон&stores=lavkaigr,gaga&limit=5"
curl "http://127.0.0.1:8001/history/1"
curl "http://127.0.0.1:8001/stores"
```

## API

Три эндпоинта:

### `GET /search`

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|:------------:|----------|
| `q` | string | обязательный | Название игры |
| `refresh` | bool | `false` | Принудительно обновить кеш |
| `stores` | string | все | Фильтр: `lavkaigr,gaga` |
| `limit` | int (1–50) | `10` | Кол-во результатов |

Ответ содержит `source` (`"cache"` / `"network"` / `"partial-cache"`), `errors` и массив товаров.

Каждый товар:

```json
{
  "id": 1,
  "store_slug": "lavkaigr",
  "title": "Каркассон (2019)",
  "price_rub": 1990.0,
  "url": "https://www.lavkaigr.ru/shop/family/karkasson-2019/",
  "image_url": "https://...",
  "image_url_hd": "https://...",
  "description": "Вы — феодальный правитель...",
  "players": "2-5",
  "age_min": 8,
  "playtime": "30-45 мин.",
  "rules_url": "https://.../Carcassonne2019_Rules.pdf",
  "fetched_at": "2026-05-06T19:36:12+00:00",
  "extra": {
    "gallery": ["https://...", "..."],
    "tags": ["выкладывание плиток"],
    "rules": [{ "url": "...", "name": "Правила" }],
    "composition": ["72 квадрата участков земли;", "..."]
  }
}
```

### `GET /history/{product_id}`

История цен на товар. `price` — в **копейках** (делить на 100 для рублей).

```json
[
  { "price": 199000, "fetched_at": "2026-05-06T19:36:12+00:00" }
]
```

### `GET /stores`

Список подключённых магазинов.

Полная документация API: [`docs/api_reference.md`](docs/api_reference.md)

## Dashboard и аналитика

Откройте `http://127.0.0.1:8001/dashboard` в браузере. Шесть табов:

| Таб | Что внутри |
|-----|------------|
| **Обзор** | KPI (запросы / cache hit rate / avg latency / ошибки), графики timeline и cache rate, таблица здоровья парсеров |
| **Парсеры** | Search vs Enrich latency breakdown (stacked bar), HTTP-counter, heatmap покрытия полей, топ ключей в `raw_json`, последний товар каждого парсера, snapshots raw HTTP-ответов |
| **Запросы** | p50/p95/p99 latency, pie chart распределения по магазинам, гистограмма latency, сортируемая таблица топ-запросов |
| **Ошибки** | Последние 50 ошибок парсеров |
| **База данных** | Размер БД, инвентарь, обозреватель товаров с поиском/фильтрами/пагинацией, история цен в модалке |
| **Live Test** | Запустить парсеры мимо кеша, посмотреть что и в каком виде они отдают |

Все аналитические данные доступны и через REST — посмотрите endpoints ниже.

### Аналитические endpoints

- `GET /api/stats` — сводный KPI
- `GET /api/stats/top-queries?hours=&limit=` — популярные запросы
- `GET /api/stats/latency?hours=` — p50/p95/p99 latency
- `GET /api/stats/timeline?bucket=hour|day&hours=` — распределение по времени
- `GET /api/stats/store-distribution?hours=` — нагрузка по магазинам
- `GET /api/stats/parser-breakdown` — search vs enrich
- `GET /api/stats/field-coverage` — Data Quality (% непустых полей)
- `GET /api/db/meta` — размер БД, counts
- `GET /api/db/products?store=&q=&sort=&limit=&offset=` — обозреватель товаров
- `GET /api/db/product/{id}` — товар + история цен
- `GET /api/debug/parse?q=&stores=&limit=` — Live Test (без кеша, без записи в БД)
- `GET /api/debug/snapshots` — raw HTTP-ответы парсеров (требует `ENABLE_RAW_SNAPSHOTS=1`)

## Переменные окружения

Скопировать `.env.example` → `.env`:

| ENV | По умолчанию | Описание |
|-----|:------------:|----------|
| `DB_PATH` | `data/prices.sqlite` | Путь к SQLite-файлу |
| `CACHE_TTL_HOURS` | `4` | TTL кеша в часах |
| `PROXY` | — | SOCKS5/HTTP-прокси |
| `ENABLE_RAW_SNAPSHOTS` | — | `1` → каждый HTTP-ответ парсера сохраняется в `parser_snapshot` для отладки. По умолчанию выключено. |
| `CATALOG_INGEST_URL` | — | URL `POST /ingest/offers` сервиса [`boardgames-catalog`](https://github.com/Vi2L/boardgames-catalog). Если задан — после успешного парсинга offers fire-and-forget пушатся в каталог; ошибки не влияют на `/search`. |
| `CATALOG_API_KEY` | — | API-ключ со scope `ingest` (если catalog запущен с `REQUIRE_AUTH=1`). |

## Связь с другими сервисами

`parsers` — один из четырёх репозиториев в стеке настольных игр:

```
parsers (этот) ──offers──▶ boardgames-catalog ◀──read── parsers_web_test
                                  │
                                  └── будущие апп: партии, скидки, мобайл
```

Карта стека и порядок запуска: [`boardgames-infra/README.md`](https://github.com/Vi2L/boardgames-infra/blob/main/README.md).

## Тесты

```bash
.venv/bin/pytest tests/ -v
```

70 тестов без сети: юнит-тесты HTML-парсеров на статичном HTML, тесты `_enrich` через fake HTTP-клиент, тесты `PriceService` через mock-парсер, тесты аналитики БД (percentiles, timelines), database explorer, field coverage, миграции `parser_log` и snapshot recorder'а, инварианты Live Test.

## Архитектура

```
FastAPI /search /history /stores /dashboard /api/stats/* /api/db/* /api/debug/*
    ↓
PriceService  — TTL-кеш per-store, asyncio.gather, graceful degradation
    ├─ PriceDatabase (aiosqlite)
    │     ├─ stores / products / price_observations  — основные данные
    │     ├─ request_log / parser_log                 — мониторинг
    │     └─ parser_snapshot                          — raw HTTP (при ENABLE_RAW_SNAPSHOTS=1)
    └─ StoreParser (ABC) + ParserMetrics + SnapshotRecorder
           ├─ HobbyGamesParser   — JSON-LD ItemList
           ├─ LavkaIgrParser     — HTML + og:meta
           ├─ GagaParser         — HTML cp1251 + card-features
           ├─ CrowdGamesParser   — каталог издателя, локальный поиск
           ├─ AvitoParser        — JSON /web/1/js/items через AvitoQratorClient
           │                       (curl-cffi + TLS-impersonation Chrome 124,
           │                        обход Qrator без браузера)
           └─ WildberriesParser  — JSON search.wb.ru v5; pluggable backend
                                   (httpx | curl-cffi); soft twin-search
                                   по subjectId=120 («Настольные игры»)
```

Каждый парсер: (1) страница поиска → базовые поля, (2) страница товара → обогащение (`players`, `age_min`, `playtime`, `rules_url`, `image_url_hd`, `gallery`, …). Search и enrich времена логируются раздельно — видно на /dashboard в табе «Парсеры».

## Добавление нового парсера

См. полный контракт в [`CLAUDE.md`](CLAUDE.md). Краткая шпаргалка:

1. Создать `parsers/stores/<slug>.py`, унаследоваться от `StoreParser`.
2. **Вызвать `super().__init__()`** в `__init__` — это даёт `last_metrics`, `_http_counter`, `_db`.
3. Реализовать `async def search(self, query, limit) -> list[ParsedProduct]`. В реализации:
   - Сбросить `self._http_counter = 0`, `self.last_metrics = None`.
   - Передать в httpx event hooks `recorder.merged_hooks({"request": [self._count_request]})` где `recorder = self._make_recorder(query)`.
   - Замерить `time.monotonic()` вокруг search-запроса → `search_ms`, вокруг `gather(*enrich)` → `enrich_ms`.
   - Установить `self.last_metrics = ParserMetrics(...)` в конце.
4. Импортировать в `parsers/stores/__init__.py` и добавить в `parsers` список в `parsers/api.py:lifespan()` — там же магазин зарегистрируется в БД и парсеру инжектируется `_db`.

После этого парсер автоматически появится во всех аналитических виджетах dashboard'а, в Live Test и (при `ENABLE_RAW_SNAPSHOTS=1`) в snapshot-рекордере.
