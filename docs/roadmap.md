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

- **`feat/admin-panel-redesign`** — полный редизайн `web-test` под единый
  design-system (handoff в `.scratch/admin-panel-design/`). Этапы:
  - [x] **PR 1 · Foundation** — design tokens + `src/components/ui/*` +
    `AppShell` + `/__design`. Сделано (commit `1e3c107`, см. devlog `WT-DESIGN-PR1`).
  - [x] **WT-MATCH-UX** — точечный апгрейд `/matching` (header / control /
    queue / single / keyboard / inline confirms). Параллельный track в gray/violet,
    не на новых tokens. Сделано (commit `4d7826e` + SPA fix `d348395`).
  - [ ] **PR 2 · Proof: Matching на zinc/indigo** — переписать `MatchingSection`
    из `CatalogPage.tsx` на новый ui. Это main proof из ТЗ §7.2. Спека —
    `.scratch/admin-panel-design/pages/01-matching.md` (three-pane + drawer
    + keyboard). MatchingSection — legacy, заменена `/matching` (WT-MATCH-UX);
    глубокий переход на zinc/indigo откладывается до отдельной задачи.
  - [x] **WT-DESIGN-PR3a/b/c · Раскатка дизайна** (ветка `feat/wt-redesign-rollout`):
    - 3a — гигиена 11 страниц (табы → `ui/Tabs`, эмодзи → lucide, ad-hoc
      статусы → `<Badge status="…">`, gray→zinc).
    - 3b — `CatalogPage` Games по `pages/03-games.md` (sticky thead, indigo
      accent, SourceBadge через token-cls, Button-обёртки, columns picker).
    - 3c — гигиена 51 sub-компонента (`components/*` — violet→indigo,
      эмодзи `✓`/`✗`/`⚡` → CheckCircle2/XCircle).
    Сделано, см. devlog `WT-DESIGN-PR3`.
  - [x] **WT-DESIGN-PR4 · Job UI** — `components/jobs/` (JobView + PhaseStrip
    + adapters), интегрирован в `bgg-sync/JobHistoryTable` и `catalog/
    BggImportPanel`. Сделано (commit `820af0d`, devlog WT-DESIGN-PR4/PR5).
  - [x] **WT-DESIGN-PR5 · Search WT-F11 (frontend-fallback)** — Master-таблица
    группировка через `titleSimilarity` clustering + UnmatchedSection.
    Toggle group/flat в `useSearchStore`. Backend group-by-game endpoint
    — не блокирующая зависимость. Сделано (commit `a481da2`).
  - [x] **WT-F11-DRAWER** — полный `<GameGroupDrawer>` с 4 табами
    (Офферы/История/Матчинг/Raw), split-view через ui/Drawer, Cmd+↑/↓
    навигация, frontend-fallback для Матчинга через fetchMatchCandidates.
    Сделано (commit `55febcc`, devlog `WT-F11-DRAWER`). Backend var. A
    (linked offers + unlink) ждёт `/search/grouped` endpoint.
  - [ ] **WT-DESIGN-SUITERUN** — `suiteRunToJobLike()` adapter +
    использование `<JobView>` в `components/testing/SuiteRunner`. Сейчас
    SuiteRunner с собственной inline-вёрсткой.

  Merge в main — после PR 2 проверки на проде. До этого ветка отдельная.

## Ближайшее (1–2 недели)

_(пусто)_

## Бэклог (без даты)

### Catalog (matching v2 — follow-ups после CAT-4)

- [CAT-4.1] **MatchProfile per-store override**.
  **Готово:** таблица `match_profiles` (миграция 0006) + endpoint
  `GET /matching/profiles` (`routers/sources.py:243`).
  **Осталось:** `MatchProfileLoader` в `engine.py` (`MatchEngine.__init__(session,
  profile=None)`), пробрасывать профиль через `match_sync(store_slug=...)`,
  переопределять `match_t1_auto_threshold` / `match_t2_auto_threshold` /
  `t2_confidence_margin` (зашит как 0.05 в `embeddings.py:153`).
  **Зачем:** для магазинов с шумным title (Wildberries добавляет SKU/серию —
  нужен более низкий T1 порог) vs HobbyGames (чистые title — можно поднять T2).
