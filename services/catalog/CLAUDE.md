# CLAUDE.md

Инструкции Claude Code для работы с `boardgames-catalog`.

## Проект

Сервис каталога настольных игр. Хранит **канонические Game** (метаданные из BGG/Tesera + ручной ввод) и связанные **offers** — предложения магазинов, приходящие из соседнего сервиса `services/parsers` через webhook `/ingest/offers`.

Полный план развития — в `~/.claude/plans/woolly-wobbling-simon.md`.

## Соседи (монорепо `boardgames-platform`)

| Сервис | Роль | URL в dev |
|---|---|---|
| `services/parsers` | Источник offers (парсинг цен в магазинах) | `http://localhost:8001` |
| `services/web-test` | Диагностика парсеров + UI ручного матчинга | `http://localhost:8000` |
| `infra/postgres/init.sql` | Расширения PG (pg_trgm, unaccent) — выполняется один раз при создании volume | — |

Карта стека целиком — в корневом [`CLAUDE.md`](../../CLAUDE.md) и [`docs/architecture.md`](../../docs/architecture.md).

## Стек

- Python ≥ 3.12 (тот же, что в parsers и web-test после миграции в монорепо)
- FastAPI + uvicorn
- SQLAlchemy 2.0 async + asyncpg
- Alembic для миграций
- pydantic-settings для конфига
- pytest + pytest-asyncio (`asyncio_mode = "strict"`)

## Команды

```bash
# Установка (один раз, из корня монорепо)
uv sync --all-packages --group dev

# Запуск API (требует поднятый Postgres — `docker compose --profile minimal up -d`)
# Из корня монорепо:
uv run --package boardgames-catalog uvicorn catalog.api:app --reload --port 8002

# Тесты — запускать из services/catalog/, иначе pytest сталкивается с conftest'ами других сервисов.
# Conftest защищён от запуска на prod БД: имя БД должно содержать 'test'.
# Дефолт = catalog_test (создаётся отдельно — см. ниже).
cd services/catalog && uv run pytest -v

# Создать тестовую БД и накатить миграции (один раз):
docker exec bg-postgres createdb -U catalog catalog_test
docker exec bg-postgres psql -U catalog -d catalog_test \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent;"
cd services/catalog && \
  DATABASE_URL='postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test' \
  uv run --package boardgames-catalog alembic upgrade head

# Если в .env стоит DATABASE_URL=...catalog (prod) — pytest упадёт с понятным
# сообщением. Решение: явно прокинуть TEST_DATABASE_URL:
TEST_DATABASE_URL='postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test' \
  cd services/catalog && uv run pytest

# Миграции — alembic.ini лежит в services/catalog/, запускать оттуда
cd services/catalog && uv run --package boardgames-catalog alembic revision --autogenerate -m "..."
cd services/catalog && uv run --package boardgames-catalog alembic upgrade head

# В Docker миграции применяются вручную после первого `docker compose up`:
docker compose exec catalog alembic upgrade head
```

## Архитектура

```
catalog/
├── api.py        # FastAPI app + /health
├── config.py     # pydantic-settings (env -> Settings)
├── db.py         # async engine, Base, get_session() FastAPI dep
├── models.py     # ORM-модели — canonical games + satellite tables
├── schemas.py    # Pydantic v2 (GameOut, GameDetailOut с bgg/wikidata)
├── wikidata.py   # WikidataClient + parser entity-payload
├── routers/      # бизнес-эндпоинты
├── matching/     # pg_trgm-матчер
├── importers/    # BGG XML / Tesera JSON импортёры (через POST /import)
├── scripts/      # CLI: import_bgg_ranks, import_wikidata, migrate_meta_*
└── auth.py       # X-API-Key middleware
```

## Satellite-схема (с миграции `0002_satellite_schema`)

Каждый внешний источник живёт в своей таблице с «жёсткими» полями + `raw jsonb`
+ `fetched_at`. Связь с canonical `games` через `game_id`. Reference design
адаптирован из старого проекта `board_game_db` (`GameWikidata`, `TsGame`, `DfGame` etc.).

```
games  (canonical, slim + денормализованные внешние ID и локализация РФ)
  ├── game_aliases   (cross-source aliases для матчинга, +language, +verified)
  ├── game_bgg       (1:1) — BGG: rank, scores, designers, mechanics,
  │                   stats (complexity/num_weights), polls (recommended_*),
  │                   raw {parsed, xml}
  ├── game_wikidata  (1:1) — labels/aliases/descriptions per language, entity_id
  ├── game_dicefest  (N:1) — публикатор РФ, preorder_price, external_links
  └── (FUTURE) game_tesera
```

