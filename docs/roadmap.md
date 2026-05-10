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

  **Что осталось — deploy и доводка:**
  - [ ] `docker pull pgvector/pgvector:pg16` (Docker Hub был недоступен)
  - [ ] `docker compose up -d --force-recreate postgres` (volume сохраняется)
  - [ ] `cd services/catalog && uv run --package boardgames-catalog alembic upgrade head`
  - [ ] `ollama pull bge-m3 && ollama pull qwen2.5:7b-instruct` (если не стоят)
  - [ ] `uv run --package boardgames-catalog python -m catalog.scripts.backfill_title_ru`
  - [ ] Warmup embeddings (~1.5–4 ч под `nohup` или через UI
    `POST /matching/warmup-embeddings`)
  - [ ] Smoke-test sync-pipeline: ingest «Каркассон» → проверить
    T0 cache hit на повторе, T1 на лёгкой опечатке.
  - [ ] Smoke-test async-pipeline (после warmup): unmatched оффер →
    воркер забирает → T2 match или T3 арбитр → запись в match_log.
  - [ ] Pytest-покрытие: `tests/test_matching_v2/`
    (`test_normalize_title`, `test_tier_0_cache_hit_miss_ttl`,
    `test_tier_1_above_below_threshold`, `test_circuit_breaker`,
    `test_llm_parse_response_robust`).

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
