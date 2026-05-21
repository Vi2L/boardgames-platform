# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Внутренний debug-портал монорепо `boardgames-platform`. Изначально — UI вокруг
сервиса парсеров; со временем оброс инструментами для каталога, ручного
матчинга и cross-service диагностики. Цель — единый «cockpit» разработчика
без переключения между терминалом, /dashboard'ом парсеров и SQL-консолью.

Что доступно через UI (по доменам):

- **Поиск**: SSE через 6 источников с фильтром out-of-stock и бейджем «не
  в наличии», бейдж sale (HG `extra.on_sale`), личные программы лояльности
  (HG бонусы до 15% / Лавка % + донор VK) с пересчётом цены и сортировкой,
  колонки Min 30д / Min всё (агрегаты по `price_observations`).
  Лимит по умолчанию 100, потолок 500.
- **Парсеры**: одиночный run, Live Test мимо кеша, side-by-side compare
  cache vs live, raw HTTP-снепшоты, URL probe, contract-validator (схема
  ParsedProduct + heatmap field-coverage), cache invalidation
  per-store/query.
- **Каталог**: fuzzy-search games, drawer с полной карточкой (BGG +
  Wikidata + aliases), CRUD алиасов с verified flag, BGG/Tesera Import
  Wizard с polling, ручное создание/редактирование Game, merge двух игр.
- **Матчинг**: dashboard очереди (по магазинам, score-buckets), top-N
  кандидатов с pg_trgm score прямо в LinkPicker, кнопка reassess (single
  и batch).
- **БД** (`/database`): сводный health-блок наверху (4 кликабельные
  карточки), товары портала с открытием в `ProductDrawer` (как на /search),
  магазины с сортировкой «проблемные сначала», журнал поисков, БД parsers
  (inventory с per-column сортировкой, products browser с удалением
  observations, аналитика — latency p50/p95/p99, top queries с
  cache_hit_rate, тихие сбои). На каждой вкладке info-блок с назначением
  и tooltip-ы на фильтрах/метриках.
- **Тесты (QA)**: snapshots с parser-aware diff (категории: price/lost/
  gained/raw/field), suite-runner с baselines (фиксация expected min_count
  per query), favorites с preset (showOutOfStock + конфиг loyalty).
- **DLQ**: dead-letter queue для catalog ingest, ручной replay при
  downtime catalog'а.
- **Cross-service health**: popover в сайдбаре с метриками обоих соседей
  (размер БД parsers, total games в catalog, unmatched-counter).

## Соседи (multi-repo стек)

| Сервис | Роль | URL в dev | ENV для подключения |
|---|---|---|---|
| `services/parsers` | парсинг цен | `http://localhost:8001` | `PARSERS_API_URL` |
| `services/catalog` | каталог + матчинг | `http://localhost:8002` | `CATALOG_API_URL`, `CATALOG_API_KEY` |
| `services/web-test` (этот) | debug-портал | `http://localhost:8000` | — |

## Commands

### Backend

```bash
# Из корня монорепо
uv sync --all-packages --group dev               # один раз
uv run --package web-test uvicorn app.main:app --reload --port 8000

# Локально из services/web-test
python3 -c "import ast, os; [ast.parse(open(os.path.join(r,f)).read()) for r,_,fs in os.walk('app') for f in fs if f.endswith('.py')]"
```

### Frontend

```bash
cd frontend
npm install                                       # один раз
npm run dev                                       # → http://localhost:5173
npx tsc --noEmit                                  # type check
npm run build                                     # → dist/, отдаётся FastAPI как статика
```

### Running both

Terminal 1: `uv run --package web-test uvicorn app.main:app --reload --port 8000`
Terminal 2: `cd frontend && npm run dev`
Open: http://localhost:5173 (Vite проксирует `/api` на `:8000`).

## Architecture