**Денормализованные поля в `games` (миграция 0006):**
- `kind` — тип: `base | expansion | promo | accessory`. Default `'base'`.
  Для `is_expansion=true` из BGG автоматом → `'expansion'` (backfill).
- `parent_game_id` — self-FK на базу для допов/промо/аксессуаров. Заполняется
  вручную (без автоматизации).
- `bgg_id`, `tesera_id`, `dicefest_id`, `nastolio_id` — явные external IDs,
  partial-UNIQUE WHERE NOT NULL. `dicefest_id` указывает на `dicefest_raw_games.id`
  (без жёсткого FK — staging может быть очищен). `nastolio_id` — slug или URL.
- `ru_publisher`, `ru_release_year`, `is_localized_ru`, `preorder_price` —
  локализационные данные РФ. Источник истины — `game_dicefest` (или ручная
  правка); при промоушене копируем в `games`, чтобы UI не делал JOIN.
  При `revert` обнуляем только `dicefest_id` — остальное оператор правит сам.

Источники в `game_aliases.source`:
| value | language | verified | смысл |
|---|---|---|---|
| `manual` | NULL | true | оператор подтвердил вручную |
| `auto-match` | NULL | false | pg_trgm matcher (≥0.6) |
| `wikidata` | `'ru'`, `'en'`, ... | false | labels/aliases из Wikidata |
| `bgg` | `'en'` | false | alternate names из BGG XML |
| `tesera` (FUTURE) | `'ru'` | false | названия с tesera.ru |

**Зачем jsonb колонки в satellite'ах**: GIN-индексы по часто-запрашиваемым ключам
(`ix_game_wikidata_aliases_ru_gin` — для `aliases->'ru' ?` поиска). Остальное —
для аудита и реэкстракции.

## Обогащение catalog'а

### CSV BGG ranks (массовый seed)

```bash
# С хоста (через port mapping bg-postgres :5433):
uv run --package boardgames-catalog python -m catalog.scripts.import_bgg_ranks /path/to/boardgames_ranks.csv

# Внутри Docker контейнера (DATABASE_URL=postgres:5432 из ENV):
docker cp /path/to/boardgames_ranks.csv bg-catalog:/tmp/boardgames_ranks.csv
docker compose exec catalog python -m catalog.scripts.import_bgg_ranks /tmp/boardgames_ranks.csv
```

Заливает ~162K записей в `games` + `game_bgg` за ~50 секунд. Идемпотентно
(`ON CONFLICT (bgg_id) DO UPDATE`). При **INSERT** (новая игра): rank,
bayes_average, average, users_rated, is_expansion, subtype_ranks, source='csv-ranks',
raw={"csv": row}. При **UPDATE** существующей записи — обновляются только
`rank`/`is_expansion`/`subtype_ranks` (миграция 0012, CAT-5): XML — источник
истины для остальных метрик, CSV не понижает source/raw/fetched_at и не
перетирает свежие данные XML-обогащения.

Description/mechanics/designers/poll'ы и стат-поля (`average_weight`,
`num_weights`, `recommended_*`, `language_dependence`) остаются пустыми —
для них нужен XML API через `POST /import/bgg` или batch.

CSV-файл — официальная выгрузка BGG, обновляется ежемесячно. Скачивается
с https://boardgamegeek.com/data_dumps/bg_ranks (требует BGG-аккаунт).

### Wikidata (русские локализации + descriptions)

```bash
uv run --package boardgames-catalog python -m catalog.scripts.import_wikidata --only-rank-le 1000
```

Обходит топ-N игр по rank, обогащает `game_wikidata` (labels/aliases/
descriptions per language) и пишет ru-локализации в `game_aliases` со
`source='wikidata'`, `language='ru'`. 1 req/sec по best practice Wikidata,
fully recoverable retry на 429/5xx. Топ-1000 — ~10 минут (~600 секунд),
~585 found+written. Для полного прогона по ~30K ranked-играм — ~8 часов
под `nohup`.

Алгоритм: SPARQL `VALUES`-batch (50 ID на запрос) → entity-API per Q-id →
parse → upsert. Источник адаптирован из старого `board_game_db/app/wikidata.py`.

### XML API BGG (точечное полное обогащение)

```bash
curl -X POST 'http://localhost:8002/import/bgg?wait=true' \
  -H 'content-type: application/json' -d '{"bgg_id":822}'
```

