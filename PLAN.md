# Plan: Подключение parsers_web_test к REST API парсеров

## Context

Проект `parsers` уже имеет готовый FastAPI-сервер (`parsers/api.py`) с тремя магазинами:
`hobbygames`, `lavkaigr`, `gaga`. Сервер запускается на `http://127.0.0.1:8001`.

**Текущая проблема:** `parsers_web_test` импортирует пакет `parsers` напрямую в Python, что создаёт жёсткую связь и не даёт возможности:
- запускать парсеры как отдельный сервис
- разделять масштабирование парсеров и UI

**Цель:** переключить `parsers_web_test` на работу через HTTP API вместо прямого импорта пакета.

---

## Ключевые отличия API от текущей реализации

| Аспект | Сейчас (прямой импорт) | После (через API) |
|--------|----------------------|-------------------|
| Магазины | hobbygames (1) | hobbygames, lavkaigr, gaga (3) |
| Поле цены (поиск) | `price` (int, копейки) | `price_rub` (float, рубли) |
| Поле цены (история) | `price` (int, копейки) | `price` (int, копейки) — без изменений |
| Доп. поля продукта | только `raw: dict` | `image_url_hd`, `description`, `players`, `age_min`, `playtime`, `rules_url`, `extra` |
| Транспорт | in-process | HTTP httpx (async) |
| Кэш | наш SQLite | управляет parsers-сервис |
| SSE | per-parser (7 событий) | один HTTP-запрос → response timing |

---

## Архитектура после изменений

```
Browser (5173 / 8000)
  ↓ /api/search (SSE)
parsers_web_test :8000  ←─── httpx (async) ───→  parsers API :8001
  (app/parsers_client.py)                         /search, /stores, /history/{id}
  ↓
SSE stream к браузеру: api-request → api-response → results
```

CORS для parsers не нужен — браузер никогда не обращается к :8001 напрямую.

---

## Что меняется (файлы)

### Новый файл: `app/parsers_client.py`
Тонкий async-клиент для parsers API:

```python
class ParsersClient:
    def __init__(self, base_url: str, timeout: float = 30.0): ...

    async def get_stores(self) -> list[StoreOut]: ...
    # GET /stores → [{slug, name, base_url}]

    async def search(
        self, q: str, stores: list[str] | None = None,
        limit: int = 10, refresh: bool = False
    ) -> ParsersSearchResponse: ...
    # GET /search?q=&stores=&limit=&refresh=
    # → {source, errors, products: [ProductOut]}

    async def get_history(self, product_id: int) -> list[PricePointOut]: ...
    # GET /history/{product_id}
    # → [{price (kopecks), fetched_at}]
```

Синглтон создаётся в `deps.py`, base_url берётся из `PARSERS_API_URL` (default: `http://localhost:8001`).

---

### Изменения `app/schemas.py`

**`ProductOut`** — расширить полями из API-документации:
```python
class ProductOut(BaseModel):
    id: int
    store_slug: str
    title: str
    price_rub: float          # уже рубли из API (не копейки!)
    url: str
    image_url: str | None
    image_url_hd: str | None  # новое
    description: str | None   # новое
    players: str | None       # новое: "2-5" или null
    age_min: int | None       # новое: 8 или null
    playtime: str | None      # новое: "30-45 мин." или null
    rules_url: str | None     # новое
    fetched_at: str
    extra: dict               # store-specific: gallery, sku, rating, tags...
```

Поле `price: int` (копейки) — убрать из ProductOut, оставить только `price_rub`.
`product_record_to_out()` — удалить (больше не нужен, API сам возвращает нужный формат).

**`PricePointOut`** — история в копейках, конвертация на уровне клиента:
```python
class PricePointOut(BaseModel):
    price: int        # копейки (из /history)
    price_rub: float  # вычисляем: price / 100
    fetched_at: str
```

---

### Изменения `app/api/search.py`

Убрать прямой запуск парсеров. SSE-поток теперь:

```
1. → api-request  { url, method, stores, limit }
2. ← (HTTP-запрос к parsers :8001/search — может занять несколько секунд)
3. → api-response { status, elapsed_ms, source, products_count, errors }
4. → store-error  { slug, error }  — для каждого магазина из response.errors
5. → results      { products, source, total_ms }
```

Одна HTTP-транзакция к parsers API, обёрнутая в asyncio.Task.

```python
async def _run_search(queue, q, stores, limit, refresh):
    client = get_parsers_client()
    t0 = time.monotonic()

    await queue.put(("api-request", {"url": f"{client.base_url}/search", "q": q, ...}))
    try:
        result = await client.search(q, stores, limit, refresh)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        await queue.put(("api-response", {
            "status": 200, "elapsed_ms": elapsed_ms,
            "source": result.source, "products_count": len(result.products),
        }))
        # Частичные ошибки магазинов (200 с errors)
        for slug, err in result.errors.items():
            await queue.put(("store-error", {"slug": slug, "error": err}))

        await queue.put(("results", {
            "products": [p.model_dump() for p in result.products],
            "source": result.source,
            "total_ms": elapsed_ms,
        }))
    except Exception as exc:
        await queue.put(("api-error", {"error": str(exc), "elapsed_ms": ...}))
    await queue.put(None)
```

---

### Изменения `app/api/stores.py`

Вместо `db.list_stores()` — вызов `client.get_stores()`.

---

### Изменения `app/api/history.py`