```
services/web-test/
├── app/                                  # FastAPI backend
│   ├── main.py                           # роутер-include, CORS, static mount
│   ├── deps.py                           # ParsersClient, CatalogClient, PortalDB singletons
│   ├── parsers_client.py                 # тонкий httpx-клиент к parsers
│   ├── catalog_client.py                 # тонкий httpx-клиент к catalog
│   ├── db_local.py                       # PortalDB: SQLite локального портала + миграции
│   ├── diff.py                           # diff_snapshots с категориями (price/lost/gained/raw/field)
│   ├── schemas.py                        # Pydantic v2 (ProductOut, SnapshotMeta, ...)
│   ├── debug_hooks.py                    # httpx event_hooks → SSE events
│   └── api/
│       ├── search.py                     # GET /api/search (SSE)
│       ├── parsers.py                    # /parsers, /{slug}/run, DELETE /parsers/cache
│       ├── debug.py                      # /debug/{parse,compare,fetch-url,contract,
│       │                                 #   field-coverage,features,snapshots,...}
│       ├── parsers_db.py                 # /parsers-db/{meta,stores-inventory,products,
│       │                                 #   top-queries,latency,empty-responses,...}
│       ├── catalog.py                    # /catalog/{games,games/{id}/aliases,games/merge,
│       │                                 #   matching/{queue,stats,candidates,...},import/...}
│       ├── dlq.py                        # /dlq/{list,replay,replay-all,delete}
│       ├── snapshots.py                  # /snapshots, /snapshots/diff
│       ├── suites.py                     # /suites + /{id}/baselines (F4.4)
│       ├── favorites.py                  # /favorites CRUD
│       ├── stats.py                      # /stats/* — proxy parsers analytics
│       ├── db.py                         # /db/* — локальная БД портала
│       ├── stores.py                     # /stores
│       ├── history.py                    # /products/{id}/history, recent-deltas
│       └── health.py                     # /health, /health/all (cross-service)
│
└── frontend/src/                         # React 18 + Vite + TypeScript + Tailwind
    ├── App.tsx                           # layout: collapsible sidebar + 7 routes
    ├── store/
    │   ├── search.ts                     # Zustand: search-форма + SSE state, persist v2
    │   └── loyalty.ts                    # Zustand: конфиг личных скидок (HG/Лавка), persist
    ├── lib/
    │   ├── api.ts                        # все fetch-обёртки (~80 функций)
    │   ├── catalog.ts                    # catalog-специфичные типы и мутации
    │   ├── sse.ts                        # useSSE hook (EventSource)
    │   ├── stores.ts                     # STORE_LABELS / colors (single source of truth)
    │   ├── similarity.ts                 # фронтовый fuzzy match
    │   ├── offer.ts                      # isInStock / isOnSale / originalPriceRub
    │   └── loyalty.ts                    # applyLoyalty(products, cfg) → AdjustedPrice map
    ├── pages/
    │   ├── SearchPage.tsx                # SSE-поиск + фильтр out-of-stock + sale бейдж
    │   │                                 #   + персональные скидки + min-цены, watch-mode,
    │   │                                 #   snapshots, favorites preset
    │   ├── ParsersPage.tsx               # @deprecated (WT-F9) — удалена из NAV
    │   │                                 #   2026-05-18; route /parsers → Navigate /debug.
    │   │                                 #   Удалить после 2026-06-10 вместе с ParserCard.tsx.
    │   ├── DebugPage.tsx                 # 5 tabs: live / compare / url / contract / snapshots
    │   ├── DatabasePage.tsx              # 6 tabs + сводный health-блок наверху;
    │   │                                 #   товары портала открываются в ProductDrawer
    │   ├── CatalogPage.tsx               # Каталог + Очередь матчинга со stats-header
    │   ├── ProductPage.tsx               # /products/:id (deep-link, отдельная страница)
    │   ├── TestingPage.tsx               # snapshots / suites / favorites
    │   └── DlqPage.tsx                   # /dlq — DLQ для catalog ingest
    └── components/
        ├── parsers/                      # ParserCard, HttpLogEntry, LiveTestPanel,
        │                                 #   RawProductCard, CompareTab, RawHttpDrawer,
        │                                 #   SnapshotsTab, UrlPlayground, ContractPanel
        ├── catalog/                      # GameDetailDrawer, AliasList/Editor, BggCard,
        │                                 #   WikidataCard, ImportWizard, GameEditor,
        │                                 #   MergeDialog, MatchingStatsHeader
        ├── search/                       # SearchForm, ResultsTable, ProductDrawer,
        │                                 #   LoyaltyPanel, SaleBadge, LoyaltyBadge,
        │                                 #   DiscountCell, StoreProgressBadge
        ├── database/                     # PriceHistogram, parsers/{Inventory,Analytics,
        │                                 #   ProductsBrowser}Tab
        ├── testing/                      # DiffView (с категориями), SuiteRunner (с baselines)
        ├── search/                       # SearchForm, ResultsTable, ProductDrawer
        └── shared/                       # CommandPalette (Cmd+K), HealthBadge (popover),
                                          #   JsonViewer, PriceChart, ProductDetail, Skeleton
```

