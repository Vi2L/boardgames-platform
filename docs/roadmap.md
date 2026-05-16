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
    + keyboard).
  - [ ] **PR 3+ · Раскатка** — Games (`/catalog`), Search WT-F11 group-by-game,
    Job UI (`/bgg-sync`), `/sources`, `/debug`, `/testing`, `/dlq`, `/status`,
    `/parsers`, `/database` — по одному PR на страницу.

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
- [CAT-4.4] **Legacy ingest-тесты под matcher v2 пороги**.
  **Статус:** `test_ingest_typo_still_matches` (`tests/test_ingest_and_matching.py:69-91`)
  **падает** — комментарий ожидает «trgm ~0.73 > порог 0.6», реальный
  порог сейчас 0.92.
  **Варианты исправления:** (a) переписать ожидания под
  `match_status='unmatched'` + проверку push в `match_queue` (тогда тест
  фиксирует поведение «typo больше не auto-T1, идёт в ML/manual»),
  (b) переключить тесты на pre-seeded T0 cache для детерминированности
  (`match_decisions` с готовым `game_id` ловит typo через cache hit).
- [CAT-4.5] **Auto-recovery rules runner**.
  **Готово:** таблица `auto_recovery_rules` (миграция 0014), CRUD endpoints
  (`routers/auto_recovery.py`), UI секция в `/matching → Очередь` с create/toggle/delete.
  **Осталось:** scheduler-job `auto_recovery_runner` (раз в минуту) который
  читает `enabled=true` правила, проверяет condition против актуального
  ml-status/job-status и выполняет action. Сейчас правила сохраняются
  «armed but not executing». MVP типов condition:
  `{type: 'circuit_state', model, becomes: 'closed'}`,
  `{type: 'job_completed', type: 'warmup-embeddings', status: 'done'}`.
  Actions: `{type: 're_enqueue_skipped', filters: {reason?, store_slug?}}`,
  `{type: 'trigger_job', job_id: str}`. Дедуп — через `last_triggered_at`
  + минимальный interval (например 5 минут).
- [CAT-4.6] **Snapshot-таблица queue_depth для точного `depth_history`**.
  **Сейчас:** `GET /matching/queue/depth` реконструирует depth по
  `created_at`/`processed_at` (`queue_repo.depth_history`) — аппроксимация,
  не точная. **Осталось:** новая таблица `queue_depth_snapshots(ts, pending,
  processing, skipped, failed)` + cron-job раз в минуту пишет snapshot.
  Endpoint читает оттуда. Trade-off: ~1.4MB/год (60*24*365 строк × ~40 байт).
- [CAT-4.7] **Intermediate match_log entries в ingest для T0/T1**.
  **Сейчас:** worker пишет `t2_progress` / `t3_progress` (`auditor.log_progress`),
  но ingest при miss T0+T1 не пишет ничего — UI SingleMatchTab показывает
  T0/T1 как `skipped` для re-run. **Осталось:** при `match_sync` пиcать
  `t0_progress` (cache miss) / `t1_progress` (best score < auto_threshold)
  в match_log с короткой meta. Это даст полные live-stages в Штучном.
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

- [CAT-10] **Yearly releases sync — новинки текущего года**.
  ⚠ **Уже сделана узкая часть** (коммит `0b70825` — `year_in` селектор для
  ручного batch-enrich). Осталась автоматическая часть: HTML-скрейп +
  scheduler-job для регулярного импорта новинок без участия оператора.

  BGG XML API не даёт фильтр по году публикации и сортировку по
  `numvoters`/`numplays`, оба необходимы для отбора «новых заметных игр».
  Решение — HTML-скрейп страницы
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

### Catalog (audit log + cache hygiene)