- [CAT-4.2] **Structured embedding text** — `embedder.build_text` сейчас
  просто конкатенирует `title_ru + title + aliases[:5]`. Лучше bge-m3
  понимает структурированный текст: `"GAME: {title_ru} ALSO: {title}
  SYNONYMS: {aliases}"`. Делать после анализа miss-rate реальных T2-запросов
  в проде — может оказаться, что текущий простой подход уже даёт ≥85%
  precision и улучшение не стоит реиндексации 162K эмбеддингов.
- [CAT-4.3] **kind_classifier pre-T2**.
  **Готово:** `kind_filter` в `vec_search_top_k` (`embeddings.py:31-100`) +
  `predicted_kind` в `ctx` — но это **post-T2 path** для T3 re-loop'а
  (когда LLM назвал `kind` и нужен повторный vector-search с фильтром).
  **Осталось:** **pre-T2** rule-based классификатор по словам «дополнение»/
  «expansion»/«big box» в title; передавать `kind_filter` в `vec_search_top_k`
  ещё до первого embed-вызова. Точка вставки: `engine.py:103` перед
  `tier_2_vector`. Сэкономит embed-вызовы на офферах, где kind виден из title.
- [CAT-4.6] **Snapshot-таблица queue_depth для точного `depth_history`**.
  **Сейчас:** `GET /matching/queue/depth` реконструирует depth по
  `created_at`/`processed_at` (`queue_repo.depth_history`) — аппроксимация,
  не точная. **Осталось:** новая таблица `queue_depth_snapshots(ts, pending,
  processing, skipped, failed)` + cron-job раз в минуту пишет snapshot.
  Endpoint читает оттуда. Trade-off: ~1.4MB/год (60*24*365 строк × ~40 байт).
- [CAT-4.8] **Skipped-таблица hover-actions + shift-range select**.
  Handoff `06-matching-v2-improvements.md` §D.5 — в Очереди → таблица skipped:
  hover-actions (re-enqueue / view in journal / run v2), shift+click range
  select, relative time для `processed_at` (живо обновляемое). Сейчас оставлено
  как в предыдущей версии — только checkbox-выделение.

### Catalog (BGG enrichment)

Расширение покрытия BGG XML API. Сейчас `/thing` парсится частично:
сохраняем title, year, description, designers/publishers/categories/
mechanics, players, age, playtime, cover/thumbnail. Не сохраняем
`<statistics>`, `<poll>`, `<versions>`, `<link type="boardgamefamily">`
и `<link type="boardgameartist">` — см. пункты ниже.

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

**Поиск**
- [WT-F8.1] **Persistent search history (опционально).** Изначальный WT-F8
  («drawer с журналом запросов на `/`») закрыт как «решено иначе» —
  таб `api-log` в SearchPage уже даёт API-логи текущей сессии (см. devlog
  2026-05-16). Этот узкий follow-up заводим **только если** возникнет
  потребность в **архивном** журнале (между сессиями, поиск по тексту,
  фильтр по магазину) — данные уже есть в `/api/db/searches`. До явной
  потребности — не делать.

**Парсеры / Debug**
- [WT-F9.1] **Удалить `pages/ParsersPage.tsx` + redirect route** —
  follow-up к WT-F9 (см. devlog 2026-05-18). Route `/parsers` сейчас
  Navigate-редиректит на `/debug`; через 2-3 недели (после 2026-06-10)
  удалить redirect, `ParsersPage.tsx` и `ParserCard.tsx`.