## Key Patterns

### Backend pattern

- **Роутер на домен** в `app/api/<domain>.py`, регистрация в `main.py`.
- **HTTP клиенты к соседям** — в `parsers_client.py` / `catalog_client.py`.
  Никогда не делать httpx-вызовы напрямую из роутеров.
- **Error mapping**: catalog возвращает `CatalogServiceError` (status_code +
  detail) → `HTTPException` в роутере; parsers — `ParsersServiceError` или
  `Exception` → 502 для health-style ручек.
- **CORS**: настроен на `localhost:5173` / `:3000` для Vite dev, в проде
  фронт отдаётся как статика и cross-origin не нужен.

### Frontend pattern

- **Страница** в `pages/`, локальные компоненты в `components/<domain>/`.
- **State**: TanStack Query 5 (server state) + Zustand 4 (UI state поиска).
- **Cache keys**: `['catalog', ...]` / `['parsers', ...]` / `['parsers-db', ...]`
  / `['debug', ...]` / `['dlq']` / `['health-all']` / `['matching', ...]`.
  Mutation-callback'и явно `invalidateQueries(...)` по нужным ключам.
- **Таблица + drawer/details** — основной UX. Inline-formы для CRUD
  (см. `AliasEditor`, `GameEditor`).
- **SSE** — для долгих операций (search, suite-run). Polling — для
  job-based (Import Wizard через `refetchInterval` с авто-стопом).
- **toast (sonner)** для успехов/ошибок мутаций. **`ConfirmPanel`** inline
  (см. `components/matching/ConfirmPanel.tsx`) для bulk-actions с filter
  summary + impact preview — заменяет `window.confirm` где нужен deliberate
  confirm. `window.confirm` только для truly destructive (delete observation,
  delete game, merge games, replay-all DLQ).

### Help-контент (WT-F13)

Контекстные подсказки оператору — через 6-уровневую палитру: `InfoTip`
(1-line plain), `Tooltip` (Radix, short JSX), `HelpBox` (popover, 2-6
предложений), `HowItWorks` (collapsible details), `MatchingHelpTab`
(full inline-doc tab), `public/help.html` (standalone справочник).

**Правило для любых изменений в web-test:** при добавлении нового
scheduler-job'а, runtime-flag, статуса, bucket'а, tier'а, breaker'а,
threshold'а, action-кнопки с неочевидным эффектом, или колонки с
жаргоном проекта (T0/T1/T2/T3, match_status, breaker, DLQ, auto_t1,
pg_trgm, bge-m3, qwen2.5) — **обязательно** добавить запись в
`frontend/src/lib/help-topics.tsx` и врезать `<HelpBox topic="..." />`
рядом с местом первой встречи концепта.

Полная палитра + чек-лист + конвенция именования topic_id — в
`frontend/CLAUDE.md` секция «Help-контент». `TopicId` — string literal
union из ключей `HELP_TOPICS`: несуществующий topic = TS-ошибка
компиляции на месте вызова (enforcement без lint-скриптов).

### Design system (`src/components/ui/*` · ветка `feat/admin-panel-redesign`)

