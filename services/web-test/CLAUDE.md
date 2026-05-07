# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Debug/testing web portal for parsers from `/Users/vitaliy/Projects/parsers`. Provides real-time HTTP inspection, parse step visualization, and database browsing.

Также — UI поверх `boardgames-catalog`: вкладка «Каталог» показывает games
и предлагает ручной матчинг unmatched-оффер'ов. См. секцию «Интеграция с
boardgames-catalog».

## Соседи (multi-repo стек)

`parsers_web_test` — один из четырёх репозиториев. Полная карта стека:
[`~/Projects/boardgames-infra/README.md`](../boardgames-infra/README.md).

| Сервис | Роль | URL в dev | ENV для подключения |
|---|---|---|---|
| `~/Projects/parsers` | парсинг цен | `http://localhost:8001` | `PARSERS_API_URL` |
| `~/Projects/boardgames-catalog` | каталог + матчинг | `http://localhost:8002` | `CATALOG_API_URL`, `CATALOG_API_KEY` |
| `~/Projects/boardgames-infra` | docker-compose, Postgres | — | — |

## Commands

### Backend

```bash
# Setup (first time)
uv venv .venv
uv pip install -e "."

# Run dev server
.venv/bin/uvicorn app.main:app --reload --port 8000

# Check syntax
python3 -c "import ast, os; [ast.parse(open(os.path.join(r,f)).read()) for r,_,fs in os.walk('app') for f in fs if f.endswith('.py')]"
```

### Frontend

```bash
cd frontend

# Setup (first time)
npm install

# Run dev server (proxies /api → localhost:8000)
npm run dev       # → http://localhost:5173

# Type check
npx tsc --noEmit

# Build for production (output → frontend/dist/, served by FastAPI)
npm run build
```

### Running both together

Terminal 1: `.venv/bin/uvicorn app.main:app --reload --port 8000`
Terminal 2: `cd frontend && npm run dev`

Open: http://localhost:5173

## Architecture

```
parsers_web_test/
├── app/
│   ├── main.py          # FastAPI app, CORS, static files mount
│   ├── deps.py          # Singletons: PriceDatabase, parser configs, in-memory stats
│   ├── schemas.py       # Pydantic response models + product_record_to_out()
│   ├── debug_hooks.py   # httpx event_hooks → asyncio.Queue SSE events
│   ├── db_ext.py        # DebugDB: extra SQL queries (list_products, stats, clear cache)
│   └── api/
│       ├── search.py    # GET /api/search → SSE stream (sequential parser execution)
│       ├── parsers.py   # GET /api/parsers, POST /api/parsers/{slug}/run
│       ├── products.py  # GET /api/products, GET /api/products/{id}, DELETE /api/cache
│       ├── history.py   # GET /api/products/{id}/history
│       └── stores.py    # GET /api/stores
└── frontend/src/
    ├── App.tsx          # Layout: sidebar + routes
    ├── store/search.ts  # Zustand: search state + SSE event handler
    ├── lib/sse.ts       # useSSE hook (EventSource wrapper)
    ├── lib/api.ts       # fetch helpers
    ├── pages/           # SearchPage, ParsersPage, DatabasePage, ProductPage
    └── components/      # search/, parsers/, database/, shared/
```

## Key Patterns

### Adding a new parser
1. Add to `_parser_configs` in `app/deps.py`:
   ```python
   {"cls": NewParser, "kwargs": lambda: {"proxy": os.getenv("PROXY") or None}},
   ```
2. Parser must have `self._client_kwargs: dict` for HTTP hook injection to work.

### SSE flow
1. `GET /api/search` creates `asyncio.Queue` and spawns `_run_parsers()` as background task
2. `_run_parsers()` creates fresh parser instances, injects debug hooks via `inject_hooks()`
3. Hooks put `("http-request", {...})` and `("http-response", {...})` tuples into queue
4. `_stream()` reads queue and yields SSE events
5. Frontend `useSSE` hook receives events → `handleSSEEvent()` in Zustand store

### Database
- Uses `parsers.db.PriceDatabase` (from parsers package) for read/write
- `app/db_ext.py:DebugDB` adds pagination and stats queries directly via aiosqlite
- DB file: `data/debug.sqlite` (configurable via `DB_PATH` env var)
- Prices stored as integers (kopecks); `price_rub = price / 100`

## Dependencies

- Parsers package: workspace-член (`{ workspace = true }` в корневом pyproject.toml монорепо), editable
- Backend: FastAPI, uvicorn, pydantic v2, aiosqlite, python-dotenv, httpx
- Frontend: React 18, Vite 5, Tailwind CSS v3, TanStack Query v5, Zustand v4, Recharts v2

## Интеграция с boardgames-catalog

Подключение через `app/catalog_client.py` (по образу `app/parsers_client.py`)
и проксирующий роутер `app/api/catalog.py` под префиксом `/api/catalog/*`.

Файлы:
- `app/catalog_client.py` — `CatalogClient`: тонкая обёртка над httpx, методы
  `list_games`, `get_game`, `matching_queue`, `link_offer`, `reject_offer`.
  Поддержка `X-API-Key`.
- `app/api/catalog.py` — proxy-роутер: фронт ходит на свой backend, не
  cross-origin. Маршруты: `/api/catalog/health`, `/games`, `/games/{id}`,
  `/matching/queue`, `/matching/{id}/link`, `/matching/{id}/reject`.
- `app/deps.py` — singleton `CatalogClient`, env: `CATALOG_API_URL` (default
  `http://localhost:8002`), `CATALOG_API_KEY` (для prod auth).
- `frontend/src/lib/catalog.ts` — TS-клиент к `/api/catalog/*`.
- `frontend/src/pages/CatalogPage.tsx` — две вкладки:
  - **Каталог**: поиск с pg_trgm fuzzy, таблица games с source-бейджами
    (manual/bgg/tesera).
  - **Очередь матчинга**: unmatched-оффер'ы с inline-picker'ом для ручной
    связки с Game.

Контракт API каталога — **single source of truth**:
[`~/Projects/boardgames-catalog/CLAUDE.md`](../boardgames-catalog/CLAUDE.md)
секция «Контракты с соседями». При изменениях upstream'а синхронно
поправить `app/catalog_client.py` и `frontend/src/lib/catalog.ts`.