Скачивает XML, заполняет `game_bgg`: каталог-поля (`description`/`designers`/
`mechanics`/`categories`/`min_players`/...), статистику (`bayes_average`/
`average`/`users_rated`/`average_weight`/`num_weights`), poll'ы
(`recommended_players` JSONB, `recommended_age`, `language_dependence`),
raw blob (`{"parsed": <BggGame>, "xml": <item>}`), `bgg_stats_updated_at`.
По одной игре за вызов (rate-limit BGG).

### XML API BGG batch — массовое обогащение топ-N (этап 2-3)

Подсистема `catalog/parsers/bgg/` с batch до 20 ID на запрос — полный seed
по ranked-играм (~30K) укладывается в ~25 минут вместо ~8 часов
(одиночный `/import/bgg` × 30K).

CLI (для админских прогонов):

```bash
# Топ-100 dry-run — проверить, что доедет до BGG и не упадёт.
uv run --package boardgames-catalog python -m catalog.scripts.enrich_bgg \
    --only-rank-le 100 --dry-run

# Реальный прогон топ-1000.
uv run --package boardgames-catalog python -m catalog.scripts.enrich_bgg \
    --only-rank-le 1000

# Полный seed по всем ranked-играм. Долго; запускать под `nohup` или в screen.
nohup uv run --package boardgames-catalog python -m catalog.scripts.enrich_bgg \
    --all-ranked > .scratch/enrich_bgg.log 2>&1 &
```