В ветке `feat/admin-panel-redesign` создана **новая UI-система** под
полный редизайн (см. `.scratch/admin-panel-design/` handoff, devlog-запись
`WT-DESIGN-PR1`). На `main` этого ещё нет, мерж — после PR 2 Matching proof.

В этой системе:
- **Источник правды для tokens**: `src/lib/design-tokens.ts` — colors
  (zinc base + indigo-400 accent), typography (Inter / JetBrains Mono,
  узкая 10-18px шкала), density (compact 32px row default), `statusSystem`
  (12 ключей → tone → toneClasses).
- **Tailwind config** extend через `tokens.tailwind` — fontSize шкала
  переопределена на 10-18px. **Важно для разработчика**: `text-xs` = 11px
  (раньше 12px), `text-base` = 13px (раньше 16px). Все размеры узнее.
- **20 ui-примитивов** в `src/components/ui/`: Button, IconButton, Input,
  Textarea, Select (Radix), Combobox (cmdk+Popover), Badge, StatusDot,
  Tag, ProgressBar, Skeleton, KBD, EmptyState, Dialog (Radix), Drawer
  (Radix Dialog modal=false split-view), Tooltip + Provider, Tabs (Radix),
  Toolbar, DataTable (TanStack Table + virtual ≥500), JobLogPanel,
  HealthCard, CommandPalette (register-API через `useCommand`).
- **Layout**: `AppShell` оборачивает все routes (sidebar + topbar +
  TooltipProvider). `Sidebar` collapse persist в `localStorage`.
- **Гaлерея**: `/__design` доступна при `import.meta.env.DEV` —
  16 секций со всеми компонентами в variants × sizes.

**Правила работы с новым ui:**
- Использовать `<Badge status="auto" />` (не локальные color-словари —
  источник правды `src/lib/design-tokens.ts:statusSystem`).
- НЕ подключать UI-библиотеки целиком (Mantine/MUI/shadcn-целиком).
  Radix-примитивы точечно — да.
- Cache-keys TanStack Query не трогать при миграции страниц — они
  стабильные между старым и новым UI.
- Старые компоненты при миграции — пометить `@deprecated`, не удалять
  сразу. Удаление через 1-2 итерации.

### Adding a new parser

В parsers сервисе. Здесь автоматически появится в:
- `/api/parsers` (список),
- `/parsers` страница (карточка с Run и Trash),
- `/api/debug/parse?stores=<slug>` (Live Test),
- БД парсеров inventory + heatmap coverage,
- `STORE_LABELS` в `frontend/src/lib/stores.ts` (придётся добавить руками
  для красивого имени и цвета — иначе fallback на slug).

### SSE flow (поиск, suite run)

1. `GET /api/search` создаёт `asyncio.Queue`, спавнит `_run_parsers()` в
   background-task.
2. `_run_parsers()` инжектит httpx event_hooks через `inject_hooks()`.
3. Hooks кладут события в очередь: `http-request`, `http-response`,
   `store-start`, `store-done`, `api-request`, `api-response`, `results`.
4. `_stream()` читает очередь, эмитит SSE-события (`event: <name>\n`).
5. Frontend `useSSE(url, handler)` подписывается, обновляет Zustand-стор.

### Database (локальная портал-БД)

- `app/db_local.py:PortalDB` — async SQLite через aiosqlite, один shared
  connection. Миграции через `PRAGMA user_version` (список идемпотентных
  CREATE/ALTER). Таблицы: `local_products`, `local_searches`, `snapshots`,
  `test_suites`, `suite_runs`, `suite_run_items`, `favorites`,
  `suite_baselines` (F4.4).
- Файл: `data/debug.sqlite` (env `DB_PATH`).
- Цены в копейках, конвертация в рубли в `_row_to_product`.
- `favorites.preset_json` (v3) — opaque JSON со «всеми остальными»
  UI-настройками (`show_out_of_stock`, конфиг лояльности). Решение —
  один JSON-столбец вместо узкоспециализированных колонок: расширения
  не требуют новых миграций.

## API endpoints (web-test)

