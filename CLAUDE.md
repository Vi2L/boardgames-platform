# CLAUDE.md — boardgames-platform monorepo

Этот файл подгружается Claude Code как корневой контекст при запуске
из любой подпапки репо. Локальные `services/*/CLAUDE.md` дополняют его —
в них живут детали конкретного сервиса.

## О репозитории

Монорепо платформы для настольных игр. Содержит **3 backend-сервиса** и
заготовки под `apps/` (пользовательские приложения) и `packages/` (общие
библиотеки). Собран через `git subtree` из четырёх предыдущих репозиториев
с сохранением полной истории — `git blame` работает корректно.

## Карта сервисов

| Папка | Что | Порт | Локальный CLAUDE.md |
|---|---|---|---|
| [services/catalog](services/catalog/) | Каталог + матчинг (FastAPI · Postgres · SQLAlchemy async) | 8002 | [services/catalog/CLAUDE.md](services/catalog/CLAUDE.md) |
| [services/parsers](services/parsers/) | Парсинг 4 магазинов (FastAPI · SQLite · async) | 8001 | [services/parsers/CLAUDE.md](services/parsers/CLAUDE.md) |
| [services/web-test](services/web-test/) | Внутренний debug-портал (FastAPI · React) | 8000 | [services/web-test/CLAUDE.md](services/web-test/CLAUDE.md) |

## Менеджер пакетов

**uv workspace** — один корневой `pyproject.toml`, каждый сервис как member
со своим `pyproject.toml`. После `uv sync` появляется единый `.venv/` в
корне с editable-установкой всех members.

```bash
# Установка зависимостей всего workspace (один .venv в корне)
uv sync --all-packages --group dev                 # все members + dev-tools
uv sync --all-packages --all-extras                # + extras типа playwright

# Запуск конкретного сервиса
uv run --package boardgames-catalog uvicorn catalog.api:app --reload --port 8002
uv run --package parsers uvicorn parsers.api:app --reload --port 8001
uv run --package web-test uvicorn app.main:app --reload --port 8000

# Тесты — запускаются ПЕР-СЕРВИС (см. секцию «Подводные камни» ниже о pytest)
cd services/catalog && uv run pytest -v             # тесты одного сервиса
bin/test-all.sh                                     # все сервисы скопом
```

**Важное правило:** в монорепо **только один `.venv` — в корне**. Если
после `uv sync` остались `services/*/.venv` от прежних установок —
удалить (`rm -rf services/*/.venv`).

## Frontend

В `services/web-test/frontend/` живёт React 18 + Vite + TypeScript. Это
отдельный мир Node.js, `uv sync` его не трогает:

```bash
cd services/web-test/frontend
npm install
npm run dev    # http://localhost:5173, прокси /api → :8000
npm run build  # производит dist/, FastAPI отдаёт его как статику
```

В Docker frontend собирается через multi-stage Dockerfile
(`services/web-test/Dockerfile`).

## Запуск через docker compose

```bash
cp .env.example .env                            # один раз
docker compose --profile full up -d             # все 4 сервиса
docker compose --profile full down              # стоп (без потери данных)
docker compose --profile full down -v           # ⚠ ОПАСНО — удаляет volumes
```

Профили: `minimal` (postgres), `catalog` (postgres+catalog), `full` (всё).

## Контракты между сервисами

Источник правды по контрактам:

- **`POST /ingest/offers` (parsers → catalog)** — формат описан в
  [services/catalog/CLAUDE.md](services/catalog/CLAUDE.md), секция
  «Контракты с соседями». Producer: `services/parsers/parsers/catalog_publisher.py`.
  **Менять формат — только синхронно с обоими местами.**
- **catalog read API (web-test → catalog)** — endpoints описаны там же.
- **parsers debug API (web-test → parsers)** — описаны в
  [services/parsers/CLAUDE.md](services/parsers/CLAUDE.md).

## Где что искать

- Корневой `pyproject.toml` — workspace, общие dev-зависимости, ruff/pytest конфиг.
- `docker-compose.yml` — единая оркестрация с profiles (minimal/catalog/full).
- `.env.example` — все переменные окружения, сгруппированные по сервису.
- `infra/postgres/init.sql` — расширения PG (pg_trgm, unaccent), запускается раз.
- `services/<name>/CLAUDE.md` — детали конкретного сервиса (читать перед изменениями).
- `services/catalog/alembic/` — миграции БД. Запускать `alembic` из
  `services/catalog/` (`cd services/catalog && uv run --package boardgames-catalog alembic upgrade head`).
