# Ревью services/catalog — 2026-07-10

Отчёт review-агента. Ядро (ingest, matching v2, scheduler, matching/games
роутеры) прочитано напрямую, импортёры/скрипты, второстепенные роутеры и
тесты/миграции проверены параллельными агентами, ключевые находки
перепроверены grep'ами.

## 1. Баги и криво реализованное

### Critical

**C1. Системное расхождение ключа T0-кэша: «сырой» vs «очищенный» title_norm.**
Точка чтения кэша — `engine.py:83-87`: ключ = `normalize_title(pipeline.process(title_raw))`
(после среза префиксов издателя, «настольная игра», артикулов и т.д.).
Но **все записи** делаются по `normalize_title(title_raw)` без pipeline:
- `routers/ingest.py:267` (save_decision после T1), `routers/ingest.py:321`
  (enqueue → worker унаследует),
- `matching/v2/worker.py:269-276` и `:326-333` (positive/negative кэш от
  T2/T3 по `q.title_norm`),
- `routers/matching.py:240` (manual link), `:297` (reassess), `:331`
  (enqueue), `:631` (manual reject → negative cache).

Последствия для любого title, который pipeline изменяет (а это как раз
маркетплейсы — основной поток T2/T3): positive/negative кэш **никогда не
хиттится** → LLM/embedding вызываются заново на каждый ingest того же
товара; negative-кэш «не настолка» не работает; сматченный воркером оффер
при следующем ingest'е сбрасывается в `unmatched` (`ingest.py:314`) и снова
едет в очередь — вечный флаппинг auto→unmatched→auto; бессрочная защита
manual-решений (`decisions.py:49-104`) не срабатывает.
Фикс: engine должен возвращать вычисленный `title_norm` в `MatchResult`,
а все `save_decision`/`enqueue` — использовать его.

**C2. `scripts/reset_mismatched.py:149-159` — INSERT в несуществующую колонку
`match_log.created_at`** (в таблице — `performed_at`, миграция 0011).
Документированный в CLAUDE.md cleanup-инструмент падает с
UndefinedColumnError при `--apply`.

**C3. `GET /admin/runtime-flags/bgg` недостижим** — `routers/runtime_flags.py:36`
(`/{key}`) зарегистрирован раньше `:93` (`/bgg`); запрос уходит в
`get_flag(key="bgg")` → 404. Потребитель есть
(`web-test/app/catalog_client.py:354`) — фича Global Settings на /bgg-sync
сломана всегда.

### Major

**M1. Зависшие `ImportJob(running)` навсегда блокируют scheduler.** Составная проблема:
- guard от параллельного запуска — `scheduler.py:436-449`
  (`status IN (pending, running)` → `JobAlreadyRunning`);
- recovery на старте есть только для `match_queue` (`api.py:53-71`),
  для `import_jobs` — нет;
- фоновые job'ы запускаются голым `asyncio.create_task` без `track_task`
  (`scheduler.py:470`, `routers/imports.py:294,482,516,555,588,619,657,710,892`,
  `routers/matching.py:944`, `routers/sources.py:99`) — при SIGTERM
  обрываются посреди транзакции;
- except-ветки финализируют статус **без `session.rollback()`**
  (`routers/imports.py:415-428, 850-859`, `importers/dicefest.py:661-669`,
  `sources/runner.py:334-347`) — при DB-ошибке сессия «отравлена», статус
  `failed` не записывается.
Итог: рестарт контейнера во время 25-минутного `bgg_top_sync` → job вечно
`running` → еженедельный sync больше никогда не запускается до ручного
UPDATE в БД.

**M2. `predicted_kind`/`kind_filter` (CAT-17.1) — мёртвая фича.**
`engine.py:126` вычисляет `classify_kind(title_raw)`, но ingest его не
сохраняет (в `enqueue` и таблице `match_queue` поля нет), а worker строит
`MatchContext` без него (`worker.py:95-100`) →
`tier_2_vector(kind_filter=ctx.predicted_kind)` (`embeddings.py:137`)
всегда получает None. Комментарий в engine («воркер передаст…») не
соответствует коду.

