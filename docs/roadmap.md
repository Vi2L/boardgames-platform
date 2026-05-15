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

  **Сделано 2026-05-11 (вторая итерация):**
  - [x] `sudo networksetup -setv6off Wi-Fi` (требовалось из-за IPv6 →
    Cloudflare broken-pipe; Ollama-CLI hardcoded Happy-Eyeballs не работал)
  - [x] `ollama pull bge-m3` (1.2 GB) — установлено, health-check поднимает
    в `available=true` (failures=0)
  - [x] Warmup эмбеддингов: 2 прогонa (limit=1000, limit=5000) → 6000 строк
    в `game_embeddings` (HNSW индекс активен)
  - [x] Smoke-test T2 косвенно через ingest: 63 unmatched от parsers'ов
    обработаны воркером, попали в `skipped` (single candidate < 0.85,
    или ambiguous без LLM-арбитра). Это **правильное** поведение
    Circuit Breaker'а — без LLM неоднозначные офферы идут в manual queue.

  **Осталось пользователю:**
  - [ ] `ollama pull qwen2.5:7b-instruct` — повисло на Cloudflare R2 download
    (~30 мин partial-blobs без прогресса). Pull убит, partials очищены.
    Повторить вручную в новом терминале: `ollama pull qwen2.5:7b-instruct`.
    Без неё T3 LLM-арбитр недоступен → неоднозначные T2-кейсы (2+ кандидата
    score>=0.70) уходят в manual queue вместо auto-resolution.
  - [ ] Полный warmup эмбеддингов на все 162K игр (под `nohup`, ~1.5–4 ч).
    Сейчас покрытие 6000 записей — для top-ранкированных игр, не базы целиком.
  - [ ] Smoke-test T2 single-confident: ingest «Каркасон» с опечаткой,
    проверить что воркер ловит её через T2 cosine >=0.85 (после полного warmup).
  - [ ] Smoke-test T3 (после `ollama pull qwen2.5`): ingest нескольких
    похожих кандидатов, проверить что LLM арбитр выбирает один из них.

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

- [CAT-8] **BGG `/family/{id}` — серии игр + подтягивание всех членов** —
  endpoint возвращает thing-id связанных игр (Catan, Carcassonne, Splendor
  series, Wingspan и т.п.). Реализуется в две стадии:

  *Структура хранения*: новая таблица `bgg_families (id, bgg_family_id, name,
  description, fetched_at)` + связь `bgg_family_members (family_id, game_id,
  bgg_id)`. В `/thing` каждая игра имеет `<link type="boardgamefamily" value="...">` —
  парсить и резолвить в family_id. UI: показ «другие игры серии» в карточке
  (близко к функционалу parent_game_id, но горизонтально вместо иерархии).
  Также может помочь матчингу — игры одной серии часто путаются.

  *Подтягивание членов серии — два механизма работают параллельно*:
  - **Cascade-import при первом обогащении.** После успешного `enrich_one(bgg_id)`
    в `parsers/bgg/service.py`: если у игры были `boardgamefamily` linked,
    запустить fire-and-forget background task через `asyncio.create_task` —
    `fetch_family(family_id)`, для каждого thing-id отсутствующего в каталоге
    вызвать `enrich_one(bgg_id)` с rate-limit (1 req/sec). Защита от рекурсии:
    cascade сам не запускает следующий cascade (флаг в kwargs).
  - **Scheduler-job `bgg_family_refresh`.** Раз в неделю обходит ВСЕ известные
    families в БД, тянет свежий `/family/{id}`, сравнивает members со
    `bgg_family_members`, для новых thing-id запускает `enrich_one`. Закрывает
    кейс «вышел Wingspan: Asia через месяц после нашего импорта Wingspan» —
    cascade при первом импорте не знал об этом.

  *Конфиг*: добавить в `scheduler_configs` запись `bgg_family_refresh` (cron
  по умолчанию `0 5 * * 0` — воскресенье 05:00 UTC). Параметры через JOB_METADATA
  registry, ImportJob-паттерн `run_family_refresh_job`. Cascade — не отдельный
  scheduler-job, а часть `enrich_one`, отключаемая через Settings-флаг
  `BGG_FAMILY_CASCADE_ENABLED` (default true).

- [CAT-9] **BGG `/thing?versions=1` — русские издания** — флаг
  `versions=1` в `/thing` добавляет `<versions><item type="boardgameversion">`
  с полями `<name>`, `<yearpublished>`, `<productcode>`, `<width>/<length>/
  <depth>/<weight>`, `<link type="boardgamepublisher" value="Hobby World">`.
  Может закрыть случаи где Dicefest не покрывает (старые русские издания).
  Pre-условие: разобраться как BGG помечает language='ru' в версии —
  не всегда explicit, часто через publisher (Hobby World, Звезда, GaGa).
  Хранить в новой таблице `bgg_versions (game_id, bgg_id, version_id,
  language, year, publisher, productcode, dimensions, ...)`.