Вместо `db.get_history()` — вызов `client.get_history(product_id)`.
Конвертация kopecks→rubles на уровне клиента.

---

### Изменения `app/api/parsers.py`

`GET /api/parsers` — статистику парсеров parsers-сервис не предоставляет.
Два варианта:
- **Вариант A:** возвращать список из `/stores` без статистики run_history
- **Вариант B:** убрать эндпоинт `GET /api/parsers` и `POST /api/parsers/{slug}/run` — они зависели от прямого запуска

→ Выбор: **Вариант A** — показывать карточки магазинов со статусом "проверить подключение".
`POST /api/parsers/{slug}/run` переделать в: запустить поиск по одному магазину через client.search() с refresh=True.

---

### Изменения `app/deps.py`

```python
_parsers_client: ParsersClient | None = None

async def init_services():
    parsers_url = os.getenv("PARSERS_API_URL", "http://localhost:8001")
    _parsers_client = ParsersClient(base_url=parsers_url)
    # Проверить доступность API при старте (опционально)

def get_parsers_client() -> ParsersClient: ...
```

Убрать: `_parser_configs`, `_parser_stats`, `update_stats()`, инициализацию `PriceDatabase`.

---

### Что убрать

- `app/debug_hooks.py` — monkey-patching больше не нужен
- `app/db_ext.py` — локальная БД не нужна (кэш управляет parsers)
- `app/api/products.py` — эндпоинт `/api/products` (пагинация по БД) убрать

> **Исключение:** если нужен инспектор БД parsers — оставить `db_ext.py` и `products.py`,
> сделав `DB_PATH` читающим parsers-овский `data/prices.sqlite`.

---

### Изменения фронтенда

**`src/types/api.ts`** — обновить `ProductOut`:
```ts
export interface ProductOut {
  id: number
  store_slug: string
  title: string
  price_rub: number        // уже рубли
  url: string
  image_url: string | null
  image_url_hd: string | null   // новое
  description: string | null    // новое
  players: string | null        // новое
  age_min: number | null        // новое
  playtime: string | null       // новое
  rules_url: string | null      // новое
  fetched_at: string
  extra: Record<string, unknown>
}
```

SSE store в `src/store/search.ts` — добавить обработку новых событий `api-request`, `api-response`, `api-error`, `store-error`.

**`ResultsTable`** — добавить колонки: описание (truncated), игроки, возраст, время.

**`ProductPage`** — использовать новые поля:
- галерея (`extra.gallery`) — горизонтальный скролл
- `description` — полный текст
- `players` / `age_min` / `playtime` — бейджи
- `extra.rules` — список PDF-ссылок
- store-specific: `extra.rating`, `extra.sku`, `extra.availability`

**`SearchPage`** — убрать вкладку "HTTP Log" (больше нет per-parser hooks) → заменить на **"API Log"** (показывает один запрос к parsers с timing, source, ошибками магазинов).

---

### Docker

Добавить второй сервис в `docker-compose.yml`:

```yaml
services:
  parsers-api:
    build:
      context: ..
      dockerfile: parsers_web_test/parsers.Dockerfile
    ports:
      - "8001:8001"
    volumes:
      - parsers-data:/app/data
    environment:
      - DB_PATH=data/prices.sqlite

  app:
    build: ...
    environment:
      - PARSERS_API_URL=http://parsers-api:8001  # внутренняя сеть docker
    depends_on:
      - parsers-api

volumes:
  parsers-data:
```

Новый `parsers.Dockerfile` (в parsers_web_test/) — образ для parsers-сервиса:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY parsers/ .
RUN pip install --no-cache-dir -e .
RUN mkdir -p data
ENV DB_PATH=data/prices.sqlite
EXPOSE 8001
CMD ["uvicorn", "parsers.api:app", "--host", "0.0.0.0", "--port", "8001"]
```

---

## .env.example после изменений

```env
# URL до parsers-сервиса
PARSERS_API_URL=http://localhost:8001

# Порт web-портала
PORT=8000
```

---

## Порядок реализации

1. `app/parsers_client.py` — новый клиент
2. `app/schemas.py` — обновить ProductOut, убрать price/kopecks
3. `app/deps.py` — переключить синглтон
4. `app/api/search.py` — новая SSE-логика через клиент
5. `app/api/stores.py` + `history.py` — проксировать через клиент
6. `app/api/parsers.py` — упростить, оставить run через клиент
7. `frontend/src/types/api.ts` — новые поля ProductOut
8. `frontend/src/store/search.ts` — новые SSE-события
9. `frontend/src/components/` — обновить ResultsTable, ProductPage, SearchPage
10. `parsers.Dockerfile` + `docker-compose.yml` — два сервиса
11. Убрать: `debug_hooks.py` (или оставить для будущего), `db_ext.py`

---

## Верификация

```bash
# 1. Поднять оба сервиса
docker compose up --build -d

# 2. Проверить parsers API напрямую
curl http://localhost:8001/stores
curl "http://localhost:8001/search?q=Каркассон&limit=2"

# 3. Проверить прокси через наш бэкенд
curl http://localhost:8000/api/stores
curl "http://localhost:8000/api/search?q=Каркассон"  # → SSE stream

# 4. Фронтенд: http://localhost:8000
# - Поиск "Каркассон" → 3 магазина, badge: lavkaigr, gaga, hobbygames
# - ProductPage → галерея, описание, players/age/playtime бейджи
# - API Log tab → один HTTP-запрос к parsers с elapsed_ms и source
```
