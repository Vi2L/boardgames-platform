# boardgames-catalog

Каталог настольных игр: канонические **Game** (метаданные из BGG/Tesera +
ручной ввод) + связанные **offers** (предложения магазинов, приходят из
сервиса `parsers` через webhook).

Часть мультирепо-стека: см. **карту стека** в
[`~/Projects/boardgames-infra/README.md`](../boardgames-infra/README.md).

## Соседи

| Сервис | Что от нас хочет | Эндпоинт |
|---|---|---|
| [`parsers`](../parsers) | пушит batched offers | `POST /ingest/offers` (scope `ingest`) |
| [`parsers_web_test`](../parsers_web_test) | проксирует UI каталога и ручного матчинга | `GET /games`, `GET /matching/queue`, `POST /matching/*/link\|reject` |
| Будущие приложения (партии, скидки, мобайл) | читают каталог и offers по канонической Game | `GET /games`, `GET /games/{id}`, `GET /games/{id}/offers` |

Подробный контракт webhook'а — в [`CLAUDE.md`](CLAUDE.md) секция «Контракты с соседями».

## Возможности

- BGG XML API + Tesera JSON импортёры (`POST /import/{bgg,tesera}`,
  идемпотентный upsert по `bgg_id`/`tesera_id`).
- pg_trgm fuzzy-search в `GET /games?q=` (находит «Каркассон» по «каркасон»).
- Auto-matcher оффер'ов на canonical Game через триграммы; порог 0.6 →
  `match_status=auto`, ниже → `unmatched`-queue для ручного review.
- Idempotent ingest: повторный POST того же оффера не плодит дубли,
  manual/rejected-статусы не перезаписываются.
- X-API-Key auth с scope'ами `ingest`/`read`/`admin`. По умолчанию выключена
  для удобства dev/CI; в prod включить `REQUIRE_AUTH=1`.

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

## API ключи (опционально)

```bash
# Включить требование ключа
echo 'REQUIRE_AUTH=1' >> .env

# Сгенерировать ключ (показывается один раз)
.venv/bin/python -m catalog.cli create-key --owner parsers --scopes ingest

# Просмотр / отзыв
.venv/bin/python -m catalog.cli list-keys
.venv/bin/python -m catalog.cli revoke 1
```

Scope'ы: `ingest` (POST /ingest/*), `read` (GET /games, /matching/queue),
`admin` (POST/PATCH /games, /matching/{id}/link|reject, /import/{bgg,tesera}).

## Alembic

```bash
# Создать миграцию из изменений ORM-моделей (этап 2+):
.venv/bin/alembic revision --autogenerate -m "initial schema"

# Применить:
.venv/bin/alembic upgrade head
```