**M3. Оффер застревает в `pending_ml` навсегда.** `reassess`/`reassess-all`
ставят `match_status='pending_ml'` (`routers/matching.py:323`), но skip-путь
воркера `_update_offer_unmatched` (`worker.py:359-378`) не возвращает статус
в `unmatched` — обновляет только tier/reason/score. Оффер исчезает из
`/matching/queue` (фильтр по `unmatched`, `matching.py:168`) навсегда.

**M4. `match_log` растёт неограниченно.** Ingest пишет 2 progress-записи на
**каждый** unmatched-оффер при **каждом** ingest'е (`ingest.py:208-232`),
worker — ещё T2/T3 progress (`worker.py:147-154, 177-186`). Retention
`evict_older_than` (`auditor.py:301-307`) удаляет только
`reverted_at IS NOT NULL OR action='revert'` — progress-записи не подпадают
никогда. Ежедневные прогоны парсеров по тысячам офферов → миллионы вечных строк.

**M5. `POST /games/merge` не инвалидирует T0-кэш и теряет вектора.**
`games.py:441-526` не вызывает `invalidate_for_game` (docstring
`decisions.py:107-111` обещает обратное) — T0 продолжает авто-матчить офферы
на merged-игру (`tier_0_cache` не проверяет `games.status`). Плюс
`game_embeddings` перенесённых алиасов остаются с `game_id=source` и
выпадают из vec_search (фильтр `status != 'merged'`, `embeddings.py:59`) —
target теряет их вектора до ручного warmup.

**M6. Race в воркере: check-then-write без блокировки.** `worker.py:246-257`
читает оффер (`session.get`) и проверяет `manual/rejected`, но без
`FOR UPDATE`; если оператор сделал manual link между чтением и commit'ом
воркера (окно велико — batch 32 × LLM-latency) — воркер перетрёт manual-связь.

**M7. HTTP-эндпоинт CSV-импорта разошёлся с CLI и откатывает XML-обогащение.**
`routers/imports.py:805-823` перезаписывает
`bayes_average/average/users_rated/raw/source/fetched_at`, тогда как CLI
`scripts/import_bgg_ranks.py:167-174` после CAT-5 бережёт XML-territory.
Загрузка CSV через UI понижает `source='xml-api'`→`'csv-ranks'` и ломает
`skip_recent_days`-resume.

**M8. Cascade-шторм к BGG.** `enrich_one(cascade=True)` по умолчанию
(`parsers/bgg/service.py:118-124, 187-192`), auto-import циклы
`bgg_hotness.py:135`, `bgg_geeklist.py:150-173`, `bgg_yearly.py:152` его не
отключают → десятки параллельных fire-and-forget петель ломают rate-limit
1 req/sec, риск бана BGG.

**M9. `enrich_batch` — per-item except без rollback**
(`parsers/bgg/service.py:411-430`): первая IntegrityError «отравляет»
сессию, остальной батч падает с PendingRollbackError, `stats.errors` врёт
о причине.

**M10. Утечки httpx-клиентов:** `routers/imports.py:443` + `:358` —
DI-клиент никогда не входит в `__aenter__`/`__aexit__`, ленивый
`httpx.AsyncClient` внутри `BggClient._ensure_client()` (`client.py:102-109`)
не закрывается; `importers/bgg_yearly.py:144` —
`own_enrich_client = client is None` всегда False (мёртвое условие),
enrich-loop работает на закрытом клиенте, который молча пересоздаётся и течёт.

**M11. `game_embeddings`: `UNIQUE(game_id, alias_id)` с nullable `alias_id`**
(`alembic/versions/20260510_0011_matching_v2.py:227`) — NULLS DISTINCT в PG,
дубли title-эмбеддингов не запрещены; `warmup_embeddings.py:152` полагается
на этот constraint зря. Нужен partial unique `WHERE alias_id IS NULL`.