- [WT-F10] **Аудит функциональности `/debug` и план расширения** —
  пройти по 5 текущим табам (Live Test / Сравнить / По URL / Контракт
  / Raw HTTP) и проверить:
  - Каждый таб реально нужен, нет dead-кода после слияния `/parsers`
    в Debug (если WT-F9 заехал).
  - Все endpoints `/api/debug/*` (`app/api/debug.py`) имеют UI;
    нет «orphan endpoints» без потребителя.
  - Контракт-валидатор покрывает все 6 парсеров (heatmap field-coverage
    не отстал от новых полей `extra.on_sale`, `extra.in_stock`).

  *Кандидаты на добавление* (накинуть и решить):
  - **Replay по `parser_log`** — выбрать запись из истории парсера
    (table `parser_log` в parsers-БД), переиграть запрос на текущей
    версии кода, посмотреть diff с записанным результатом. Закрывает
    кейс «магазин поменял HTML, что именно у нас сломалось».
  - **Прогон по списку URL** — массовый Live Test (загрузить CSV
    из 50 URL'ов одного магазина, посмотреть field-coverage и тайминги
    на батче). Сейчас «По URL» — только 1 URL за раз.
  - **TLS-impersonation profile picker** — для curl-cffi парсеров
    (avito, wildberries) — переключатель `impersonate="chrome124"` /
    `safari17` / `firefox120` в Live Test, чтобы быстро проверить
    как меняется ответ при смене JA3.
  - **HTTP request recorder & replay** — записать сессию curl-cffi
    (headers + cookies + JA3) в фикстуру `tests/fixtures/<store>/`,
    повторить в pytest. Сейчас это делается руками с raw-снепшотами.
  - **Diff двух snapshot'ов** — есть для тестов (`/testing/diff`),
    добавить в Debug кнопку «сравнить с snapshot N дней назад»
    прямо из Raw HTTP таба.
  - **Headless rate-limit tester** — серия запросов с разным интервалом,
    графики 200/429/403 по времени. Помогает калибровать
    `_get_with_backoff` для парсеров.

  *Не входит*: переезд `/sources` в `/debug` — это разные домены
  (источники = «что подключено», debug = «как это диагностировать»).

**Кросс-страничные UX-паттерны**
- [WT-F12] **Bulk-actions sticky toolbar pattern.** Базовый примитив
  `components/ui/Toolbar.tsx` уже есть, но применён точечно. Привести
  к единому виду на 3 страницах с множественным выбором: matching queue
  (link/reject N), DLQ (re-enqueue N), snapshots (compare/delete N).
  Логика: checkbox-колонка → sticky-снизу toolbar
  `Selected: N · [Action 1] [Action 2] · Clear` → **один confirm** на
  весь batch (не N модалок). Связать с keyboard-shortcuts: Shift+click
  для range-select, Cmd+A для select-all-visible, Esc для clear-selection.

**Технический долг**
- [WT-T3] **`useInvalidate(domain)` хук** — единая точка
  invalidate для cache-keys одного домена вместо ручного
  перечисления в каждой mutation.
- [CAT-13] **Вынести общий enrich-loop в `catalog/importers/_enrich_loop.py`**.
  Сейчас один и тот же цикл (per-bgg_id `enrich_one` + `await session.commit()`
  + `try/except errors += 1` + `asyncio.sleep(rate_limit_sec)`) повторяется
  трижды: `bgg_geeklist.py`, `bgg_yearly.py`, `bgg_family.py` + базовая
  версия в `service._cascade_family_enrich`. Целевая API:
  `enrich_missing_bgg_ids(missing, session_factory, client, *, rate_limit_sec,
  log, context) -> tuple[int_imported, int_errors]`. Все 4 сайта схлопнутся
  до 2 строк. Trigger: при добавлении 5-го importer'а (например, CAT-9 versions).
- [CAT-14] **`BggClient.maybe(client)` контекст-менеджер**. Паттерн
  `own_client = client is None; if own_client: await client.__aenter__()`
  с зеркальным `__aexit__` повторяется в `search_games`, `enrich_one`,
  `enrich_batch`, `run_yearly_releases_sync`, `run_family_refresh_sync`,
  `run_geeklist_sync`. Хелпер `@asynccontextmanager` упрощает все шесть
  мест до `async with BggClient.maybe(client) as c: ...`.