- [CAT-11] **Audit log retention.** `match_log` растёт неограниченно: один
  `reassess-all` пишет тысячи строк, повторных пересчётов в неделю — десятки.
  Завести eviction: APScheduler-job `match_log_retention` (раз в сутки)
  удаляет строки **старше 90 дней** по `created_at`, **кроме** ещё не
  реверченных (`reverted_at IS NULL AND action != 'revert'` сохраняем —
  потенциально нужны для отката). ENV: `MATCH_LOG_RETENTION_DAYS=90`.
  Точка реализации: `catalog/scheduler.py` + новый репозиторий-метод
  `auditor.evict_older_than(days=90)`. Перед удалением — `COUNT(*)` в
  лог для аудита. Связано с CAT-12 (negative cache тоже стоит чистить).

- [CAT-12] **Negative cache invalidation API.** Сейчас `match_decisions`
  с `game_id IS NULL` (negative cache, источник `manual` от `reject`)
  живёт **бессрочно** (`ttl_days = NULL`) — оператор может пересмотреть
  решение только руками через SQL `DELETE`. См. ограничение в
  `docs/cat-4-matching-v2.md` §10.
  - `DELETE /matching/decisions/{title_norm}` — точечная инвалидация.
  - `POST /matching/decisions/invalidate` body
    `{store: "...", title_contains: "...", only_negative: true}` —
    bulk-вариант для случая «оператор переслушал политику reject'ов».
  - UI: в `MatchLog` рядом со строкой `reject` — кнопка «Invalidate decision».
  Audit: каждая инвалидация → запись в `match_log` с `action='invalidate_decision'`.

### web-test

**Catalog / matching UI**
- [WT-F6.1] **Закрыть `/api/debug/*` и `/api/dlq/*`** — nginx
  `auth_basic` или JWT-middleware при публичном деплое.
- [WT-F6.2] **Баннер «admin-функции отключены»** при отсутствии
  `CATALOG_API_KEY` (catalog запущен с `REQUIRE_AUTH=1`).

