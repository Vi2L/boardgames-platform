# CLAUDE.md

Инструкции Claude Code для работы с `boardgames-catalog`.

## Проект

Сервис каталога настольных игр. Хранит **канонические Game** (метаданные из BGG/Tesera + ручной ввод) и связанные **offers** — предложения магазинов, приходящие из соседнего сервиса `~/Projects/parsers` через webhook `/ingest/offers`.

Полный план развития — в `~/.claude/plans/woolly-wobbling-simon.md`.

## Соседи

| Проект | Роль | URL в dev |
|---|---|---|
| `~/Projects/parsers` | Источник offers (парсинг цен в магазинах) | `http://localhost:8001` |
| `~/Projects/parsers_web_test` | Диагностика парсеров + UI ручного матчинга | `http://localhost:8000` |
| `~/Projects/boardgames-infra` | docker-compose, Postgres, общий `.env` | — |

## Стек

- Python ≥ 3.12 (новее, чем `parsers` — там 3.9; здесь смело берём свежий)
- FastAPI + uvicorn
- SQLAlchemy 2.0 async + asyncpg
- Alembic для миграций
- pydantic-settings для конфига
- pytest + pytest-asyncio (`asyncio_mode = "strict"`)

## Команды

```bash
# Создать venv (один раз)
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Запуск API (требует поднятый Postgres из infra)
.venv/bin/uvicorn catalog.api:app --reload --port 8002

# Тесты
.venv/bin/pytest -v

# Миграции (этап 2+)
.venv/bin/alembic revision --autogenerate -m "..."
.venv/bin/alembic upgrade head
```

## Архитектура

```
catalog/
├── api.py        # FastAPI app + /health
├── config.py     # pydantic-settings (env -> Settings)
├── db.py         # async engine, Base, get_session() FastAPI dep
├── models.py     # ORM-модели (этап 2)
├── routers/      # бизнес-эндпоинты (этап 3+)
├── matching/     # pg_trgm-матчер (этап 5)
├── importers/    # BGG / Tesera (этап 3-4)
└── auth.py       # X-API-Key middleware (этап 7)
```

## Контракты с соседями

### Webhook от `parsers` (этап 5)

```
POST /ingest/offers
X-API-Key: <ingest scope>

{
  "store_slug": "hobbygames",
  "products": [
    {
      "external_id": "1234",
      "title": "Каркассон",
      "url": "https://...",
      "price": 169500,           // копейки
      "image_url": "...",
      "extra": {...}             // raw_json из parsers
    }
  ]
}
```

### Чтение из `parsers_web_test` и других потребителей

Все GET-эндпоинты `/games`, `/games/{id}/offers`, `/games/{id}/price-history` — за `X-API-Key` со scope `read`.

## Auth (этап 7)

X-API-Key с разделением scope'ов. По умолчанию **выключена** (`REQUIRE_AUTH=False`),
чтобы не ломать dev/CI. В prod включается через `REQUIRE_AUTH=1`.

Scope'ы:
- `ingest` — только `POST /ingest/*` (для `parsers`)
- `read` — все `GET /games`, `GET /matching/queue`, `GET /import/jobs/*`
  (для `parsers_web_test` и других read-only клиентов)
- `admin` — суперскоуп: всё, что выше + `POST/PATCH /games`, `POST /matching/*/link|reject`,
  `POST /import/{bgg,tesera}` (для оператора)

`/health` и `/health/db` — **без auth** (нужно для compose-healthcheck).

Управление ключами через CLI:

```bash
.venv/bin/python -m catalog.cli create-key --owner parsers --scopes ingest
.venv/bin/python -m catalog.cli list-keys
.venv/bin/python -m catalog.cli revoke 5
```

В БД хранится только `sha256(plaintext)`. Plaintext показывается один раз при
создании — потом восстановить нельзя, нужно сгенерировать новый.

## Подводные камни

- **Цены в копейках** (как в `parsers`). Конвертация в рубли — на стороне клиента.
- **`title_norm`** — `lower(unaccent(title))`, как `normalized_title` в `parsers`. Делаем через generated column или триггер, чтобы `pg_trgm` индекс работал.
- **`expire_on_commit=False`** в session_factory — иначе после commit'а объекты «протухают» и FastAPI не сможет их сериализовать в response.
- **`pool_pre_ping=True`** — отбрасывает мёртвые соединения. Критично, если перед сервисом стоит pgbouncer или Postgres рестартует.
- **Alembic + async**: `env.py` использует `async_engine_from_config` + `run_sync` — обычный шаблон Alembic не работает с asyncpg.
- **Игнор `parsers.products` как источника правды**: оффер'ы дублируются в нашу `offers` (last_price + история в `offer_prices`). Это сделано ради независимости — `parsers` может пересоздавать SQLite, мы храним свою копию для долгосрочной аналитики.

## Запреты

- Не менять формат webhook `/ingest/offers` без синхронного обновления `~/Projects/parsers/parsers/catalog_publisher.py`.
- Не push'ить в remote без явного разрешения пользователя.