- [CAT-10] **Yearly releases sync — новинки текущего года** — BGG XML API не
  даёт фильтр по году публикации и сортировку по `numvoters`/`numplays`, оба
  необходимы для отбора «новых заметных игр». Решение — HTML-скрейп страницы
  `https://boardgamegeek.com/browse/boardgame?sort=numvoters&yearpublished=YYYY`
  (10 страниц × 100 игр = топ-1000 новинок года).

  *Парсер*: BeautifulSoup-парсер строк `<tr id="row_">` в tbody таблицы —
  thing-id из `<a href="/boardgame/X/...">`, title, year, rating. Для thing-id
  отсутствующих в каталоге — `enrich_one`. Никаких новых таблиц: записи
  попадают в обычный `games` + `game_bgg` через стандартный enrich.

  *Scheduler*: новый job `bgg_yearly_releases` (раз в месяц, например `0 2 1 * *`
  — первое число месяца, 02:00 UTC). Параметры `params.year` (default — текущий
  UTC-год через runtime-вычисление), `params.max_pages` (default 5 = топ-500).

  *Риски HTML-скрейпа*:
  - Вёрстка BGG может измениться → парсер сломается. Mitigation: фикстура
    `tests/fixtures/bgg_browse_2025.html` для unit-теста парсера; при росте
    rate failure'ов в логах — алерт.
  - Anti-bot защиты на browse-страницах. Mitigation: запросы с User-Agent
    реального браузера, mild rate-limit (3-5 сек/стр), retry через
    `_get_with_backoff`-аналог для HTTP 429/503.
  - Bearer token нужен для XML API, но для HTML-страниц `/browse/*` —
    проверить в smoke-тесте (по обсуждениям BGG-форума работает без токена,
    но это не задокументировано).

  *UI* в `/bgg-sync` → вкладка «Расписание» автоматически покажет новый job
  благодаря registry-паттерну. Лог обогащения — в существующей вкладке
  «История» с фильтром `type=bgg-yearly`.

### web-test

**Catalog / matching UI**
- [WT-F6.1] **Закрыть `/api/debug/*` и `/api/dlq/*`** — nginx
  `auth_basic` или JWT-middleware при публичном деплое.
- [WT-F6.2] **Баннер «admin-функции отключены»** при отсутствии
  `CATALOG_API_KEY` (catalog запущен с `REQUIRE_AUTH=1`).

**Поиск**
- [WT-F8] **Log поисковых запросов на странице `/`** — сейчас журнал
  запросов лежит на `/database` → вкладка «Журнал» (`DatabasePage.tsx:55`,
  компонент `SearchesTab`, endpoint `/api/db/searches`). На самой странице
  поиска видны только последние 10 запросов в dropdown'е `SuggestInput`
  (localStorage через `lib/searchHistory.ts`) — это не журнал, а typeahead.

  *Цель*: открываемая панель/drawer прямо с `/`, чтобы быстро посмотреть
  свои последние N запросов с метаданными — когда искал, сколько товаров
  пришло, какие магазины, потраченное время. Это перекрывает потребность
  «помню что неделю назад искал X и что-то странное приходило, нужно
  повторить».

  *Объём (minimal)*:
  - Кнопка «Журнал» рядом с `SearchForm` (icon `History`) → открывает
    `<SearchLogDrawer>` (по аналогии с `ProductDrawer`).
  - В drawer: таблица последних 50 поисков из `/api/db/searches` —
    колонки `query` / `когда` / `results_count` / `duration_ms`
    (если есть в schema; иначе добавить в `db_local.local_searches`).
  - Клик по строке → пре-заполняет `SearchForm` тем же query и
    запускает поиск (через Zustand `useSearchStore.setQuery + submit`).
  - Поиск по тексту запросов (debounced, через query-param `?query=`
    в `/api/db/searches` — уже поддерживается, см. `db.py:101`).

  *Объём (nice-to-have, по согласованию)*:
  - Группировка по дню («Сегодня», «Вчера», «На этой неделе»).
  - Фильтр по магазину (если в `local_searches` появится колонка
    `stores_json` или `result_stores`).
  - Inline-метрика «retry рейт»: процент запросов где какой-то стор
    вернул ошибку (полезно для дебага парсеров).

  *Что НЕ делать*:
  - Не дублировать `/database` → `SearchesTab` полностью. Drawer — это
    «быстрый доступ», полная таблица с пагинацией остаётся там.
  - Не убирать dropdown typeahead с localStorage — он работает мгновенно
    без сетевого запроса и нужен на фокусе input'а.

