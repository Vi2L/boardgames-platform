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

- **Satellite-схема для источников**: `games` (canonical) + `game_bgg`,
  `game_wikidata` (1:1) + `game_dicefest` (N:1 через `game_id`),
  каждая с `fetched_at` для TTL.
  Reference design — `~/Projects/board_game_db`.
- **Денормализованные поля в `games`** (миграция 0006): `kind`
  (base/expansion/promo/accessory), `parent_game_id` (self-FK для допов),
  `ru_publisher` / `ru_release_year` / `is_localized_ru` / `preorder_price`
  для локализации РФ, явные external IDs `bgg_id` / `tesera_id` /
  `dicefest_id` / `nastolio_id` (partial-UNIQUE WHERE NOT NULL).
- BGG XML API + Tesera JSON импортёры (`POST /import/{bgg,tesera}`,
  идемпотентный upsert по `bgg_id`/`tesera_id`).
- **CSV-bulk-импорт** boardgames_ranks: 176K за ~50 секунд через
  `python -m catalog.scripts.import_bgg_ranks`.
- **Wikidata-обогащение**: SPARQL по BGG-ID property P2339 → labels/aliases/
  descriptions для нескольких языков. Запускается через
  `python -m catalog.scripts.import_wikidata --only-rank-le N`.
- pg_trgm fuzzy-search в `GET /games?q=` (находит «Каркассон» по «каркасон»);
  с Wikidata-aliases ru-локализации тоже попадают в матчер.
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

## Обогащение каталога

### Шаг 1 — массовый seed из BGG ranks CSV

Скачать [boardgames_ranks.csv](https://boardgamegeek.com/data_dumps/bg_ranks)
с BGG (требует лог-ин). Затем:

```bash
.venv/bin/python -m catalog.scripts.import_bgg_ranks /path/to/boardgames_ranks.csv
```

→ 176K записей в `games` + `game_bgg` за ~50 сек. Идемпотентно.

### Шаг 2 — русские локализации через Wikidata

```bash
# топ-1000 ≈ 17 минут; по умолчанию 1 req/sec
.venv/bin/python -m catalog.scripts.import_wikidata --only-rank-le 1000

# полный прогон по 30K ranked-играм (≈8 часов)
nohup .venv/bin/python -m catalog.scripts.import_wikidata --only-rank-le 30000 \
  > /tmp/wikidata.log 2>&1 &
```

Параметры:
- `--only-rank-le N` — обходить только игры с rank ≤ N (default 1000)
- `--languages ru,en` — какие локали тянуть
- `--rate-limit 1.0` — секунды между запросами (Wikidata best practice)
- `--refresh-after-days 30` — пропускать свежие записи

После прогона:

```sql
SELECT g.title, gw.labels->>'ru' AS ru_label
FROM games g JOIN game_wikidata gw ON gw.game_id = g.id
WHERE gw.found AND gw.labels ? 'ru'
ORDER BY (SELECT rank FROM game_bgg WHERE game_id = g.id) LIMIT 10;
```

ru-локализации автоматом попадают в `game_aliases` (`source='wikidata'`,
`language='ru'`), и pg_trgm-матчер начинает находить русские оффер'ы из
магазинов.

### Шаг 3 — точечное обогащение через BGG XML API

Когда нужны description/designers/mechanics для конкретной игры:

```bash
curl -X POST 'http://localhost:8002/import/bgg?wait=true' \
  -H 'content-type: application/json' -d '{"bgg_id":822}'
```

Заполнит `game_bgg.description/designers/mechanics/categories/min_players/...`,
а также статистику (`bayes_average`/`average`/`users_rated`/`average_weight`/
`num_weights`), poll'ы (`recommended_players` JSONB, `recommended_age`,
`language_dependence`) и `raw` blob (`{"parsed", "xml"}` — для re-parse без
повторного запроса). См. devlog 2026-05-12 [CAT-5/6/7].

## Alembic

```bash
# Создать миграцию из изменений ORM-моделей (этап 2+):
.venv/bin/alembic revision --autogenerate -m "initial schema"

# Применить:
.venv/bin/alembic upgrade head
```
