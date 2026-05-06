# Board Game Price Parser

Сервис сравнения цен на настольные игры в российских интернет-магазинах. Парсит 3 магазина, кеширует результаты в SQLite и отдаёт REST API для мобильного приложения или веб-фронтенда.

## Магазины

| Магазин | slug | Что собирается |
|---------|------|----------------|
| [HobbyGames](https://hobbygames.ru) | `hobbygames` | цена, фото, описание, правила PDF, наличие, категория |
| [Лавка Игр](https://www.lavkaigr.ru) | `lavkaigr` | цена, фото, игроки, возраст, время, механики, галерея, правила PDF |
| [GaGa.ru](https://gaga.ru) | `gaga` | цена, фото, игроки, возраст, время, рейтинг, галерея, правила PDF, размеры |

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

## Переменные окружения

Скопировать `.env.example` → `.env`:

| ENV | По умолчанию | Описание |
|-----|:------------:|----------|
| `DB_PATH` | `data/prices.sqlite` | Путь к SQLite-файлу |
| `CACHE_TTL_HOURS` | `4` | TTL кеша в часах |
| `PROXY` | — | SOCKS5/HTTP-прокси |

## Тесты

```bash
.venv/bin/pytest tests/ -v
```

23 теста без сети: юнит-тесты HTML-парсеров на статичном HTML, тесты `_enrich` через fake HTTP-клиент, тесты `PriceService` через mock-парсер.

## Архитектура

```
FastAPI /search /history /stores
    ↓
PriceService  — TTL-кеш per-store, asyncio.gather, graceful degradation
    ├─ PriceDatabase (aiosqlite) — stores / products / price_observations
    └─ StoreParser (ABC)
           ├─ HobbyGamesParser  — JSON-LD ItemList
           ├─ LavkaIgrParser    — HTML + og:meta
           └─ GagaParser        — HTML cp1251 + card-features
```

Каждый парсер: (1) страница поиска → базовые поля, (2) страница товара → обогащение (`players`, `age_min`, `playtime`, `rules_url`, `image_url_hd`, `gallery`, …).

## Добавление нового парсера

1. Создать `parsers/stores/<slug>.py`, унаследоваться от `StoreParser`
2. Реализовать `async def search(query, limit) -> list[ParsedProduct]`
3. Добавить в `parsers/stores/__init__.py` и в `api.py` → `lifespan()`