**M12. `apply_run` не идемпотентен вопреки докстрингу**
(`sources/runner.py:371-380, 409-417`): частичный apply
(`change_types=['new']`) переводит run в `applied` → применить `updated`
уже нельзя (409).

**M13. `fetch_with_retry` ретраит 4xx** (`importers/dicefest.py:415-434`):
`except httpx.HTTPError` ловит и `HTTPStatusError` — мёртвый slug (404)
впустую крутится 5 попыток с ~30с backoff.

### Minor (заслуживают упоминания)

- `bg_shared/ingest.py`: `fetched_at: datetime | None` без требования
  tz-aware — naive datetime уедет в timestamptz «как есть»; и **нет
  `max_length` на `products`** — весь батч обрабатывается в одной
  транзакции с матчингом на каждый item (`ingest.py:104-371`).
- `queue_repo.py:55-67`: `enqueue` ON CONFLICT сбрасывает даже
  `processing`-запись в `pending` — worker после finalize перезапишет в
  done, «ре-матч с новым title» теряется.
- `queue_repo.py:294-313`: `depth_history` — `LEFT JOIN match_queue ON true`
  = O(buckets × все строки таблицы) на каждый рендер sparkline.
- `matching.py:77-122,150`: `/matching/stats` и `/matching/candidates`
  отдают захардкоженные пороги 0.6/0.3 (v1), реальный авто-порог v2 — 0.92
  из Settings; UI показывает неверные bucket'ы.
- `matching.py:1270-1283`: `search_offers` не экранирует `%`/`_` в ILIKE
  (в `games.py:71` экранирование есть — непоследовательно).
- `health.py:100-106`: half-open probe возвращает True всем параллельным
  вызовам — thundering herd проб в одном батче.
- `importers/dicefest.py:469`: годы листингов захардкожены
  `(2024, 2025, 2026)` — с 2027-го парсер молча слепнет (сейчас июль 2026 —
  скоро).
- `bgg_hotness.py:79`, `bgg_geeklist.py:83`: `date.today()` — локальная
  дата вместо UTC.
- `matching_report.py:96`: `first_seen = MIN(last_seen_at)` — фикция
  (нет `created_at` у offers).
- `promotion/dicefest.py:40,133`: `threshold=0` не «показывает всех» —
  `%`-оператор всё равно режет по серверному `similarity_threshold=0.3`.
- `schemas.py:754`: `batch_auto_link.max_items` без верхней границы —
  опечатка `100000` займёт воркер на часы.
- `models.py:746-775`: `SchedulerConfig.updated_at` без `onupdate` —
  застывает после INSERT.

## 2. Мёртвый/лишний код (дублирование из roadmap — подтверждено и шире)

- **`_utcnow` — не 4, а 9 копий** (+ близнец `models._now`):
  `scheduler.py:39`, `routers/ingest.py:59`, `routers/imports.py:18`,
  `parsers/bgg/repository.py:52`, `importers/_log_buffer.py:31`,
  `bgg_hotness.py:34` (мёртвая, не вызывается), `bgg_family.py:38`
  (мёртвая), `bgg_geeklist.py:40`, `scripts/import_wikidata.py:43`.
- **enrich-loop — не 3, а 5 копий**: `bgg_hotness.py:128-150`,
  `bgg_geeklist.py:150-173`, `bgg_yearly.py:139-169`,
  `bgg_family.py:123-132`, `service.py:236-250`.
- **own_client — не 6, а ~10**: `tesera.py:128`, `bgg_family.py:81`,
  `bgg_geeklist.py:70`, `bgg_hotness.py:61`, `bgg_yearly.py:75,144`,
  `service.py:50,135,356`, `embedder.py:49`, `routers/imports.py:358`.