- `services/catalog/catalog/scripts/` — CLI-скрипты:
  - `import_bgg_ranks.py` — массовый seed catalog из CSV (~162K игр за 50 сек)
  - `import_wikidata.py` — обогащение русскими названиями + descriptions (топ-1000 за ~10 мин)
  - `migrate_meta_to_satellites.py` — миграция данных из старой `games.meta` в satellite-таблицы.
  - Инструкция запуска — в `README.md` секция «Наполнение catalog данными».
- `bin/test-all.sh` — прогон тестов всех сервисов отдельными процессами pytest.
- `bin/backup-catalog.sh` — backup/restore Postgres catalog'а через pg_dump/pg_restore.
  Хранит дампы в `.scratch/backups/` (gitignored), ротация — оставляет 10 свежих.
  Можно повесить на cron хоста для регулярного бэкапа.

## Запреты (для всего монорепо)

- **Не push в remote без явного разрешения пользователя.**
- **Не `docker compose down -v`** без подтверждения — теряются все данные
  в volumes (pgdata, prices-data, portal-data).
- **Не менять формат `/ingest/offers`** без синхронной правки producer'а
  (`services/parsers/parsers/catalog_publisher.py`) и consumer'а
  (`services/catalog/catalog/routers/ingest.py` + `catalog/schemas.py:IngestRequest`).
- **Не коммитить `.env`, `data/*.sqlite`, `node_modules/`, `.venv/`** —
  всё в `.gitignore`, проверять перед коммитом.
- **Не удалять файлы без явного запроса пользователя** (общее правило проекта).

## Подводные камни (общие для монорепо)

- **`parsers @ file:///` в web-test заменён на workspace-source.** Старый
  путь `/Users/vitaliy/Projects/parsers` больше не используется — `parsers`
  резолвится через `[tool.uv.sources]` в корневом `pyproject.toml`.
- **pytest нельзя запускать из корня монорепо без cd в сервис.** У каждого
  сервиса свой `tests/conftest.py`, и pluggy падает с
  `ImportPathMismatchError`/`Plugin already registered`, потому что не
  может удержать два модуля с именем `tests.conftest` в одной сессии.
  Поэтому корневой `[tool.pytest.ini_options]` отсутствует. Запуск:
  `cd services/<name> && uv run pytest` (per-service) или
  `bin/test-all.sh` (последовательно отдельными процессами).
- **Alembic запускать из `services/catalog/`** — пути в `alembic.ini`
  относительные. Из корня — `alembic -c services/catalog/alembic.ini ...`.
- **Цены везде в копейках** (int). Конвертация в рубли — на стороне клиента.
- **web-test использует root-context для docker build** (`build.context: .`).
  Это позволяет в одном Dockerfile делать COPY и из `services/parsers/`, и из
  `services/web-test/`. Без `.dockerignore` Docker отправит весь репо в
  build daemon — `.dockerignore` обязателен.
- **Порты:** catalog 8002, parsers 8001, web-test 8000, postgres 5433 (хост),
  Vite dev 5173 (только при `npm run dev`).
- **`log_statement=mod` в bg-postgres**: все INSERT/UPDATE/DELETE/TRUNCATE/DDL
  попадают в `docker logs bg-postgres`. Это даёт audit-trail на случай неожиданных
  потерь данных (`docker logs bg-postgres | grep -E 'TRUNCATE|DELETE FROM'`).
  SELECT не логируется, поэтому шум умеренный. Прописано через `command:` в
  `docker-compose.yml`.

## Roadmap

- `apps/web/` — пользовательский веб-портал (Next.js / Vite + React)
- `apps/mobile/` — React Native / Expo для записи партий и коллекций
- `packages/shared-py/` — общие pydantic-схемы (вынести `IngestRequest` из
  дубликатов в parsers + catalog). Будет workspace member.
- `packages/shared-ts/` — TypeScript-клиент catalog API (генерируется из
  `/openapi.json`).
- `.github/workflows/` — CI с change detection (пересобирать только что менялось).
