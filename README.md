# boardgames-catalog

Каталог настольных игр: канонические Game-сущности + связанные offers (предложения магазинов из проекта `parsers`).

Часть стека `~/Projects/boardgames-stack/` (см. `~/.claude/plans/woolly-wobbling-simon.md`).

## Этап реализации

**Этап 1 (текущий) — skeleton:** FastAPI с `/health`, async SQLAlchemy + asyncpg, Alembic настроен (миграций ещё нет), Dockerfile.

Следующие этапы — в плане в `~/.claude/plans/woolly-wobbling-simon.md`.

## Запуск

### Через docker-compose (рекомендуется)

```bash
cd ~/Projects/boardgames-infra
docker compose up catalog postgres
curl http://localhost:8002/health
curl http://localhost:8002/health/db
```

### Локально

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
# Postgres должен быть доступен по DATABASE_URL — проще всего поднять его из infra:
# docker compose -f ~/Projects/boardgames-infra/docker-compose.yml up postgres
.venv/bin/uvicorn catalog.api:app --reload --port 8002
```

### Тесты

```bash
.venv/bin/pytest -v
```

## ENV

| ENV | по умолчанию | описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://catalog:catalog@localhost:5433/catalog` | async DSN |
| `LOG_LEVEL` | `INFO` | |

## Alembic

```bash
# Создать миграцию из изменений ORM-моделей (этап 2+):
.venv/bin/alembic revision --autogenerate -m "initial schema"

# Применить:
.venv/bin/alembic upgrade head
```