Backend под `/api/...`. Тонкий слой — большинство endpoints проксируют
parsers/catalog с error mapping. Свои данные живут в локальной portal-БД.

| Префикс | Что | Источник |
|---|---|---|
| `/search`, `/products/{id}/history`, `/products/recent-deltas`, `/products/price-stats?ids=` | SSE поиск, история, batch-агрегаты (Δ-цена, min-30д, min-all) | parsers |
| `/parsers`, `/parsers/{slug}/run`, `DELETE /parsers/cache` | Список парсеров, run, cache invalidation | parsers |
| `/stores` | Список магазинов | parsers |
| `/debug/parse`, `/debug/compare`, `/debug/fetch-url`, `/debug/contract`, `/debug/field-coverage`, `/debug/features`, `/debug/snapshots[/{id}[/raw]]` | Live Test, compare cache vs live, URL probe, schema, raw HTTP snapshots | parsers |
| `/parsers-db/{meta,stores-inventory,products[/{id}],top-queries,latency,empty-responses,price-distribution}`, `DELETE /parsers-db/observations/{id}` | Browser БД parsers | parsers |
| `/stats/{summary,stores,errors}` | Аналитика парсеров | parsers |
| `/dlq[/{id}[/replay]]`, `/dlq/replay-all` | Dead-letter queue | parsers |
| `/db/products`, `/db/searches`, `/db/products/{id}` | Локальная БД портала | local |
| `/snapshots`, `/snapshots/diff?a=&b=` | Сохранённые прогоны + parser-aware diff | local |
| `/suites[/{id}[/run\|runs\|baselines\|baselines/{bid}]]` | Test-сьюты + baselines | local |
| `/favorites` | Сохранённые поисковые запросы | local |
| `/catalog/health`, `/catalog/games[/{id}]`, `POST /catalog/games`, `PATCH /catalog/games/{id}` | Каталог CRUD | catalog |
| `/catalog/games/{id}/aliases[/{aid}]` (POST/PATCH/DELETE) | Алиасы CRUD | catalog |
| `/catalog/games/merge` | Merge двух игр | catalog |
| `/catalog/import/{bgg,tesera}`, `/catalog/import/jobs/{id}` | BGG/Tesera импорт + polling | catalog |
| `/catalog/matching/{queue,stats,candidates,{id}/{link,reject,reassess},reassess-all}` | Матчинг + dashboard | catalog |
| `DELETE /catalog/matching/decisions/{title_norm}`, `POST /catalog/matching/decisions/invalidate` | Инвалидация T0 cache (CAT-12) | catalog |
| `POST /catalog/matching/lookup-batch` | Batch резолв game_id для группировки SearchPage (WT-F11) | catalog |
| `/health`, `/health/all` | Health-check (deep) | оба + локально |

## Dependencies

- **Workspace member**: `parsers @ { workspace = true }` в корневом
  `pyproject.toml`. Editable, без `file:///`-путей.
- **Backend**: FastAPI, uvicorn, pydantic v2, aiosqlite, python-dotenv,
  httpx.
- **Frontend**: React 18, Vite 5, Tailwind CSS v3, TanStack Query v5,
  TanStack Table, Zustand v4, Recharts v2, sonner (toasts), lucide-react,
  clsx, cmdk.

## Контракты с соседями

### catalog API (single source of truth: `services/catalog/CLAUDE.md`)

Web-test проксирует все нужные endpoints. При изменениях upstream:
1. Обновить `app/catalog_client.py` — новые/изменённые методы.
2. Обновить `app/api/catalog.py` — proxy + error mapping.
3. Обновить `frontend/src/lib/catalog.ts` — типы и fetch-функции.
4. По желанию обновить таблицу выше.

Auth: catalog admin-mutations требуют `X-API-Key`. Web-test использует
один ключ из env `CATALOG_API_KEY` (scope `admin`). Если catalog запущен
с `REQUIRE_AUTH=0`, web-test тоже работает без ключа.

### parsers API

