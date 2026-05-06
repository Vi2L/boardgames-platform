# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Debug/testing web portal for parsers from `/Users/vitaliy/Projects/parsers`. Provides real-time HTTP inspection, parse step visualization, and database browsing.

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

- Parsers package: `file:///Users/vitaliy/Projects/parsers` (local editable)
- Backend: FastAPI, uvicorn, pydantic v2, aiosqlite, python-dotenv
- Frontend: React 18, Vite 5, Tailwind CSS v3, TanStack Query v5, Zustand v4, Recharts v2
