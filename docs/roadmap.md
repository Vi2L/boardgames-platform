# Roadmap — boardgames-platform

Верхний уровень roadmap'а монорепо. Сервисные PLAN-ы держат
оперативные задачи и ссылаются сюда из шапки.

- Подробности по web-test: [`services/web-test/PLAN.md`](../services/web-test/PLAN.md)
- Архитектура: [`docs/architecture.md`](architecture.md)
- Параллельная работа агентов: [`docs/parallel-agents.md`](parallel-agents.md)
- Журнал завершённых задач: [`docs/devlog.md`](devlog.md)

Идентификаторы: `[<SVC>-<id>]`, SVC ∈ WT (web-test), CAT (catalog),
PRS (parsers), INFRA (общее).

---

## Сейчас в работе

- [CAT-4] **Matching v2: ML-powered tiered pipeline**
  (закрывает [CAT-1] частично — авто-эвристики теперь делает T3 LLM-арбитр)

  **Сделано (код, 2026-05-10..11):**
  - Миграция 0011: pgvector + `game_embeddings` (HNSW vector(1024)),
    `match_decisions` (T0 cache c TTL per source), `match_log`
    (audit + bulk-revert через batch_id UUID), `match_queue` (outbox).
  - Tiered pipeline `services/catalog/catalog/matching/v2/`:
    - T0 — cache hit по `match_decisions` (sync)
    - T1 — pg_trgm ≥ 0.92 на title/title_ru/aliases (sync)
    - T2 — bge-m3 cosine через pgvector top-K (async, worker)
    - T3 — qwen2.5:7b-instruct LLM-арбитр с JSON-режимом (async)
    - T4 — manual queue (UI)
  - `OllamaHealth` polling 30 сек + Circuit Breaker per-model;
    `ml_enabled` kill-switch без рестарта.
  - APScheduler-jobs: `ml_health_check` (30s), `match_worker` (10s).
  - Замена `find_best_match` → `match_sync` в `routers/ingest.py`,
    запись в `match_log` на каждое изменение `offers.game_id`.
  - Web-test UI: `MlStatusBadge` в HealthBadge, новая вкладка
    «Журнал матчинга» с bulk-revert чекбоксами, `TierBadge`.
  - CLI/admin: `warmup_embeddings.py` (фоном через ImportJob),
    `backfill_title_ru.py`.
  - `Game.title_ru` — first-class колонка денормализованного ru-имени.

  **Deploy — сделано 2026-05-11:**
  - [x] `docker pull pgvector/pgvector:pg16` (Docker Hub был недоступен)
  - [x] `docker compose up -d --force-recreate postgres` (volume сохранился)
  - [x] `alembic upgrade head` на prod + catalog_test
    (fix: `now()` в partial-index predicate — убран, PG требует IMMUTABLE)
  - [x] `backfill_title_ru` — заполнено 985 игр из ru-aliases
  - [x] Rebuild + restart `bg-catalog` и `bg-web-test`
  - [x] Smoke-test sync-pipeline: ingest «Каркассон» → T1 auto-match (score=1.0,
    `trgm_alias_ru`); повтор → T0 cache hit (`cache_hit_auto_t1`); «Каркасон»
    с опечаткой → unmatched + push в `match_queue`; revert log #1 → offer
    обнулён, match_decisions очищен, создана `revert`-запись в audit log.
  - [x] Pytest-покрытие: 38 unit (`test_matching_v2_unit.py`) +
    19 integration (`test_matching_v2_integration.py`) — все зелёные.

  **Осталось пользователю:**
  - [ ] `ollama pull bge-m3 && ollama pull qwen2.5:7b-instruct`
    (Ollama сейчас отдаёт пустой `/api/tags` → T2/T3 skip'аются, async-очередь
    висит в `pending`. После pull — health-check тикает каждые 30s, поднимает
    модели в `available=true`, воркер начинает обрабатывать backlog.)
  - [ ] Warmup embeddings (~1.5–4 ч): `POST /matching/warmup-embeddings`
    или CLI `python -m catalog.scripts.warmup_embeddings`. Pre-условие —
    pull моделей. Можно сначала `--limit 1000` для топ-ранкированных,
    позже полный прогон под `nohup`.
  - [ ] Smoke-test async-pipeline (после warmup): «Каркасон» с опечаткой
    из текущей очереди должен сматчиться T2 на >=0.85 cosine similarity.

  **Технический долг (после боя):**
  - Per-store `MatchProfile` override (схема в БД готова, реализация —
    `MatchProfileLoader` в `engine.py`).
  - Structured embedding text вместо простой конкатенации
    (после анализа miss-rate реальных запросов).
  - Отдельный `kind_classifier` для pre-T2 фильтрации
    (сейчас kind определяется внутри T3 prompt'а).

## Ближайшее (1–2 недели)

_(пусто)_

## Бэклог (без даты)

### Catalog (BGG enrichment)

Расширение покрытия BGG XML API. Сейчас `/thing` парсится частично:
сохраняем title, year, description, designers/publishers/categories/
mechanics, players, age, playtime, cover/thumbnail. Не сохраняем
`<statistics>`, `<poll>`, `<versions>`, `<link type="boardgamefamily">`
и `<link type="boardgameartist">` — см. пункты ниже.

- [CAT-5] **BGG XML stats fields в `game_bgg`** — парсер уже извлекает
  `rating_avg` и `bayes_average` (`parser.py:219-220`), но `upsert_bgg_data`
  их не пишет (`repository.py:130-145`). В колонке `game_bgg` поля
  `bayes_average` / `average` уже есть (приходят из CSV-импорта BGG ranks).
  Добавить: `users_rated` (`<statistics><ratings><usersrated value="N"/>`),
  `average_weight` (complexity 1-5, поле `<averageweight value="X"/>`),
  `num_weights`. Источник истины — XML, а не CSV (CSV отстаёт на неделю).

- [CAT-6] **BGG `<poll>` рекомендации** — три poll'а в `/thing`:
  `suggested_numplayers` (best/recommended/not-recommended per player count),
  `suggested_playerage` (рекомендуемый возраст по голосам коммьюнити —
  может отличаться от `minage` от издателя), `language_dependence`
  (1-5: no necessary in-game text → unplayable in foreign language).
  Хранить как `recommended_players JSONB`, `recommended_age int`,
  `language_dependence int` в `game_bgg`. UX-ценность: показывать
  «лучше всего с 4 игроками» в карточке игры на фронте.

- [CAT-7] **`raw` JSONB blob в `game_bgg`** — сейчас в `upsert_bgg_data`
  стоит `raw={}` с TODO («на этапе 3 заполним полным XML payload для
  аудита»). Заполнить полным распарсенным dict из `parse_thing_xml`
  + raw XML-string в подключе `raw.xml`. Польза: при изменении парсера
  (новые поля типа [CAT-5]/[CAT-6]) можно re-парсить из БД без
  повторного запроса к BGG. Размер: ~10-50KB JSONB на игру, на ~30K
  игр — ~300MB-1.5GB. GIN-индекс не нужен, читаем только по `game_id`.

- [CAT-8] **BGG `/family/{id}` — серии игр** — endpoint возвращает
  thing-id связанных игр (Catan, Carcassonne, Splendor series).
  Новая таблица `bgg_families (id, bgg_family_id, name, description,
  fetched_at)` + связь `bgg_family_members (family_id, game_id, bgg_id)`.
  В `/thing` каждая игра имеет `<link type="boardgamefamily" value="...">` —
  парсить и резолвить в family_id. UI: показ «другие игры серии» в
  карточке (close к функционалу parent_game_id, но горизонтально вместо
  иерархии). Также может помочь матчингу — игры одной серии часто путаются.

- [CAT-9] **BGG `/thing?versions=1` — русские издания** — флаг
  `versions=1` в `/thing` добавляет `<versions><item type="boardgameversion">`
  с полями `<name>`, `<yearpublished>`, `<productcode>`, `<width>/<length>/
  <depth>/<weight>`, `<link type="boardgamepublisher" value="Hobby World">`.
  Может закрыть случаи где Dicefest не покрывает (старые русские издания).
  Pre-условие: разобраться как BGG помечает language='ru' в версии —
  не всегда explicit, часто через publisher (Hobby World, Звезда, GaGa).
  Хранить в новой таблице `bgg_versions (game_id, bgg_id, version_id,
  language, year, publisher, productcode, dimensions, ...)`.

### web-test

**Catalog / matching UI**
- [WT-F6.1] **Закрыть `/api/debug/*` и `/api/dlq/*`** — nginx
  `auth_basic` или JWT-middleware при публичном деплое.
- [WT-F6.2] **Баннер «admin-функции отключены»** при отсутствии
  `CATALOG_API_KEY` (catalog запущен с `REQUIRE_AUTH=1`).

**Технический долг**
- [WT-T3] **`useInvalidate(domain)` хук** — единая точка
  invalidate для cache-keys одного домена вместо ручного
  перечисления в каждой mutation.

### Parsers
- [PRS-1] **DLQ retry с backoff** — cron-таск в parsers,
  пробующий replay'нуть DLQ-записи с экспоненциальным backoff;
  алерт при `attempt_count > 10`.

### Инфра
- [INFRA-1] **`apps/web/`** — пользовательский веб-портал
  (Next.js / Vite + React).
- [INFRA-2] **`apps/mobile/`** — React Native / Expo для записи
  партий и коллекций.
- [INFRA-3] **`packages/shared-ts/`** — TypeScript-клиент catalog
  API, генерируется из `/openapi.json`. Потребители — `apps/web`
  и `apps/mobile`.
- [INFRA-4] **`.github/workflows/`** — CI с change detection
  (пересобирать только то, что менялось).

### Известные ограничения (не баги, а константы)
- **Парсеры — только 4 магазина** (hobbygames, lavkaigr, gaga,
  crowdgames). Добавление нового — задача на parsers + правка
  `STORE_LABELS`.
- **Tesera blocked from non-RU IPs** — Cloudflare режет
  `api.tesera.ru`. Решается прокси (см.
  `services/catalog/CLAUDE.md` секция «Tesera — отложено»).
- **Snapshot retention** — нет автоматической чистки. Решение —
  `prune_snapshots(keep_days=30)` cron'ом в `db_local.py`.

---

## Архив решений (ADR-style, append-only)

- **2026-05-08** — `docs/parallel-agents.md`: дизайн параллельной
  работы нескольких Claude Code-сессий (split C, worktrees,
  subagents).
- **2026-05-08** — Длинный alembic `revision`-id
  (`YYYYMMDD_HHMMSS_<up_revision>`). См. parallel-agents §10.1.
- **2026-05-08** — `IngestRequest` вынесен в
  `packages/shared-py/bg_shared/ingest.py` как single source of
  truth. См. parallel-agents §10.2. *(Закрывает старый пункт
  «packages/shared-py/ → IngestRequest» из Roadmap CLAUDE.md.)*
- **2026-05-08** — `services/web-test/frontend/CLAUDE.md`:
  локальный конфиг для frontend-сессии в split-режиме.
- **2026-05-08** — `.gitignore`: `.claude/scheduled_tasks.lock`
  как runtime-state.
- **2026-05-08** — Pre-commit hook `bin/check-alembic-heads.sh`
  через `.claude/settings.json:hooks.PreToolUse[Bash]`.
- **2026-05-07** — `uv workspace` вместо pip-tools
  (единый `.venv/`, editable members).
- **2026-05-07** — `git subtree` для сборки монорепо из 4
  репозиториев с сохранением истории.
- **2026-05-07** — Catalog satellite-схема (`game_bgg`,
  `game_wikidata`, `game_dicefest`) с `raw jsonb` + GIN-индексами
  по часто-запрашиваемым ключам.
