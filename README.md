# boardgames-platform

Монорепозиторий платформы для настольных игр. В одном репо живут:

| Папка | Что | Стек | Порт |
|---|---|---|---|
| [services/catalog](services/catalog/) | Каталог игр + матчинг офферов | FastAPI · Postgres · SQLAlchemy async · Alembic | 8002 |
| [services/parsers](services/parsers/) | Парсинг цен 4 магазинов | FastAPI · SQLite · aiosqlite | 8001 |
| [services/web-test](services/web-test/) | Внутренний debug-портал | FastAPI · React + Vite · SQLite | 8000 |

В будущем:
- `apps/web/` — пользовательский веб-портал
- `apps/mobile/` — мобильное приложение (React Native)
- `packages/shared-py/` — общие pydantic-схемы для контрактов
- `packages/shared-ts/` — TypeScript-клиент catalog API (генерируется из OpenAPI)

## Быстрый старт

```bash
# Один раз
cp .env.example .env
uv sync --all-packages --group dev     # один общий .venv в корне со всеми members

# Запуск через docker compose
docker compose --profile full up -d    # все сервисы + postgres
docker compose ps                       # все 4 healthy

# Запуск вручную (без docker), полезно для отладки
docker compose --profile minimal up -d                                    # только postgres
uv run --package boardgames-catalog uvicorn catalog.api:app --reload --port 8002
uv run --package parsers uvicorn parsers.api:app --reload --port 8001
uv run --package web-test uvicorn app.main:app --reload --port 8000

# Тесты — запускаются per-service (см. CLAUDE.md о pytest)
cd services/catalog && uv run pytest -v   # один сервис
bin/test-all.sh                            # все сервисы (отдельные процессы)
```

## Профили docker compose

| Profile | Что поднимается | Когда использовать |
|---|---|---|
| `minimal` | postgres | работаете над миграциями alembic |
| `catalog` | postgres + catalog | работаете только над каталогом |
| `full` | postgres + catalog + parsers + web-test | обычный режим |

## Менеджер зависимостей

Все Python-сервисы — члены **единого uv workspace**. Один `.venv` в корне, один `uv.lock`.
Подробности — в [CLAUDE.md](CLAUDE.md) и в `pyproject.toml`.

Для frontend в `services/web-test/frontend/` — отдельный мир Node.js. После `uv sync`:

```bash
cd services/web-test/frontend
npm install
npm run dev   # http://localhost:5173
```

## История

Этот репо собран из четырёх предыдущих репозиториев через `git subtree`:
- [Vi2L/boardgames-catalog](https://github.com/Vi2L/boardgames-catalog) → `services/catalog/`
- [Vi2L/parsers](https://github.com/Vi2L/parsers) → `services/parsers/`
- [Vi2L/parsers_web_test](https://github.com/Vi2L/parsers_web_test) → `services/web-test/`
- [Vi2L/boardgames-infra](https://github.com/Vi2L/boardgames-infra) → docker-compose.yml + infra/postgres/init.sql

`git blame` на любом подмонтированном файле работает корректно — история коммитов сохранена.