HTTP-endpoint (для UI с polling'ом прогресса):

```bash
curl -X POST http://localhost:8002/import/bgg/batch \
  -H 'content-type: application/json' \
  -d '{"rank_le": 1000}'
# → {"id": 42, "status": "pending", ...}

curl http://localhost:8002/import/jobs/42 | jq '.progress, .log_lines | last'
# progress: {"phase": "enriching", "current": 540, "total": 1000, "current_title": "..."}
```

Запись в БД:
- **games**: COALESCE-семантика — НЕ затираем ручные правки. Обогащаются только
  пустые поля (description / designers / players_min/max / age_min / playtime_*
  / cover_url). `source` из `'bgg-ranks'` поднимается до `'bgg'`.
- **game_bgg** (satellite): полная перезапись XML-полей (description, designers,
  mechanics, categories, min/max_players, image_url, ...). С миграции 0012
  (CAT-5/6/7) дополнительно перезаписываются `bayes_average`/`average`/
  `users_rated` (XML — источник истины), заполняются `average_weight`,
  `num_weights`, `recommended_players` JSONB, `recommended_age`,
  `language_dependence`, `raw = {"parsed": <BggGame>, "xml": <item XML>}`,
  `bgg_stats_updated_at=now()`. `rank`/`is_expansion`/`subtype_ranks`
  остаются CSV-territory. `source='xml-api'`, `fetched_at=now()` — это
  resume-state, повторный прогон со `skip_recent_days=30` пропустит
  недавно обогащённые.
- **game_aliases**: alternate names (преимущественно EN) с `source='bgg'`,
  `language='en'`, `verified=False`, ON CONFLICT DO NOTHING на
  `uq_alias_per_game`.

Прогресс в UI: `ImportJob.progress = {phase, current, total, current_title}`,
`log_lines` (ring-buffer 200 строк), batched UPDATE через
`catalog.importers._log_buffer.LogBuffer` каждые 100 строк / 2 сек.

Rate-limit BGG: `--rate-limit-sec 1.0` (≥1 req/sec — best practice). При
превышении — BGG может вернуть 429 или временно забанить.

### Tesera — отложено

Cloudflare блокирует tesera.ru / api.tesera.ru с большинства не-RU-IP.
Когда появится прокси — добавим `game_tesera` (схема готова в плане
`~/.claude/plans/woolly-wobbling-simon.md`) и `import_tesera_html.py`.

### Dicefest (русские локализации, издатели, даты выхода в РФ)

```bash
# Запуск через UI (Catalog → Импорт → Dicefest), либо curl:
curl -X POST http://localhost:8002/import/dicefest -H 'content-type: application/json' \
     -d '{"max_items": 10}'    # пробный прогон 10 игр
curl http://localhost:8002/import/jobs/{id}   # polling progress + log_lines
```

Парсер обходит листинги `?year=2024|2025|2026` (sitemap.xml у dicefest почти
пустой), парсит карточки `/game/{slug}/` через BeautifulSoup. Полный прогон —
~900 slug'ов × 1 req/sec ≈ 15 минут.

**Двухстадийность:** парсер пишет ТОЛЬКО в staging-таблицу
`dicefest_raw_games` (миграция 0003). Основная `games`/`game_aliases` НЕ
трогается — этим обеспечивается изоляция от инцидентов парсинга. Перенос в
canonical БД — отдельный управляемый процесс через UI с pg_trgm-матчингом и
журналом для отката (PR-2: `/promotion/dicefest/...`).

**Idempotency:** `slug` UNIQUE → ON CONFLICT DO UPDATE. При повторном запуске
парсер пропускает slug'и, скачанные за последние 7 дней (resume after crash).

**Прогресс/лог в UI:** `ImportJob.progress` (`{phase, current, total, current_title}`)
+ `log_lines` (ring-buffer 200 строк) обновляются батчами через
`catalog.importers._log_buffer.LogBuffer` (раз в ~20 строк или 2с) — на 1000
итераций это ~150 UPDATE'ов вместо 3000.

Поля в staging: `title_ru`, `title_en`, `publisher`, `release_year`,
`release_month`, `release_status` (data-status code типа `v-prodazhe` /
`buduschie-predzakazy`), `description`, `cover_url`. Сырой HTML карточки
сохранён в `raw_html` — позволяет перепарсить без повторного запроса при
изменении селекторов. Структурированный дамп всего вытащенного — в `raw` JSONB.

## Контракты с соседями

### Webhook от `parsers` — `POST /ingest/offers`

**Source of truth для контракта.** Менять формат — только синхронно с
`services/parsers/parsers/catalog_publisher.py`.

```http
POST /ingest/offers
Content-Type: application/json
X-API-Key: <ingest scope>     ← обязателен только при REQUIRE_AUTH=1
```

```json
{
  "store_slug": "hobbygames",
  "fetched_at": "2026-05-07T12:00:00+00:00",   // optional; если нет — server now()
  "products": [
    {
      "external_id": "1234",
      "title": "Каркассон",
      "url": "https://hobbygames.ru/.../",
      "price": 169500,                          // в копейках, nullable
      "image_url": "https://...",               // nullable
      // Нормализованные поля магазина (миграция 0006). Все опциональны;
      // если не указаны — catalog пытается извлечь из `extra` (HobbyGames
      // кладёт sku/availability, Crowd Games — in_stock).
      "sku": "HB0001234",                       // nullable
      "in_stock": true,                          // nullable: true | false | null (неизвестно)
      "original_price": 199000,                  // nullable, копейки до скидки
      "is_preorder": false,                      // nullable
      "extra": {                                // ParsedProduct.raw из parsers
        "gallery": ["..."],
        "tags": [...],
        "rating": 7.5
      }
    }
  ]
}
```

**Ответ:**

```json
{
  "store_slug": "hobbygames",
  "accepted": 1,
  "auto_matched": 1,
  "unmatched": 0,
  "items": [
    {
      "external_id": "1234",
      "offer_id": 42,
      "game_id": 7,                             // null если не сматчен
      "match_status": "auto",                   // auto | unmatched | manual | rejected
      "match_score": 0.72                       // null для unmatched без кандидатов
    }
  ]
}
```

**Семантика:**
- Upsert по `(store_slug, external_id)` — один offer = один ряд в `offers`.
- Если `match_status` уже `manual` или `rejected` — не пересматчиваем
  (решение оператора финально).
- При auto-match `title` сохраняется как `game_aliases.alias` с
  `source='auto-match'` — следующий ingest сматчится по точному `alias_norm`,
  не нагружая trgm-индекс.
- `offer_prices` получает точку при каждом ingest'е с `price != null`.
  PRIMARY KEY `(offer_id, fetched_at)` + ON CONFLICT DO NOTHING — один и тот
  же ингест в тот же миг не плодит дубли.

### Чтение из `parsers_web_test` и других потребителей

| Эндпоинт | Scope | Описание |
|---|---|---|
| `GET /games?q=&limit=&offset=` | `read` | листинг + pg_trgm fuzzy по q (UNION с `game_aliases`) |
| `GET /games/{id}` | `read` | `GameDetailOut`: основа + `aliases[]` + `bgg` (satellite) + `wikidata` (satellite) |
| `POST /games`, `PATCH /games/{id}` | `admin` | ручное создание/правка |
| `POST /games/merge {source_id, target_id}` | `admin` | объединить две игры: переносит offers + aliases (ON CONFLICT skip), source.status='merged', `meta.merged_into=target_id`. Возвращает `{offers_moved, aliases_moved, aliases_skipped_dup}` |
| `POST /games/{id}/aliases {alias, source?, language?, verified?}` | `admin` | добавить альтернативное название (UNIQUE по `alias_norm` per game) |
| `PATCH /games/{id}/aliases/{aid}` | `admin` | редактирование (alias / source / language / verified). Главный кейс — пометка `verified=true` после ревью |
| `DELETE /games/{id}/aliases/{aid}` | `admin` | удалить алиас |
| `GET /matching/queue?store=&limit=` | `read` | unmatched offers, NULLS LAST по match_score |
| `GET /matching/stats` | `read` | breakdown unmatched: total + by_store (count, avg_score) + by_bucket (good ≥0.6 / candidate 0.3-0.6 / cold) + thresholds |
| `GET /matching/candidates?title=&limit=` | `read` | топ-N кандидатов с pg_trgm score через тот же `find_match_candidates` (UNION title+aliases, MAX score per game). JOIN с games — без N+1 на фронте |
| `POST /matching/{offer_id}/link {game_id}` | `admin` | ручная связка + добавить title_raw как alias (`source='manual'`, ON CONFLICT skip) |
| `POST /matching/{offer_id}/reject` | `admin` | пометить как «не игра» |
| `POST /matching/{offer_id}/reassess` | `admin` | пересчитать `find_best_match` после правки алиасов / импорта BGG. 409 если offer уже `manual` или `rejected` |
| `POST /matching/reassess-all?store=&max_score=` | `admin` | batch-пересчёт unmatched. Возвращает `{scanned, promoted_to_auto, score_improved, unchanged}` |
| `POST /import/{bgg,tesera,dicefest}` | `admin` | запуск импортёра |
| `GET /import/jobs/{id}` | `read` | статус job'ы (включая `progress` и `log_lines` для long-running) |
| `GET /promotion/{provider}/queue?status=&limit=&offset=` | `read` | список raw-записей (provider=`dicefest`) |
| `GET /promotion/{provider}/{raw_id}` | `read` | одна raw-запись |
| `GET /promotion/{provider}/{raw_id}/candidates?threshold=&limit=` | `read` | кандидаты-canonical Game по pg_trgm |
| `POST /promotion/{provider}/{raw_id}/apply` | `admin` | действие промоушена: `link`/`create`/`skip`/`reject`. Возвращает `{log_id, game_id, alias_id, satellite_id}` |
| `POST /promotion/log/{log_id}/revert` | `admin` | откат: удаляет alias+satellite, возвращает raw в `new`. 409 если `games.status='merged'` |
| `GET /promotion/log?provider=&limit=&offset=` | `read` | журнал действий промоушена |
| `GET /health`, `GET /health/db` | — | без auth (нужно для compose-healthcheck) |

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
# С хоста (postgres на :5433 через port mapping):
uv run --package boardgames-catalog python -m catalog.cli create-key --owner parsers --scopes ingest
uv run --package boardgames-catalog python -m catalog.cli list-keys
uv run --package boardgames-catalog python -m catalog.cli revoke 5

# В контейнере (postgres на :5432 через docker network):
docker compose exec catalog python -m catalog.cli create-key --owner parsers --scopes ingest
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
- **Merge games не удаляет source**: после `POST /games/merge` source-игра помечается `status='merged'` и пишет `meta.merged_into=target_id`. Для трассировки auto-match'ей, которые могли сослаться на старый id. Реальные offers и aliases переезжают на target. UI (`web-test`) фильтрует merged-игры через `status` колонку.
- **`reassess` уважает `manual`/`rejected`**: операторские решения не пересчитываются — single-reassess отвечает 409, batch-reassess их игнорирует через WHERE `match_status='unmatched'`. Чтобы пересмотреть manual-связку — сначала reject/unlink вручную.
- **`find_match_candidates` группирует per-game**: одна игра может всплыть и через `title`, и через `alias` одновременно — берём `MAX(score)` и `via` от лучшего. Иначе UI показывал бы дубль одной игры со score 0.85 и 0.72.
- **Conftest защита от prod БД** (`tests/conftest.py:38-83`): фикстура `clean_db` делает `TRUNCATE ... CASCADE`. Чтобы не уничтожить prod, conftest падает при загрузке, если имя БД не содержит `test`. Резолвит URL по приоритету `TEST_DATABASE_URL` → `DATABASE_URL` → дефолт `catalog_test`. Прецедент: 2026-05-07 случайный pytest на prod БД с `DATABASE_URL=...catalog` обнулил 162K игр.

## Запреты

- Не менять формат webhook `/ingest/offers` без синхронного обновления `services/parsers/parsers/catalog_publisher.py`.
- Не push'ить в remote без явного разрешения пользователя.
