# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Проект

Сервис сравнения цен на настольные игры в российских интернет-магазинах.
Предназначен для мобильного приложения (React Native). Python ≥ 3.9, полностью async.

User-facing документация — в `README.md` (если появится). Этот файл — для разработчика/Claude.

## Команды

```bash
# Создать venv (один раз; пакет поддерживает Python >=3.9)
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Запуск API (http://127.0.0.1:8001)
.venv/bin/uvicorn parsers.api:app --reload --port 8001

# Тесты (без сети, без БД — только моки)
.venv/bin/pytest tests/ -v

# Один тест или один класс
.venv/bin/pytest tests/test_service.py::TestPriceService::test_cold_cache_hits_parser -v
.venv/bin/pytest tests/test_service.py::TestHobbyGamesParser -v

# Тест поиска через API
curl "http://127.0.0.1:8001/search?q=Каркассон"
curl "http://127.0.0.1:8001/search?q=Каркассон&refresh=true"
curl "http://127.0.0.1:8001/stores"
curl "http://127.0.0.1:8001/history/1"
```

## Переменные окружения

Скопировать `.env.example` → `.env` при необходимости.

| ENV | по умолчанию | описание |
|---|---|---|
| `DB_PATH` | `data/prices.sqlite` | Путь к SQLite-файлу |
| `CACHE_TTL_HOURS` | `4` | Время жизни кеша в часах |
| `PROXY` | — | SOCKS5/HTTP-прокси для HTTP-парсеров |

## Архитектура

```
FastAPI (api.py)
    ↓
PriceService (service.py)   ← оркестрация: TTL-кеш per-store + параллельный парсинг
    ├─ PriceDatabase (db.py)  ← aiosqlite: 3 таблицы, история цен
    └─ StoreParser (base.py)  ← абстрактный класс
           ├─ HobbyGamesParser  (stores/hobbygames.py)  — работает без ограничений
           ├─ LavkaIgrParser    (stores/lavkaigr.py)    — работает без ограничений
           └─ GagaParser        (stores/gaga.py)        — cp1251, работает без ограничений
```

**Ключевые модули:**

- `models.py` — frozen dataclasses: `StoreInfo`, `ParsedProduct` (от парсера), `ProductRecord` (из БД), `PricePoint`, `SearchResult`.
- `db.py` — `PriceDatabase`: 3 таблицы (stores, products, price_observations). Цены в **копейках** (int). `normalized_title` = `title.lower()` хранится отдельно — SQLite `lower()` не работает с Unicode/кириллицей.
- `service.py` — логика TTL per-store: читает кеш, определяет устаревшие магазины, параллельно парсит через `asyncio.gather`, сохраняет наблюдения, graceful degradation.
- Каждый парсер делает два параллельных этапа: поиск → обогащение (`_enrich`). `_enrich` запрашивает страницу каждого товара в параллели через `asyncio.gather` и возвращает `dict` для `dataclasses.replace(product, **extra)`.
- `api.py` — FastAPI: `/search`, `/history/{id}`, `/stores`. **Форматы цены различаются**: `/search` отдаёт `price_rub` (рубли, float), `/history/{id}` отдаёт `price` (копейки, int) — так хранится в БД.

**`SearchResult.source`:**
| значение | смысл |
|---|---|
| `"cache"` | все магазины свежие, сеть не трогали |
| `"network"` | хотя бы один магазин обновился |
| `"partial-cache"` | все упали, вернули устаревший кеш |

## Добавление нового парсера

1. Создать `parsers/stores/<slug>.py`
2. Унаследоваться от `StoreParser`, задать `store: StoreInfo`
3. Реализовать `async def search(self, query, limit) -> list[ParsedProduct]`
4. Добавить импорт в `parsers/stores/__init__.py`
5. Добавить экземпляр в `parsers` список в `api.py` → `lifespan()`

## Подводные камни

- **HobbyGames**: работает с любого IP. URL поиска — `/catalog/search?keyword=`, данные в JSON-LD `ItemList` (не HTML). `players`/`age_min`/`playtime` недоступны в структурированном виде.
- **cp1251 (GaGa)**: gaga.ru возвращает тело в cp1251. httpx декодирует автоматически по `Content-Type`. Поисковый запрос нужно кодировать в cp1251 перед percent-encoding: `quote(query.encode('cp1251'))`.
- **SQLite `lower()`**: не поддерживает Unicode → используем `normalized_title` (Python `.lower()`).
- **Цены в копейках**: `ParsedProduct.price` и `ProductRecord.price` — всегда копейки. `/search` конвертирует в рубли (`price_rub`), `/history` отдаёт сырые копейки (`price`).
- **COALESCE в upsert**: поля `image_url_hd`, `description` и т.д. не перезаписываются NULL — если новый парсинг не вернул значение, старое остаётся.
- **pytest-asyncio**: требует `asyncio_mode = "strict"` в `pyproject.toml` (уже настроен).