**Парсеры / Debug**
- [WT-F9] **Убрать пункт «Парсеры» из сайдбара** — `/parsers` сейчас
  показывает 6 карточек `<ParserCard>` с двумя действиями: «Запустить»
  (`POST /parsers/{slug}/run`) и trash (`DELETE /parsers/cache`).
  Функциональность дублирует:
  - Live Test (`/debug` → таб «Live Test») — ручной прогон парсера
    мимо кеша с raw `ParsedProduct`.
  - Источники (`/sources/{provider}`) — это «новый дом» для
    диагностики per-source (видно в App.tsx:13,27).

  *План*:
  - Удалить запись из `NAV` в `App.tsx:22`. `<Route path="/parsers">`
    оставить ещё одну итерацию (deep-link через bookmark'и) с
    `<Navigate to="/sources" replace>` либо с баннером
    «страница переехала на /sources». Через 2-3 недели — удалить роут
    и `ParsersPage.tsx`.
  - Action «Очистить кеш» (Trash) — перенести в `/debug` или в
    `/sources/{provider}` как отдельную кнопку «Invalidate cache»
    рядом с Live Test. Это единственное действие, которого нет ни в
    Debug, ни в Sources.
  - Бейдж «parsers API доступен/ошибка» — уже частично есть в
    `HealthBadge` (сайдбар внизу), дублировать не нужно.

  *Риск*: кто-то ходит по `/parsers` из закладок → редирект + toast
  «страница переехала», лог события в `console.info` для отлова.

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

**BGG Sync UI**
- [WT-F7] **Удобное редактирование всех настроек BGG Sync** —
  на `/bgg-sync` сейчас редактируются только `cron_expr` + `enabled`
  + сырая JSON-строка `params` (`SchedulerHealth.tsx:CronEditor`).
  Остальные настройки разбросаны: BGG bearer token и
  `BGG_FAMILY_CASCADE_ENABLED` — только через ENV/Settings,
  Hotness/GeekList запускаются без явного UI для расписания
  обновления. Цель — единая «панель настроек» вкладки.

  *Объём* (что должно стать редактируемым из UI):
  - Per-job динамическая форма вместо textarea с JSON. Источник схемы —
    JOB_METADATA registry на бэке (`services/catalog/.../scheduler/jobs.py`):
    добавить `params_schema: list[FieldSpec]` (тип, default, label,
    description, validation), endpoint `/api/scheduler/jobs/{id}/schema`
    или включить schema в payload `fetchSchedulerJobs`. Рендер —
    `<SchemaForm fields={...}>` с типами `int`/`bool`/`string`/`enum`/
    `cron`. Эта же схема валидирует payload в `rescheduleJob`.
  - Cron-builder помимо raw expr: пресеты («каждый час», «ежедневно
    в HH:MM UTC», «по воскресеньям 05:00 UTC») + human-readable preview
    («Раз в неделю, воскресенье 05:00 UTC → следующий запуск …»).
    Библиотека-кандидат: `cronstrue` (lightweight, i18n включает RU).
  - Global Settings-секция в шапке вкладки: BGG bearer token (masked),
    `BGG_FAMILY_CASCADE_ENABLED` toggle, rate-limit (req/sec) для cascade.
    Бэк: расширить `/api/settings` (catalog) под whitelist BGG-ключей,
    UI — отдельная карточка `<BggGlobalSettings>` сверху над списком job'ов.
  - Bulk actions: «pause all», «resume all», «trigger all overdue»
    (когда `next_run_at < now() - cron-interval`).

  *Не входит*: миграция Hotness/GeekList панелей под общую форму —
  они уже имеют собственные триггеры (`HotnessPanel.tsx`,
  `GeeklistPanel.tsx`); им добавится только blok «расписание»
  если эти job'ы появятся в `JOB_METADATA`.

  *Зависимости*: CAT-8/CAT-9/CAT-10 добавят новые job'ы
  (`bgg_family_refresh`, `bgg_yearly_releases`) с нетривиальными
  параметрами — без schema-driven формы каждый из них принесёт
  правку фронта руками. Делать WT-F7 **до** ландинга CAT-10
  выгоднее, чем потом ретрофитить три формы сразу.

  *Риски*: schema-driven формы соблазняют переусложнить (валидация
  cross-field, conditional fields). Держаться минимума: тип + label
  + description + default + simple required-flag. Cross-field
  валидация — на бэке в момент `rescheduleJob`.

**Технический долг**
- [WT-T3] **`useInvalidate(domain)` хук** — единая точка
  invalidate для cache-keys одного домена вместо ручного
  перечисления в каждой mutation.

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
  целевая дата **2026-05-28** (две недели стабильной работы L0). Снять
  блокер: 14 дней `parser_log` по avito с `success=1 ratio ≥ 95%`.
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