**Поиск**
- [WT-F11] **Группировка результатов по игре**.
  ⚠ **Семантический дрейф:** коммиты `de24cce`/`c9dd058`/`1de0edf` от
  2026-05-16 имеют label `[WT-F11]`, но содержательно относятся к
  редизайну админ-панели матчинга (см. `docs/web-test-redesign-brief.md`),
  а **не** к группировке результатов поиска. Сама эта задача
  (`GroupedResultsTable` в SearchPage) ещё не начата. В будущих коммитах
  под admin-panel-редизайн использовать другой label, чтобы не путать.

  Сейчас `ResultsTable`
  (`frontend/src/components/search/ResultsTable.tsx`) рисует плоский
  список `ProductOut[]`: один и тот же «Каркассон» из 6 магазинов = 6
  строк с разными названиями (HG: «Каркассон. Базовый набор»,
  WB: «Carcassonne настольная игра CGA1001», Avito: «Каркассон новый
  в плёнке»). Нужна одна строка с агрегатами + раскрытие со списком
  магазинов/цен.

  *Цель UX*:
  - Одна строка на «игру» с колонками: title (каноничный), **min/max
    цены среди магазинов**, **кол-во магазинов в наличии**, sparkline
    разброса (опционально).
  - Клик/тап → раскрытие inline-блока (или drawer) с текущей таблицей
    как «sub-rows»: магазин / цена / sale-бейдж / loyalty / link.
  - Кнопка-переключатель в `SearchForm`: «Группировать по игре / Плоский
    список» — плоский остаётся для дебаг-сценариев (это же debug-портал).
  - Несгруппированные «осиротевшие» офферы (catalog не смог сматчить) —
    отдельная секция внизу «Не сматчено (N)», тоже раскрываемая.

  *Архитектурная развилка — как определять «одинаковая игра»*:

  - **Вариант A (frontend-only fuzzy)**: использовать существующий
    `lib/similarity.ts` (Jaccard по токенам) + порог. Дёшево (0 backend
    изменений), но путает «Каркассон» с «Каркассон: Замки и крепости» —
    expansion'ы склеит с base. Подходит как **MVP / fallback**, когда
    catalog недоступен.
  - **Вариант B (catalog batch-lookup)**: новый endpoint
    `POST /catalog/matching/lookup-batch` (catalog) — **не путать с уже
    реализованным `/matching/offers/search`**, это fuzzy-lookup offer'ов
    по title для admin-UI, а нужен **батч-резолв game_id для списка
    title'ов из поиска**. Принимает
    `[{store_slug, title, url, price_rub}]`, возвращает массив
    `[{idx, game_id, game_title_ru, match_score, match_tier}]` либо
    `null` для не-сматченных. Внутри переиспользует `MatchEngine`
    (`services/catalog/catalog/matching/engine.py`) — T0 cache hit
    через `match_cache` для уже виденных пар (store, title), T1/T2 для
    новых. Этот же путь уже работает в `/ingest/offers`, просто без
    записи в `offers` (read-only режим). **Это правильное направление.**
  - **Вариант C (parsers возвращает game_id)**: parsers сам зовёт catalog
    при отдаче результата. Нарушает изоляцию parsers ↔ catalog, добавляет
    catalog в hot-path SSE-поиска (повышает latency). **Не делать.**

  *План реализации (рекомендуется B + A fallback)*:
  1. **Backend (catalog)**: `POST /matching/lookup` (admin? или public —
     решить по auth). Принимает батч, возвращает резолв через
     `MatchEngine.match_offer(...)` в режиме `dry_run=True` (не пишет
     в `match_cache`, либо пишет с TTL). Лимит батча 100. Кеш в Redis
     по `(store_slug, normalized_title)` на 1 час — поиск часто повторяет
     те же офферы.
  2. **Backend (web-test)**: `app/api/search.py` после получения всех
     результатов SSE — финальный батч-вызов в `catalog_client.lookup(...)`,
     отдаёт фронту дополнительное SSE-событие `event: matches` с массивом
     `{product_id, game_id, game_title_ru}`. Не блокирует основной поток —
     эмитим события `results` сразу, `matches` приходит «дозаливкой».
  3. **Frontend**:
     - Расширить `ProductOut` опциональным `match?: {game_id, game_title_ru,
       tier}` (типы в `types/api.ts`).
     - В `SearchPage` собрать `Map<game_id, ProductOut[]>` + bucket
       `unmatched` для `match=null`.
     - Новый компонент `GroupedResultsTable` (рядом с `ResultsTable`):
       строки игр + `expandedGameIds: Set<number>` в локальном state,
       раскрытие через `<details>` или ручной toggle. Sub-rows — те же
       `<ResultRow>` что в плоском режиме (вынести как компонент из
       `ResultsTable`).
     - Тоггл «Группировать / Плоский» в `SearchForm`, persist в
       `useSearchStore` (Zustand v2 persist).
     - Fallback на frontend-fuzzy (вариант A через `similarity.ts`),
       если catalog ответил ошибкой или timeout > 3 сек — показать
       «приблизительная группировка» с warning-бейджем.

  *Метрика успеха*:
  - На типичном запросе («каркассон», 6 магазинов, ~30 офферов) кол-во
    «строк верхнего уровня» падает с 30 до ~3-5.
  - `lookup` p95 < 500 мс для батча 30 (cache hit ratio ≥ 70% после
    разогрева).

  *Не входит*:
  - **Inline-merge нескольких разных игр** (юзер сам говорит «это всё
    Каркассон») — это уже manual matching, есть в `/catalog` (LinkPicker).
  - **Sparkline разброса цен** среди магазинов — nice-to-have, после
    landing'а базовой группировки.

  *Зависимости*: CAT-4 (matching v2) — должен быть стабилен в проде,
  иначе lookup даст много false positives. Сейчас CAT-4 в devlog
  (2026-05) — можно начинать.