- **`MatchEngine.match_async`** (`engine.py:142-208`) — ноль вызовов;
  worker дублирует T2→T3-оркестрацию самостоятельно (`worker.py:102-240`).
  Два расходящихся экземпляра одной логики.
- **`matcher.py:41-80` `find_best_match` + `:138-142` `classify`** — не
  используются; импорты в `routers/matching.py:26-31` мёртвые (жив только
  `find_match_candidates`).
- **`embedder.py:132-169` `build_text`** — не вызывается; warmup собирает
  текст SQL'ем (`warmup_embeddings.py:77`) с другой семантикой (нет
  дедупа/алиасов) — мусор + дрейф.
- **`parsers/bgg/service.py:458-501` `iter_enrich`** — ноль вызовов.
- **`importers/dicefest.py:363-401, 61-80`** `_parse_release_date`/`MONTH_RU`
  — мёртвые с миграции 0005, живы только за счёт тестов, которые тестируют
  мёртвый код.
- `domain.py:44` `MATCH_STATUS_PENDING` — прод-код использует литерал
  `'pending_ml'`; константу проверяет только тест самой константы.
- `engine.py:50-56`: параметр `store_slug` в `match_sync` принимается и не
  используется.
- `schemas.py:876-885` `ScrapeRunTotals`, `schemas.py:628` `year_diff`
  (всегда None) — мёртвые контракты.

## 3. Безопасность

- **Auth-покрытие полное**: все мутации под `admin`, чтения под `read`,
  `/health` без auth — корректно. Но `REQUIRE_AUTH=False` по умолчанию
  (`config.py:29`) означает, что в дефолтной конфигурации массовые операции
  (merge, re-enqueue-all, bulk-revert, DELETE prefixes) открыты — приемлемо
  для внутреннего сервиса, стоит зафиксировать включение в prod-чеклисте.
- **[major] Аудит `performed_by`/`updated_by` фиктивен**:
  `request.state.api_key_owner` читается в 4 местах
  (`matching.py:1711-1719`, `runtime_flags.py:75`, `auto_recovery.py:60,95`),
  но **нигде не присваивается** — `auth.require_scope` (`auth.py:55-93`)
  не кладёт owner в request.state. Однострочный фикс в `_dep`.
- SQL-инъекций нет: все f-string SQL интерполируют только константы,
  значения — через bindparams; `invalidate_bulk` корректно через Core API.
- Хранение ключей sha256 без соли — обоснованно для 256-битных токенов.

## 4. Производительность

- **[major] Нет индекса `offers.last_seen_at`** — все 4 отчёта
  `/matching/report/*` (`matching_report.py:82,170,296`) делают seq scan
  на каждый рендер страницы.
- `warmup_embeddings.py:110,141-159`: 522K строк одним `.all()` в память +
  INSERT per-row.
- `embed_one` в worker-пути создаёт новый `httpx.AsyncClient`
  (TCP+TLS handshake) на каждый queue item (`embedder.py:49-52`) — стоило
  бы шарить клиента на батч.
- `lookup_batch` (`matching.py:1479-1492`): до 200 × последовательный
  `match_sync` (T0+T1+лемматизация) — до ~10 c на запрос; `reassess_all` —
  500 офферов в одной транзакции.
- Ollama-вызовы: таймауты есть везде (30/60/120с) — хорошо; но у
  LLM-промпта нет усечения `title_raw` (маркетплейс-заголовки бывают
  >500 символов).
- Индексы под горячие запросы (claim_batch partial, T0 unique, trgm
  expression-индексы) — на месте, проверено против SQL. Не хватает мелочи:
  `match_log(action)`, `import_jobs(type, created_at DESC)`, partial
  `offers(match_score) WHERE match_status='unmatched'`.
- Синхронных вызовов в async-коде не найдено (везде httpx + asyncio.sleep).

## 5. Тесты