- [CAT-15] **`catalog/utils/time.py:utcnow()`**. Сейчас `_utcnow()` /
  `_current_utc_year()` дублируются в `scheduler.py`, `bgg_family.py`,
  `bgg_yearly.py`, `bgg_geeklist.py`. Один общий модуль; тривиальный
  cleanup, делается при следующем касании любого из этих файлов.

### Parsers
- [PRS-1] **DLQ retry с backoff** — cron-таск в parsers,
  пробующий replay'нуть DLQ-записи с экспоненциальным backoff;
  алерт при `attempt_count > 10`.
- [PRS-3] **Avito L2-fallback через camoufox** — пока L0
  (curl-cffi + `/web/1/js/items`) даёт 200, fallback не нужен.
  Завести, если в проде на avito.ru начнётся стабильный поток 429/403:
  при ошибке L0 переключаться на browser-сервис, который дёргает тот же
  endpoint через camoufox с накопленным persistent profile. См. devlog
  2026-05-14 [AVT-CONT].
- [PRS-4] **Удаление `services/parsers/DEPRECATED/chrome-extension/`** —
  целевая дата **2026-06-15** (перенесено с 2026-05-28). Блокер
  ещё не снят: на 2026-05-18 14-дневный success ratio Avito L0 = 76%
  (требуется ≥95%). Худшие дни: 2026-05-10 (33%), 2026-05-11 (60%),
  2026-05-15 (66.7%). Перепроверить через месяц — если стабилизируется
  на 95%+, удалить папку. Если нет — заводить PRS-3 (L2-fallback через
  camoufox).
- [PRS-6.1] **WB L2-fallback через browser-service** — последний пункт из
  закрытого PRS-6 (см. devlog 2026-05-18). exp-backoff + chrome131 +
  per-store Circuit Breaker (PRS-7, devlog 2026-05-18) уже сильно
  смягчили 429. Если рейт всё равно держится >5% — при открытом
  WB breaker'е перебрасывать на camoufox с persistent profile
  (по аналогии с Ozon).

  *Метрика успеха*: rate ошибок 429 в `parser_log` падает ниже 5%.
  Без замера — не катить, иначе ловим overkill.

  *Зависимости*: WT-F10 пункт «Headless rate-limit tester» — удобно
  иметь UI-инструмент для калибровки до выкатки.

- [PRS-5] **WB enrichment через `card.wb.ru/cards/v{N}/detail`** — search
  даёт только цену/название/бренд/рейтинг. Через `card.wb.ru` доступны
  characteristics (players, age, playtime, description). Сейчас не делаем
  потому что (1) `card.wb.ru` блокирует DC-IP жёстче `search.wb.ru` и
  (2) для MVP цены без характеристик хватает. Завести если возникнет
  потребность в WB-данных для matching v2 (T2 embeddings).


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

- [INFRA-6] **Процессный аудит `.claude/settings.json`.** Файл накапливает
  Bash-разрешения и pre-commit-хуки от старых страниц и команд web-test.
  Раз в квартал (или после крупного merge типа admin-panel редизайна) —
  пройтись и удалить устаревшее: команды, которых больше нет в скриптах;
  hooks, ссылающиеся на удалённые файлы. Это **процессная** задача, не
  одноразовая — заведена сюда как напоминание не забыть после
  ландинга крупных рефакторов. Скрипт-помощник: `grep -hoE 'allow.*Bash'
  .claude/settings*.json` сверить с `bin/*` и `package.json:scripts`.

### Известные ограничения (не баги, а константы)
- **Парсеры — 6 источников** (hobbygames, lavkaigr, gaga,
  crowdgames, avito, wildberries). Добавление нового — задача на parsers +
  правка `STORE_LABELS`. Avito и Wildberries работают через TLS-impersonation
  (curl-cffi с `impersonate="chrome124"`) — остальные ходят по обычному HTTP.
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