- [WT-F8.1] **Persistent search history (опционально).** Изначальный WT-F8
  («drawer с журналом запросов на `/`») закрыт как «решено иначе» —
  таб `api-log` в SearchPage уже даёт API-логи текущей сессии (см. devlog
  2026-05-16). Этот узкий follow-up заводим **только если** возникнет
  потребность в **архивном** журнале (между сессиями, поиск по тексту,
  фильтр по магазину) — данные уже есть в `/api/db/searches`. До явной
  потребности — не делать.

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
- [PRS-6] **WB парсер — устойчивость к 429** — текущая реализация
  `search_async` в `services/parsers/parsers/stores/wildberries.py:151-165`
  делает всего **1 retry через фиксированные 2 сек** и падает с
  `RuntimeError("HTTP 429 (rate-limited даже после retry)")`. В проде
  WB стабильно режет DC-IP — пользователь часто видит эту ошибку.

  *Симптом*: `Wildberries: HTTP 429 (rate-limited даже после retry)` в
  UI поиска / Live Test.

  *Гипотезы причин*:
  - 2 сек backoff слишком короткий — Angie дросселирует на 10-30 сек.
  - curl-cffi с `chrome124` устарел (Chrome ушёл вперёд → JA3 не матчит
    реальный браузер); попробовать `chrome131` / `chrome133`.
  - DC-IP домашнего датацентра в чёрном списке WB — нужен residential
    прокси или fallback через browser-service.

  *План реализации (от дешёвого к дорогому)*:
  1. **Exponential backoff с jitter** вместо фиксированных 2 сек:
     `delay = base * 2**attempt + random(0, jitter)`, 3-4 попытки,
     base=1.5, max ~30 сек. Использовать существующий `_get_with_backoff`
     паттерн из других парсеров (если он там устаканен), либо новый
     helper в `parsers/utils/backoff.py`.
  2. **Обновить `impersonate`**: попробовать `chrome131`/`safari17` через
     `WB_BACKEND` env-флаг, замерить rate 429 на staging. Сейчас зашит
     `chrome124` (`wildberries.py:183`).
  3. **L2-fallback через browser-service** (по аналогии с Ozon
     `feat(parsers): [PRS-OZ]` и avito PRS-3) — при стабильном 429 на L0
     перебрасывать на camoufox с persistent profile, который копит cookies
     и проходит через JS-challenge Angie. Browser-service уже поднят как
     отдельный контейнер (`services/browser-service/`) — переиспользовать
     ту же ручку, что у Ozon.
  4. **Circuit breaker per-store**: если за последние N запросов rate
     ошибок > 50% — открывать breaker на 5 мин и сразу возвращать
     `ParserError("WB temporarily disabled")` вместо тыка в забор.
     Уменьшит шум в UI и логах. Структура breaker'а уже есть в catalog
     (`CAT-4` half-open) — переиспользовать паттерн.

  *Метрика успеха*: rate ошибок 429 в `parser_log` (table в parsers-БД)
  падает ниже 5% за неделю. Без замера — не катить в прод; добавить
  метрику до начала работ.

  *Зависимости*: WT-F10 пункт «Headless rate-limit tester» — удобно
  иметь UI-инструмент для калибровки backoff'а до выкатки.

- [PRS-5] **WB enrichment через `card.wb.ru/cards/v{N}/detail`** — search
  даёт только цену/название/бренд/рейтинг. Через `card.wb.ru` доступны
  characteristics (players, age, playtime, description). Сейчас не делаем
  потому что (1) `card.wb.ru` блокирует DC-IP жёстче `search.wb.ru` и
  (2) для MVP цены без характеристик хватает. Завести если возникнет
  потребность в WB-данных для matching v2 (T2 embeddings).

- [PRS-7] **Общий per-store Circuit Breaker.** WB-проблема (PRS-6 пункт 4)
  и Ozon timeouts показали, что breaker нужен не одному парсеру, а как
  cross-cutting pattern. Вынести в `services/parsers/parsers/utils/breaker.py`:
  `CircuitBreaker(store, failure_threshold=0.5, window=60s, open_for=300s,
  half_open_probes=1)`. Half-open паттерн — как у catalog'а
  (`docs/cat-4-matching-v2.md` §5). Использовать декоратором над `search()`
  в `wildberries.py`, `ozon.py`, `avito_qrator.py`. После реализации
  PRS-6 пункт 4 становится частным случаем — wildberries-circuit
  превращается в `@circuit_breaker(store='wildberries')`. Состояние
  держать **per-process** (не в БД) — breaker'у не нужна персистентность,
  цель — погасить шум на 5 минут, а не координировать инстансы.

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