Покрыто хорошо: T0/T1 (hit/miss/negative/TTL), match_queue
(enqueue/claim/retry/recover_stuck), ingest e2e (whitelist, идемпотентность,
прогресс-записи), auth-скоупы, dicefest promotion (включая
revert-после-merge), BGG-парсер/enrich_batch на mock-транспорте, чистая
логика (pipeline/scoring/classifier/circuit breaker).

Критичные дыры:
- **`tier_2_vector` / `tier_3_llm` / весь `worker.py` — ноль тестов**
  (ни integration, ни с mock-Ollama). Финализация, negative-cache,
  `_finalize_reject` — не покрыты. **critical**
- `scheduler.py` (927 строк) — ноль тестов. **major**
- `POST /games/merge`, `reassess`/`reassess-all` — не покрыты. **major**
- Конкурентность не проверяется: claim_batch двумя сессиями, параллельный
  ingest одного оффера. **major**
- `requires_db` молча скипает 16/28 файлов — CI без Postgres зелёный,
  не выполнив ~80% значимых тестов. **major**

## 6. Идеи функциональности (логичные продолжения)

1. **Инкрементальный embedding**: новые игры/алиасы попадают в T2 только
   после ручного warmup — генерить вектор при create game/alias или
   nightly-job по диффу `game_embeddings`.
2. **`MatchResult.title_norm`**: вернуть вычисленный ключ из engine и
   переиспользовать во всех записях — закрывает C1 архитектурно, а не
   точечными правками.
3. **ImportJob startup-recovery** (симметрично `recover_stuck`):
   `running` старше N часов → `failed` при старте — закрывает M1.
4. **Эндпоинт истории цен**: `offer_prices` — write-only таблица, ни один
   эндпоинт её не читает. `GET /offers/{id}/prices` или
   `GET /games/{id}/price-history` — очевидный следующий шаг (данные уже
   копятся).
5. **Snapshot-таблица глубины очереди** — `depth_history` сам признаётся,
   что он аппроксимация; cron-запись 5 чисел в минуту заменит
   cartesian-реконструкцию.
6. **Активировать kind_filter**: колонка `predicted_kind` в `match_queue`
   (или пересчёт `classify_kind` в воркере) — фича написана, осталось
   донести значение до T2.
7. **Auto-discovery префиксов издателей**: `source='discovered'` уже заведён
   в модели (`models.py:824`) — анализ частых первых токенов
   unmatched-офферов.

## Главные выводы

1. **T0-кэш системно сломан рассинхроном ключа (C1)** — pipeline-очистка
   применяется при чтении, но не при записи; это обесценивает весь смысл
   кэша v2 и заставляет LLM пересматривать одни и те же маркетплейс-товары
   при каждом ingest'е. Самый дорогой по последствиям баг; чинится
   централизацией `title_norm` в `MatchResult`.
2. **Фоновые job'ы хрупкие к сбоям и рестартам (M1)**: нет recovery для
   `ImportJob`, `create_task` без трекинга, except без rollback — любой
   рестарт может навсегда заблокировать scheduled-джоб. Инфраструктура
   (`track_task`, паттерн recover_stuck) уже написана — её просто не
   применяют.
3. **ML-путь (T2/T3/worker) не покрыт ни одним тестом**, при этом именно
   там живут race M6, застревание M3 и мёртвая фича M2 — все три остались
   бы незамеченными тестами и дальше.
4. **Данные утекают по мелочам**: match_log растёт вечно (M4), merge не
   чистит кэш/вектора (M5), CSV-импорт через UI откатывает XML-обогащение (M7).
5. **Дублирование хуже, чем в roadmap**: `_utcnow` ×9, enrich-loop ×5,
   own_client ×10, плюс две копии T2→T3-оркестрации (engine.match_async vs
   worker) и разошедшийся CSV-upsert — рефакторинг-проход (общий `utcnow`,
   `enrich_missing()` helper, `BggClient.ensure()`) назрел.
