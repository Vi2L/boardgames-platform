# Roadmap — boardgames-platform

Верхний уровень roadmap'а монорепо. Сервисные PLAN-ы держат
оперативные задачи и ссылаются сюда из шапки.

- Подробности по web-test: [`services/web-test/PLAN.md`](../services/web-test/PLAN.md)
- Архитектура: [`docs/architecture.md`](architecture.md)
- Параллельная работа агентов: [`docs/parallel-agents.md`](parallel-agents.md)

Идентификаторы: `[<SVC>-<id>]`, SVC ∈ WT (web-test), CAT (catalog),
PRS (parsers), INFRA (общее).

---

## Сейчас в работе

- [WT-F4.1-extended] **parsers DB explorer** — ✅ **ЗАВЕРШЕНО** (8/8 виджетов).
  Реализованы: Inventory, ProductsBrowser, Analytics, Timeline, LatencyHistogram,
  StoreDistribution, ParserBreakdown, RawKeys — новая вкладка «БД парсеров: графики».
  Vanilla `/dashboard` в parsers можно отключить.

## Ближайшее (1–2 недели)

- [WT-F1.6] **Selectors playground** — расширение URL probe (F1.4)
  с textarea для CSS-селектора и применением к raw HTML через
  DOMParser. Чисто фронт.
- [CAT-1] **Авто-matching эвристики** — расширить `find_best_match`
  и `find_match_candidates`: бонус +0.1 при match по alias, штраф
  при несовпадении publisher/year, обработка expansions
  («Каркассон: Король и разбойник» не должна матчиться на базовый
  «Каркассон»).
- [WT-F4.4-extended] **Suite baselines auto pass/fail** —
  автосравнение `min_count` (и потом `expected_stores`,
  `min_field_coverage`) на прогоне с подсветкой строк pass/fail.

## Бэклог (без даты)

### Catalog / matching
- [WT-F2.5] **Offer history page** — вкладка «офферы игры» на
  странице каталога (catalog уже отдаёт через `Game.offers`).
- [WT-F2.6] **Bulk-import wizard top-N** — UI вокруг
  `import_bgg_ranks.py`: импорт топ-N по rank.
- [WT-F2.7] **RU-first автоподсказки** — компонент `GameSuggestRow`
  с RU-названием как первичным, EN как бледным суффиксом; при выборе
  подставляется RU; `getDisplayName(game)` в `lib/catalog.ts`
  как shared-хелпер.

### Cross-service / инфра
- [PRS-1] **DLQ retry с backoff** — cron-таск в parsers,
  пробующий replay'нуть DLQ-записи с экспоненциальным backoff;
  алерт при `attempt_count > 10`.
- [WT-F5.3] **Status page** — `/status` с историей пингов и
  timeline'ом unmatched-counter'а (для ретроспектив).
- [INFRA-1] **`apps/web/`** — пользовательский веб-портал
  (Next.js / Vite + React).
- [INFRA-2] **`apps/mobile/`** — React Native / Expo для записи
  партий и коллекций.
- [INFRA-3] **`packages/shared-ts/`** — TypeScript-клиент catalog
  API, генерируется из `/openapi.json`. Потребители — `apps/web`
  и `apps/mobile`.
- [INFRA-4] **`.github/workflows/`** — CI с change detection
  (пересобирать только то, что менялось).

### Auth и безопасность
- [WT-F6.1] **Закрыть `/api/debug/*` и `/api/dlq/*`** — nginx
  `auth_basic` или JWT-middleware при публичном деплое.
- [WT-F6.2] **Баннер «admin-функции отключены»** при отсутствии
  `CATALOG_API_KEY` (catalog запущен с `REQUIRE_AUTH=1`).

### Технический долг
- [WT-T1] **`AliasList.tsx` → удалить** — заменён на
  `AliasEditor.tsx` после F2.2, файл остался как dead-code.
- [WT-T2] **Snapshot diff `extra` — фильтр** — сейчас
  разбивается на `extra.<key>`, при 100 ключах в `raw` UI шумный.
  Whitelist важных raw-ключей или фильтр «изменения ≥ X%».
- [WT-T3] **`useInvalidate(domain)` хук** — единая точка
  invalidate для cache-keys одного домена вместо ручного
  перечисления в каждой mutation.

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
