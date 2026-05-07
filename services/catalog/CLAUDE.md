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
+ `fetched_at`. Связь с canonical `games` через `game_id`. Reference design —
`~/Projects/board_game_db` (есть `GameWikidata`, `TsGame`, `DfGame` etc.).

```
games  (canonical, slim)
  ├── game_aliases   (cross-source aliases для матчинга, +language, +verified)
  ├── game_bgg       (1:1) — BGG: rank, scores, designers, mechanics, raw
  ├── game_wikidata  (1:1) — labels/aliases/descriptions per language, entity_id
  └── (FUTURE) game_tesera, game_dicefest
```

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
.venv/bin/python -m catalog.scripts.import_bgg_ranks /path/to/boardgames_ranks.csv
```

Заливает 176K записей в `games` + `game_bgg` за ~50 секунд. Идемпотентно
(`ON CONFLICT (bgg_id) DO UPDATE`). Поля: rank, bayes_average, average,
users_rated, is_expansion, subtype_ranks. Description/mechanics/designers
остаются пустыми — для них нужен XML API через `POST /import/bgg`.

### Wikidata (русские локализации + descriptions)

```bash
.venv/bin/python -m catalog.scripts.import_wikidata --only-rank-le 1000
```

Обходит топ-N игр по rank, обогащает `game_wikidata` (labels/aliases/
descriptions per language) и пишет ru-локализации в `game_aliases` со
`source='wikidata'`, `language='ru'`. 1 req/sec по best practice Wikidata,
fully recoverable retry на 429/5xx. Топ-1000 — ~17 минут. Для полного прогона
по 30K ranked-играм — ~8 часов под `nohup`.

Алгоритм: SPARQL `VALUES`-batch (50 ID на запрос) → entity-API per Q-id →
parse → upsert. Источник адаптирован из `~/Projects/board_game_db/app/wikidata.py`.

### XML API BGG (точечное полное обогащение)

```bash
curl -X POST 'http://localhost:8012/import/bgg?wait=true' \
  -H 'content-type: application/json' -d '{"bgg_id":822}'
```

Скачивает XML, заполняет `game_bgg` `description`/`designers`/`mechanics`/
`categories`/`min_players` и т.д. По одной игре за вызов (rate-limit BGG).

### Tesera — отложено

Cloudflare блокирует tesera.ru / api.tesera.ru с большинства не-RU-IP.
Когда появится прокси — добавим `game_tesera` (схема готова в плане
`~/.claude/plans/woolly-wobbling-simon.md`) и `import_tesera_html.py`.

## Контракты с соседями

### Webhook от `parsers` — `POST /ingest/offers`

**Source of truth для контракта.** Менять формат — только синхронно с
`~/Projects/parsers/parsers/catalog_publisher.py`.

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
| `POST /import/{bgg,tesera}` | `admin` | запуск импортёра |
| `GET /import/jobs/{id}` | `read` | статус job'ы |
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
- **Merge games не удаляет source**: после `POST /games/merge` source-игра помечается `status='merged'` и пишет `meta.merged_into=target_id`. Для трассировки auto-match'ей, которые могли сослаться на старый id. Реальные offers и aliases переезжают на target. UI (`web-test`) фильтрует merged-игры через `status` колонку.
- **`reassess` уважает `manual`/`rejected`**: операторские решения не пересчитываются — single-reassess отвечает 409, batch-reassess их игнорирует через WHERE `match_status='unmatched'`. Чтобы пересмотреть manual-связку — сначала reject/unlink вручную.
- **`find_match_candidates` группирует per-game**: одна игра может всплыть и через `title`, и через `alias` одновременно — берём `MAX(score)` и `via` от лучшего. Иначе UI показывал бы дубль одной игры со score 0.85 и 0.72.

## Запреты

- Не менять формат webhook `/ingest/offers` без синхронного обновления `~/Projects/parsers/parsers/catalog_publisher.py`.
- Не push'ить в remote без явного разрешения пользователя.
