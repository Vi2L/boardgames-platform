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

**Все сервисы локально запускаются в Docker-контейнерах** через единый
`docker compose` — это канонический способ работы с репо. Host-uvicorn
оставлен только для точечной отладки одного сервиса (см. ниже).

```bash
# Один раз
cp .env.example .env
uv sync --all-packages --group dev     # один общий .venv в корне со всеми members
                                        # (нужен для тестов, миграций и host-debug)

# Запуск всего стека
docker compose --profile full up -d    # postgres + catalog + parsers + web-test
docker compose ps                       # все 4 healthy
docker compose --profile full down      # стоп (volumes сохраняются)

# Тесты — запускаются per-service (см. CLAUDE.md о pytest)
cd services/catalog && uv run pytest -v   # один сервис
bin/test-all.sh                            # все сервисы (отдельные процессы)
```

### Локальная отладка одного сервиса (host-uvicorn)

Когда нужен hot-reload или отладчик в IDE — поднимаем postgres в Docker,
а конкретный сервис запускаем uvicorn'ом с хоста. Остальные сервисы
обычно тоже остаются в Docker (либо тушим только тот, что отлаживаем).

```bash
docker compose --profile minimal up -d                                    # только postgres
docker stop bg-<service>                                                  # тушим тот, что заменяем
uv run --package boardgames-catalog uvicorn catalog.api:app --reload --port 8002
uv run --package parsers uvicorn parsers.api:app --reload --port 8001
uv run --package web-test uvicorn app.main:app --reload --port 8000
```

## Наполнение catalog данными (seed)

После первого запуска `catalog` БД пустая (только применённые миграции).
Загрузить ~162K игр из BGG-выгрузки + русские локализации из Wikidata:

```bash
# 1) Скачать BGG ranks CSV (~10 МБ) с https://boardgamegeek.com/data_dumps/bg_ranks
#    (требует BGG-аккаунт; обновляется ежемесячно)

# 2) Загрузить ~162K игр в `games` + `game_bgg` (~50 секунд):
uv run --package boardgames-catalog python -m catalog.scripts.import_bgg_ranks ~/Downloads/boardgames_ranks.csv

# 3) Обогатить топ-1000 русскими названиями + descriptions из Wikidata (~10 минут):
uv run --package boardgames-catalog python -m catalog.scripts.import_wikidata --only-rank-le 1000

# Полный прогон по всем ~30K ranked игр займёт ~8 часов (rate-limit Wikidata 1 req/sec):
# nohup uv run --package boardgames-catalog python -m catalog.scripts.import_wikidata > wikidata.log 2>&1 &
```

Оба скрипта **идемпотентные** (`ON CONFLICT (bgg_id) DO UPDATE`) — повторный
запуск только обновит существующие записи. Их также можно запускать
изнутри docker-контейнера через `docker compose exec catalog python -m ...`
(после `docker cp <csv> bg-catalog:/tmp/`).

Подробности — в [`services/catalog/CLAUDE.md`](services/catalog/CLAUDE.md), секция «Обогащение catalog'а».

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
