# Архитектура boardgames-platform

## Обзор

Платформа из трёх backend-сервисов и трёх будущих клиентов. Все backend'ы —
FastAPI на Python 3.12, async-стек.

```
┌──────────────────┐                ┌─────────────────┐
│  apps/web        │                │  apps/mobile    │
│  (будущий)       │                │  (будущий)      │
└────┬─────────────┘                └────┬────────────┘
     │ catalog API (read)                 │ catalog API (read)
     ▼                                    ▼
┌─────────────────────────────────────────────────────────┐
│                   services/catalog                      │
│   FastAPI :8002 + Postgres                              │
│   - games (canonical) + game_aliases + offers           │
│   - satellite tables: game_bgg, game_wikidata           │
│   - matching engine (pg_trgm)                           │
└────▲──────────────────────────────────────────────▲─────┘
     │ POST /ingest/offers                          │ read API
     │ (webhook от parsers)                         │ + /matching/queue
     │                                              │ (web-test)
┌────┴───────────────┐                  ┌───────────┴──────┐
│  services/parsers  │ ──── HTTP ─────► │ services/web-test│
│  FastAPI :8001     │   /search etc.   │  FastAPI :8000   │
│  - 4 магазина      │                  │  + React :5173   │
│  - SQLite (кеш)    │                  │  - debug портал  │
│  - dashboard       │                  │  - ручной матчинг│
└────────────────────┘                  └──────────────────┘
```

## Сервисы

### services/catalog (порт 8002)

Каталог настольных игр. Хранит canonical-сущности `Game` (метаданные из BGG,
Tesera, Wikidata + ручной ввод) и `Offer` (предложения магазинов, поступающие
из parsers через webhook).

**Технологический стек:**
- FastAPI + uvicorn
- PostgreSQL 16 + SQLAlchemy 2.0 async + asyncpg
- Alembic для миграций
- pg_trgm для fuzzy-матчинга unmatched-офферов
- pydantic-settings для конфигурации
- X-API-Key middleware с разделением scope'ов (ingest/read/admin)

**Ключевые endpoints:**
- `POST /ingest/offers` — webhook от parsers (single source of truth контракта)
- `GET /games`, `GET /games/{id}` — read API с pg_trgm fuzzy-search
- `GET /matching/queue` — unmatched-офферы для ручной разметки
- `POST /matching/{offer_id}/link` — ручная связка offer → game
- `POST /import/{bgg,tesera}` — асинхронные импорты из внешних источников

Подробности — в [services/catalog/CLAUDE.md](../services/catalog/CLAUDE.md).

### services/parsers (порт 8001)

Сервис парсинга цен. Опрашивает 4 интернет-магазина настольных игр
(`hobbygames`, `lavkaigr`, `gaga`, `crowdgames`), кеширует результаты в
SQLite, опционально пушит в catalog через webhook.

**Особенности:**
- Полностью async (httpx + asyncio)
- TTL-кеш per-store (по умолчанию 4 часа)
- Graceful degradation (если один парсер падает, остальные продолжают)
- Встроенный analytics dashboard на `/dashboard` (vanilla JS + Chart.js)
- Fire-and-forget publisher в catalog (не блокирует ответы `/search`)

Подробности — в [services/parsers/CLAUDE.md](../services/parsers/CLAUDE.md).

### services/web-test (порт 8000)

Внутренний debug/admin-портал. Не для конечных пользователей. Используется
разработчиком и оператором для диагностики парсеров и ручного матчинга
unmatched-офферов.

**Технологический стек:**
- Backend: FastAPI + aiosqlite (отдельная локальная БД для логов портала)
- Frontend: React 18 + Vite + TypeScript + Tailwind + TanStack Query + Zustand
- Real-time SSE-стримы для отображения работы парсеров
- Прокси-роутер `/api/catalog/*` → catalog API (никаких CORS на фронте)

В отличие от `apps/web/` (будущий пользовательский портал), web-test
оптимизирован под отладку, а не под UX. После выхода apps/web на
production web-test продолжит жить как admin-tool.

Подробности — в [services/web-test/CLAUDE.md](../services/web-test/CLAUDE.md).

## Контракт `/ingest/offers`

Источник правды — [services/catalog/CLAUDE.md](../services/catalog/CLAUDE.md),
секция «Контракты с соседями». Producer: `services/parsers/parsers/catalog_publisher.py`.
Consumer: `services/catalog/catalog/routers/ingest.py` + `catalog/schemas.py:IngestRequest`.

**Изменение формата — синхронное** во всех трёх местах. Иначе либо producer
ломается на новом consumer'е, либо наоборот.

## Базы данных

| Хранилище | Сервис | Что | Volume в compose |
|---|---|---|---|
| PostgreSQL 16 | catalog | canonical games + offers + satellite tables | `pgdata` |
| SQLite | parsers | кеш парсеров + history цен + parser_log | `prices-data` |
| SQLite | web-test | local search log + favorites + test snapshots | `portal-data` |

Цены везде в **копейках** (`int`). Конвертация в рубли — на стороне клиента.

## Stretch goals (Roadmap)

- `apps/web/` — публичный портал (поиск лучших цен, ведение коллекции,
  запись партий)
- `apps/mobile/` — мобильное приложение (React Native + Expo)
- `packages/shared-py/` — извлечь общие pydantic-схемы из дубликатов
  parsers/catalog
- `packages/shared-ts/` — генерировать TypeScript-клиент из catalog
  `/openapi.json` для apps/web и apps/mobile
- CI/CD: GitHub Actions с change detection (пересобирать только то, что
  менялось)