Контракт `/search`, `/api/debug/*`, `/api/db/*`, `/api/stats/*`, `/api/dlq/*`
описан в `services/parsers/CLAUDE.md`. Web-test проксирует через
`parsers_client.py` и роутеры в `app/api/{parsers,debug,parsers_db,dlq,stats}.py`.

## Подводные камни

- **`parsers @ workspace`**: импорты `from parsers.db import ...` работают
  из-за editable workspace install. Старый `file:///`-путь больше не нужен.
- **Frontend cache key consistency**: после mutation в одном домене часто
  нужно invalidate несколько ключей. Например, `linkOffer` инвалидирует
  `['catalog','matching-queue']` И `['catalog','matching-stats']` —
  иначе dashboard висит со старыми числами.
- **`catalog_dlq` в parsers**: web-test не пишет сам, только проксирует
  чтение и replay. DLQ-логика — на стороне `parsers/catalog_publisher.py`.
- **Suite baselines**: пока используется только `min_count` из
  `SuiteBaselineSpec`. Поля `expected_stores` и `min_field_coverage` есть
  в schema, но не сравниваются на прогоне (UI показывает их в pill, если
  заполнены). Расширение — следующая итерация.
- **Snapshot diff `extra` разбивается на `extra.<key>`** на бэкенде
  (`app/diff.py:diff_products`). Если нужно вернуться к сравнению целиком —
  убрать ветку `if field == "extra"` в diff_products.
- **Health popover** держит `position: fixed inset-0` overlay для
  закрытия по клику. Не вкладывать в overflow-hidden родителя — иначе
  popover обрезается.
- **Имена полей parsers ↔ frontend**: web-test тонко проксирует parsers,
  поэтому контракт = parsers. Источник правды — реальные ответы parsers,
  не интуиция. Конкретные поля для типов в `frontend/src/lib/api.ts` и
  `frontend/src/types/api.ts`:
  - `ParsersDbMeta`: `db_size_bytes`, `db_size_mb`, `tables.<name>`
    (counts), `oldest_observation`, `newest_observation`. Нет плоских
    `product_count` — берём из `tables.products`.
  - `ParsersStoreInventory`: `products_count`, `observations_count`,
    `min_price_rub`, `mean_price_rub`, `max_price_rub`, `oldest_obs`,
    `newest_obs`. Цены **уже в рублях**, не делить на 100.
  - `StoreHealthEntry` (`/api/stats/stores`): `store_slug`,
    `success_rate_24h` (0..100, **не fraction**), `avg_response_ms`,
    `total_calls_24h`, `success_count_24h`, `last_seen`, `last_success`,
    `last_error`.
  - `ParsersTopQuery`: `count` (не `hits`), `cache_hits`,
    `cache_hit_rate` (0..100), `errors`, `last_seen`, `avg_ms`.
  Эти расхождения когда-то ломали `/database` чёрным экраном — фронт
  обращался к несуществующим полям.
- **`extra.on_sale` / `extra.original_price`**: ставит парсер
  HobbyGames при акционной цене (`original_price` в **копейках**).
  Используется на `/search` для бейджа «sale» и для блокировки
  HG-бонусов в loyalty (бонусами оплачивается только товар без акции).
- **`isInStock(p)`** (`frontend/src/lib/offer.ts`): `extra.availability`
  для HG, `extra.in_stock` для CrowdGames; для Лавки/GaGa возвращает
  `true` (нет признака → считаем «в наличии»).
- **Loyalty стратегия HG-бонусов**: «по каждому товару отдельно» —
  для каждой строки делаем вид, что весь пул бонусов лёг именно на неё
  (`min(pool, 0.15 × price)`). Это «оптимистичная» цена, при покупке
  нескольких товаров одной корзиной суммарная скидка может быть меньше.
  В `LoyaltyPanel` есть дисклеймер.

## Запреты

- **Не push в remote** без явного разрешения пользователя.
- **Не менять формат** webhook'а `parsers → catalog` (`/ingest/offers`)
  без синхронной правки producer'а и consumer'а.
- **Не удалять** observations / DLQ-записи / aliases без подтверждения
  оператора (UI везде использует `window.confirm` для destructive ops).
