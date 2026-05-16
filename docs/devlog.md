# Devlog — boardgames-platform

Журнал завершённых задач. Каждая запись: дата, ID, что сделано, как пользоваться.

> **Для агентов:** после завершения задачи **перенеси** её из `roadmap.md` сюда —
> добавь запись **в начало** файла (новые сверху) и удали строки из roadmap.
> Формат — см. примеры ниже. Не редактируй старые записи.

---

## 2026-05-16 · [CAT-4] Matching v2 — ML-powered tiered pipeline + hardening

**Что сделано:** многоуровневый матчер catalog → game с auto-resolution через
ML-стек, plus полная обвязка для боя (recovery, kill-switch, audit, revert).
Реализован 2026-05-10..11, hardened после code review 2026-05-15..16.

Pipeline:
- **T0** — cache (`match_decisions`, TTL per source: manual=∞, t1=30д, t2=14д, t3=7д).
- **T1** — `pg_trgm` ≥ 0.92 на title/title_ru/aliases, sync в ingest.
- **T2** — bge-m3 cosine через pgvector top-K, async через `match_worker` (10с).
- **T3** — qwen2.5:7b-instruct LLM-арбитр (format='json', confidence ≥ 0.75)
  при `vec_ambiguous` (≥2 кандидата ≥ 0.70). Single confident below auto_threshold
  (`vec_below_threshold`) идёт в T4 без LLM-вызова — экономит ресурс.
- **T4** — manual queue (UI).

Production-обвязка:
- `OllamaHealth` Circuit Breaker per-model с **half-open**: после `_recovery_timeout`
  (60с) первый запрос — probe; `embedder.record_success`/`llm_arbiter.record_success`
  закрывают цепь немедленно. APScheduler-job `ml_health_check` (30с) поллит `/api/tags`.
- `match_queue` outbox с `FOR UPDATE SKIP LOCKED`, exponential backoff 30→120→600→1800с,
  `claimed_at` денормализация для корректного `recover_stuck` (был баг — использовался
  `created_at`, при горячем рестарте запись могла обработаться повторно).
- `runtime_flags.ml_enabled` kill-switch с in-memory TTL-кэшем 5с — выключение ML
  без рестарта через `PATCH /admin/runtime-flags/ml_enabled`. Settings.ml_enabled
  оставлен как fallback.
- `match_log` audit с bulk-revert через `batch_id` UUID. `revert_one` снимает
  `title_norm` snapshot до UPDATE — корректно очищает T0 даже если оффер удалён.
- BGG enrichment всех 162K игр (169 744 эмбеддинга, HNSW vector(1024), m=16,
  ef_construction=128) и `title_ru` first-class колонка.
- LLM JSON-парсер через `JSONDecoder.raw_decode` — обрабатывает вложенные объекты
  (старый regex `\{.*?\}` ломался на nested JSON).

UI (web-test):
- `MlStatusBadge` в HealthBadge показывает circuit_state per-model.
- Новая вкладка «Журнал матчинга» с bulk-revert чекбоксами, `TierBadge`.
- `GET /matching/stats` теперь возвращает `queue.{pending,processing,skipped,
  failed,done}` — оператор видит сколько ушло в T4.

**Как пользоваться:**
- ML kill-switch: `curl -X PATCH http://localhost:8002/admin/runtime-flags/ml_enabled
  -H 'content-type: application/json' -d '{"value":false}'` — выключает T2/T3 (worker
  пропускает циклы, ingest пишет `unmatched` с reason='ml_disabled').
- Прогресс воркера: `curl http://localhost:8002/matching/stats | jq .queue` —
  pending/processing видно сразу, skipped = офферы в manual T4.
- ML-статус: `curl http://localhost:8002/matching/ml-status` — `models` + `circuit_state`
  (closed/open/half_open) per-model.
- Revert: `curl -X POST http://localhost:8002/matching/log/batch/<uuid>/revert` —
  откат всех изменений одного batch'а (например, неудачного reassess-all).

**Затронутые файлы:**
- Миграции: `0011_matching_v2.py` (pgvector + game_embeddings + match_decisions/log/queue),
  `0013_matching_v2_hardening.py` (claimed_at + runtime_flags).
- Ядро: `services/catalog/catalog/matching/v2/{engine,tiers,embeddings,llm_arbiter,
  health,worker,queue_repo,decisions,auditor,embedder,domain}.py`.
- Runtime flags: `catalog/runtime_flags.py`, `catalog/routers/runtime_flags.py`.
- Scheduler: `catalog/scheduler.py` (`_register_interval_job`, `reload_job_from_db`
  для interval-jobs).
- Интеграция: `catalog/routers/{ingest,matching}.py`.
- Тесты: `tests/test_matching_v2_{unit,integration}.py` (80 тестов).
- UI: `services/web-test/frontend/src/components/{shared/HealthBadge.tsx,
  catalog/MatchLog.tsx,catalog/TierBadge.tsx}`.

**Известные ограничения** (вынесено в roadmap follow-up'ом):
- Pre-existing `test_ingest_typo_*` падают на T1@0.92 vs старый 0.6 — переписать
  под новые пороги.
- MatchProfile per-store override — схема в БД готова (`match_profiles`), реализация
  `MatchProfileLoader` не подключена.
- Structured embedding text вместо конкатенации title+title_ru+aliases — после
  анализа miss-rate.

## 2026-05-16 · [PRS-OZ] Ozon-парсер через browser-service (Camoufox persistent profile)

**Что сделано:** Шестой источник цен — Ozon. Парсит SSR HTML страницы `/search/?text=<q>`,
поднятой через `services/browser` (Camoufox + Firefox). Прямой HTTP закрыт **Antibot
Challenge Page** (FunCaptcha-like JS challenge на TLS+behavioural+cookies): probe
показал, что даже с cookies от Camoufox, прямой запрос на `composer-api.bx` отдаёт 403.
Поэтому **все запросы идут через browser-service** с `profile_id="ozon"` (persistent
profile в `/data/profiles/ozon` — cookies/localStorage накапливаются между запросами,
warm-trip быстрее cold-trip). В `lifespan` запущен **warmup loop** (asyncio.Task,
интервал `OZON_WARMUP_INTERVAL_MINUTES`, default 60м) — делает «холостой» fetch на
главную, чтобы первый user-запрос был тёплым. Парсинг карточек — regex по якорю
`<a href="/product/<slug>-<id>/">` с fallback на восстановление title из slug.

**Как пользоваться:**
- Запустить browser-service: `docker compose --profile browser up -d browser` (или весь
  стек: `--profile full --profile browser`). Без него `OzonParser.search()` падает с
  `RuntimeError`, остальные парсеры работают.
- Поиск: `curl "http://127.0.0.1:8001/search?q=Каркассон&stores=ozon&limit=5"`.
- Live Test: `curl "http://127.0.0.1:8001/api/debug/parse?q=Каркассон&stores=ozon&limit=5"` —
  мимо кеша, видны цены/brand/original_price/image_url.
- Dashboard `/dashboard` → таб «Парсеры» — latency Ozon в среднем 3-12с vs WB ~500мс,
  это нормально (плата за обход antibot).
- Цены: `price` = с Ozon-картой (Headline-цена в карточке), `raw.original_price` =
  без скидки. В catalog `price` пишется как основная.

**Затронутые файлы:**
- `services/parsers/parsers/stores/ozon.py` (новый) — `OzonParser`, `_parse_cards`,
  `_parse_price_kopecks`, `_title_from_slug`, `warmup_once`, `warmup_interval_seconds`.
- `services/parsers/parsers/stores/__init__.py` — экспорт `OzonParser`.
- `services/parsers/parsers/api.py` — регистрация в `lifespan()`, `_ozon_warmup_loop()`.
- `services/parsers/tests/test_ozon_parser.py` (новый) — 24 теста: helpers, парсинг
  карточек, search() protocol, error pathways (challenge HTML, empty html, no browser).
- `services/parsers/CLAUDE.md`, `services/parsers/README.md` — обновили таблицу и
  подводные камни.
- `.env.example` — добавлен `OZON_WARMUP_INTERVAL_MINUTES`.

## 2026-05-14 · [PRS-WB] Wildberries-парсер (search-only через публичный JSON)

**Что сделано:**
Новый `WildberriesParser` (`services/parsers/parsers/stores/wildberries.py`) —
шестой источник цен в сервисе. Использует публичный JSON endpoint
`search.wb.ru/exactmatch/ru/common/v5/search` (тот же, что дёргает фронт WB),
один HTTP-запрос → до 100 товаров. Без обогащения со страницы товара
(минимум HTTP). **Pluggable backend**: `httpx` или `curl-cffi` (TLS-imp
Chrome 124) — переключение через env `WB_BACKEND` или query-параметр
`/api/debug/parse?wb_backend=curl-cffi`. Default — `curl-cffi`, потому
что Angie у WB агрессивнее rate-limit'ит vanilla httpx из DC-IP.
**Soft twin-search**: один запрос → локальная фильтрация по
`subjectId=120` («Настольные игры»), при недоборе до limit — добор общей
выдачей. Retry-once при HTTP 429 (через 2 сек). 14 unit-тестов, full suite
96/96 ✓. Probe-скрипты `bin/probe_wb*.py` сохранены для диагностики.

**Почему legacy v5, а не v13:** WB v13 теперь — preset-router (возвращает
shardKey, а не товары), реальные products живут в `catalog.wb.ru` — а тот
шлёт **403 Forbidden** на любой DC-IP. v5 — legacy без preset-routing,
возвращает 100 products одним запросом.

**Как пользоваться:**
- Поиск по умолчанию: `curl --get "http://127.0.0.1:8001/api/debug/parse"
  --data-urlencode "q=Каркассон" --data-urlencode "stores=wildberries"
  --data-urlencode "limit=5"` → 5 настолок subjectId=120.
- Сравнить backends на лету: `?wb_backend=httpx` vs `?wb_backend=curl-cffi`
  в том же URL.
- Cold-start ~1–2.5 сек, hot ~500–800 мс (зависит от текущего rate-limit'а
  WB к контейнеру). При устойчивом 429 после retry — error попадает в
  `parser_log` и `/dashboard`, остальные парсеры продолжают работать
  (graceful degradation в `PriceService`).

**Затронутые файлы:**
- `services/parsers/parsers/stores/wildberries.py` — новый парсер.
- `services/parsers/parsers/api.py` — регистрация в lifespan, добавлен
  query-параметр `wb_backend` в `/api/debug/parse`.
- `services/parsers/tests/test_wildberries_parser.py` — 14 новых unit-тестов.
- `.env.example` — секция `WB_BACKEND` / `WB_API_VERSION`.
- `services/parsers/README.md` + `services/parsers/CLAUDE.md` — Wildberries
  в таблице магазинов и в архитектуре.
- `bin/probe_wb.py` / `probe_wb2.py` / `probe_wb3.py` / `probe_wb4.py` —
  диагностические скрипты для ретроспективы.

---

## 2026-05-14 · [AVT-CONT] Avito-парсер: container-only через L0 (curl-cffi + /web/1/js/items)

**Что сделано:**
AvitoParser перенесён с цепочки «нативный Mac Chrome + chrome-extension +
browser-service» на L0-стратегию — `curl-cffi` с TLS-импесронацией Chrome 124
и обращение напрямую к публичному JSON-endpoint avito `/web/1/js/items`,
который раньше дёргал фронт после CSR-загрузки страницы. Новый модуль
`services/parsers/parsers/stores/avito_qrator.py` инкапсулирует cookie-jar,
ротацию `_avisc` (Max-Age=60, refresh ≥50s), retry-with-fresh-session при
429/403. `AvitoParser` теперь только маппит JSON в `ParsedProduct`.
Зависимость от хостового браузера убрана: `docker compose --profile full up -d`
поднимает рабочий парсер без других действий. Chrome-расширение перенесено в
`services/parsers/DEPRECATED/chrome-extension/`, `POST /api/avito/cookies`
возвращает 410 Gone. В browser-service удалён режим `CHROME_CDP_URL`,
из docker-compose убран сервис `chrome-vnc`. PoC-скрипты сохранены в
`bin/probe_avito_l0*.py`.

**Как пользоваться:**
- Из коробки: `docker compose --profile full up -d` → `curl --get
  "http://127.0.0.1:8001/api/debug/parse" --data-urlencode "q=Каркассон"
  --data-urlencode "stores=avito" --data-urlencode "limit=5"`.
- Ожидаемая латентность: cold (после простоя >60s) ~2.0–2.5 сек, hot — ~500–700 мс.
  Метрика видна в `parser_log.search_ms` и в `/dashboard` → Парсеры.
- Если когда-нибудь сломается endpoint — повторить `bin/probe_avito_l0_xhr.py`:
  он покажет, отдаёт ли avito JSON и какой именно.

**Затронутые файлы:**
- `services/parsers/parsers/stores/avito_qrator.py` — новый, L0-клиент с TLS-imp.
- `services/parsers/parsers/stores/avito.py` — переписан, только маппинг JSON.
- `services/parsers/parsers/api.py` — `AvitoQratorClient` в lifespan, `AvitoParser`
  регистрируется всегда, `/api/avito/cookies` → 410.
- `services/parsers/tests/test_avito_parser.py` — новый, 8 unit-тестов.
- `services/parsers/DEPRECATED/chrome-extension/` — перенесено + README с откатом.
- `services/browser/browser/api.py` — удалён CHROME_CDP_URL ветка lifespan.
- `docker-compose.yml` — убраны env `AVITO_COOKIES`, `CHROME_CDP_URL`, сервис `chrome-vnc`.
- `.env.example` — упрощён browser-блок, удалён avito-cookies-блок.
- `bin/probe_avito_l0.py`, `bin/probe_avito_l0_xhr.py` — PoC-скрипты для диагностики.

---

## 2026-05-12 · [CAT-6] BGG `<poll>` рекомендации — суг. число игроков, возраст, language dependence

**Что сделано:**
Парсер `parse_thing_xml` достаёт три poll'а из `/thing` ответа BGG. Логика
вынесена в helper'ы `_poll_winner`/`_age_transform`/`_lang_level_transform` +
три специализированных парсера, чтобы каждый кейс тестировался изолированно.
В `game_bgg` добавлены колонки `recommended_players JSONB` (raw подсчёты per
player count включая bucket «6+»), `recommended_age INTEGER` (winning value;
tie → min; «21 and up» → 21), `language_dependence INTEGER` (winning level 1–5).
`totalvotes=0` → NULL (poll без голосов неинформативен). `GameBggOut` отдаёт
все три поля наружу.

**Как пользоваться:**
- Прогнать XML-обогащение: `POST /import/bgg/batch -d '{"rank_le": 100, "skip_recent_days": 0}'`.
- Проверить: `curl localhost:8002/games/<id> | jq '.bgg | {recommended_players, recommended_age, language_dependence}'`.
- Структура `recommended_players`: `{"2": {"best": 100, "recommended": 200, "not_recommended": 50}, "6+": {...}}` — фронт сам решает, как презентовать («лучше всего с N игроками», бар-чарт и т.п.).
- Юниттесты helper'ов: `cd services/catalog && uv run pytest tests/test_bgg_parser.py -v -k poll`.

**Затронутые файлы:**
- `services/catalog/catalog/parsers/bgg/parser.py` — 4 helper-функции + расширение `parse_thing_xml`.
- `services/catalog/catalog/parsers/bgg/models.py` — `BggGame` поля `recommended_players`/`recommended_age`/`language_dependence`.
- `services/catalog/catalog/models.py` — ORM-колонки в `GameBgg`.
- `services/catalog/catalog/schemas.py` — `GameBggOut` 3 поля.
- `services/catalog/tests/test_bgg_parser.py` — 11 новых юнит-тестов (включая tie-resolution, "21 and up", totalvotes=0).
- `services/catalog/tests/fixtures/bgg_carcassonne.xml` — расширена тремя poll'ами.

---

## 2026-05-12 · [CAT-5] BGG XML stats fields в game_bgg — XML как источник истины

**Что сделано:**
`upsert_bgg_data` теперь записывает `users_rated`, `average_weight` (complexity
1.00–5.00), `num_weights` из `<statistics><ratings>` BGG XML. Поля
`bayes_average`/`average`/`users_rated` начинают перезаписываться XML'ом —
ранее они приходили только из ежемесячной CSV-выгрузки `boardgames_ranks.csv`,
которая отстаёт от XML на неделю. CSV-импорт (`import_bgg_ranks.py`) перестал
обновлять эти поля при ON CONFLICT: source/raw/fetched_at/bayes_average/
average/users_rated исключены из `set_` блока для `game_bgg`, а `source` —
ещё и из `set_` для `games` (заодно пофиксили pre-existing — CSV откатывал
`games.source='bgg'` обратно в `'bgg-ranks'`). CSV теперь обновляет только
rank/is_expansion/subtype_ranks.

Новая колонка `bgg_stats_updated_at TIMESTAMPTZ` помечает момент последнего
XML-обогащения отдельно от `fetched_at` (который трогается любым upsert'ом).

**Как пользоваться:**
- После накатывания миграции 0012 запустить XML-обогащение свежей выборки:
  `POST /import/bgg/batch -d '{"rank_le": 1000, "skip_recent_days": 0}'`.
- Проверить колонку complexity на фронте: `curl localhost:8002/games/<id> | jq '.bgg.average_weight'`.
- Список игр с свежей статистикой:
  `psql -c "SELECT bgg_id, bayes_average, average_weight FROM game_bgg WHERE bgg_stats_updated_at > now() - interval '1 day' ORDER BY rank LIMIT 20"`.
- При следующем ежемесячном CSV-импорте (`python -m catalog.scripts.import_bgg_ranks ranks.csv`) `source='xml-api'` и raw XML-blob сохранятся.

**Затронутые файлы:**
- `services/catalog/catalog/parsers/bgg/repository.py` — `upsert_bgg_data` пишет 3 новых поля + перезаписывает bayes/avg/users_rated.
- `services/catalog/catalog/parsers/bgg/parser.py` — извлечение `users_rated`/`average_weight`/`num_weights`.
- `services/catalog/catalog/parsers/bgg/models.py` — `BggGame` поля.
- `services/catalog/catalog/models.py` — ORM-колонки + `bgg_stats_updated_at`.
- `services/catalog/catalog/schemas.py` — `GameBggOut` поля.
- `services/catalog/alembic/versions/20260512_1056_bgg_stats_extension.py` — миграция 0012.
- `services/catalog/catalog/scripts/import_bgg_ranks.py` — узкий ON CONFLICT set_ (только rank/is_expansion/subtype_ranks для game_bgg; убран source из games).

---

## 2026-05-12 · [CAT-7] raw JSONB blob в game_bgg — re-parse без повторного запроса BGG

**Что сделано:**
`upsert_bgg_data` теперь заполняет `game_bgg.raw` структурой
`{"parsed": <asdict(BggGame)>, "xml": <raw item XML>}`. До этого там стоял
`raw={}` с TODO, и в `set_` блок поле вообще не входило — то есть даже при
повторных XML-обогащениях raw оставался пустым. Теперь `raw` корректно
перезаписывается на каждом XML-upsert. Сигнатура расширена:
`upsert_bgg_data(session, bgg, xml_text="")`. `_parse_things_xml` (batch path)
возвращает `list[tuple[BggGame, str]]`, чтобы прокинуть sub_xml каждой игры
в upsert. `enrich_one` пробрасывает уже имеющийся xml_text напрямую.

Польза: при изменении парсера (новые поля XML) можно re-парсить из БД без
повторных rate-limited запросов к BGG. Размер: ~30-50KB JSONB на игру, ~1.5GB
на полные 30K ranked-игр.

**Как пользоваться:**
- После XML-обогащения проверить raw для конкретной игры:
  `psql -c "SELECT jsonb_object_keys(raw), length(raw->>'xml') FROM game_bgg WHERE bgg_id=822"`.
- Re-parse без BGG-запроса: загрузить `raw->>'xml'` строкой и вызвать
  `parse_thing_xml(xml_text)` — получите `BggGame` с обновлённой логикой парсера.
- Аудит конкретного поля без повторного запроса:
  `psql -c "SELECT raw->'parsed'->>'recommended_age' FROM game_bgg WHERE bgg_id=822"`.

**Затронутые файлы:**
- `services/catalog/catalog/parsers/bgg/repository.py` — `upsert_bgg_data` сигнатура + заполнение raw + raw в `set_` блоке.
- `services/catalog/catalog/parsers/bgg/service.py` — `_parse_things_xml` возвращает tuple, `enrich_one`/`enrich_batch` прокидывают xml_text.
- `services/catalog/tests/test_bgg_repository.py` — новый файл, 4 integration-теста (запись новых полей, idempotency, XML overwrites CSV, CSV не откатывает XML-territory).
- `services/catalog/tests/test_bgg_enrich.py` — обновлены 3 теста под новую сигнатуру `_parse_things_xml`.

---

## 2026-05-10 · [CAT-3] BGG Sync UI + GeekList + daily mini-batch + cron editor

**Что сделано:**
Полнофункциональный web-интерфейс синхронизации с BGG. Новая страница `/bgg-sync`
в web-test с пятью вкладками: **Расписание** (health-блок 3 scheduler-job'ов,
inline cron editor, кнопка ручного запуска), **История** (унифицированная история
ImportJob'ов с фильтрами type/status/trigger — ручные и автоматические запуски в
одной таблице), **Hotness** (текущий снимок + история + diff «новые/выпали/
изменили позицию»), **GeekList** (импорт кураторских BGG-списков, например monthly
«Top 50 Most Played»), **Без BGG ID** (catalog-игры без bgg_id с deep-link на BGG search).

Новый scheduler-job `bgg_mini_batch` — ежедневный catch-up хвоста rank-таблицы
(500 игр, мягкий rate-limit 2с). На ~30K играх это даёт цикл обновления ~60 дней.
Cron-выражения и параметры job'ов теперь в БД (`scheduler_configs`) — UI редактирует
без рестарта сервиса через `scheduler.reschedule_job()`. Scheduler-job'ы создают
ImportJob с `payload.trigger='scheduled'` — ручные и автоматические запуски в
единой истории. Race-protection: повторный trigger того же type возвращает 409.

**Как пользоваться:**
- Открыть `http://localhost:5173/bgg-sync` (или `:8000/bgg-sync` в prod-режиме).
- **Расписание** → клик «Настроить» под job'ом → правка cron + params (JSON) → Сохранить.
- **Расписание** → клик «Запустить» — мгновенный manual trigger (создаёт ImportJob).
- **GeekList** → ввести ID (например, `367126` для October 2025 Top Most Played) →
  клик «Запустить» → snapshot сохраняется в `bgg_geeklists`, новые игры авто-импортятся.
- **Hotness** → выпадающие списки: левый = снимок дня, правый = «сравнить с» →
  показывает Set-difference добавленных/выпавших игр + поднявшихся/упавших в ранге.
- **История** → фильтры: type / status / trigger (manual или scheduled). Клик строки —
  раскрывает прогресс-бар, лог, result JSON.

**Затронутые файлы:**
- catalog: `alembic/versions/20260510_0010_*.py` (миграция scheduler_configs +
  bgg_geeklists), `models.py` (SchedulerConfig, BggGeeklist),
  `scheduler.py` (rewrite — JOB_METADATA registry, trigger_scheduled_job,
  JobAlreadyRunning, reload_job_from_db, _register_job),
  `routers/scheduler.py` (новый), `routers/bgg_lists.py` (новый — read API),
  `routers/imports.py` (GET /import/jobs, POST /bgg/geeklist, POST /bgg/mini-batch),
  `routers/games.py` (?no_bgg=true), `importers/bgg_geeklist.py` (новый),
  `importers/_log_buffer.py` (BufLogger, run_import_job_skeleton),
  `parsers/bgg/{client,parser,models}.py` (fetch_geeklist + parse_geeklist_xml +
  BggGeeklistMeta/Item, _get_with_backoff helper).
- web-test: `app/api/bgg_sync.py` (новый proxy), `app/catalog_client.py` (9 методов).
- frontend: `pages/BggSyncPage.tsx`, `lib/bgg-sync.ts`, 5 компонентов в
  `components/bgg-sync/` (SchedulerHealth, JobHistoryTable, HotnessPanel,
  GeeklistPanel, NoBggList).

**Замечание про BGG API возможности:**
«Most Played Games» и «Bestsellers» в BGG XML API НЕ существуют. Реализован путь
через GeekList importer — универсальный механизм, BGG публикует ежемесячный
кураторский список «Top 50 Most Played» (id обновляется ежемесячно админами BGG).
Для нативных «bestsellers» BGG нет источника — будем строить из локальных offers
позже как отдельную фичу.

---

## 2026-05-10 · [CAT-2] BGG периодическая синхронизация + Hotness

**Что сделано:**
Полная подсистема автоматической синхронизации с BGG. APScheduler встроен в
lifespan FastAPI: еженедельный `bgg_top_sync` (enrich_batch топ-1000 по рангу,
понедельник 03:00 UTC) и ежедневный `bgg_hotness_sync` (snapshot /hot → таблица
`bgg_hotness` + авто-импорт новых игр). При ingest offers: если `game_bgg.fetched_at`
старше `BGG_INGEST_ENRICH_STALENESS_DAYS` дней — fire-and-forget `enrich_one` в фоне.
Добавлена поддержка BGG Bearer-токена (обязателен с 2025-го). Миграция `0009_bgg_hotness`.

**Как пользоваться:**
- Scheduler стартует автоматически при запуске сервиса; job'ы видны в логах контейнера.
- Ручной запуск hotness sync: `POST http://localhost:8002/import/bgg/hotness`
  (прогресс через `GET /import/jobs/{id}`).
- Настройка расписания — через env-переменные `BGG_TOP_SYNC_CRON` / `BGG_HOTNESS_SYNC_CRON`.
- Отключить sync полностью: `BGG_TOP_SYNC_ENABLED=false` / `BGG_HOTNESS_SYNC_ENABLED=false`.
- Токен BGG: добавить `BGG_API_TOKEN=<token>` в `.env`
  (получить на boardgamegeek.com/account/preferences).

**Затронутые файлы:**
`catalog/scheduler.py` (новый),
`catalog/importers/bgg_hotness.py` (новый),
`alembic/versions/20260510_0009_bgg_hotness.py` (новый),
`catalog/models.py` (BggHotness),
`catalog/parsers/bgg/client.py` (fetch_hot, from_settings, Bearer auth),
`catalog/parsers/bgg/parser.py` (parse_hot_xml),
`catalog/parsers/bgg/models.py` (BggHotnessItem),
`catalog/routers/imports.py` (POST /import/bgg/hotness),
`catalog/routers/ingest.py` (staleness check),
`catalog/config.py` (BGG_* settings),
`catalog/api.py` (scheduler в lifespan + logging.basicConfig).

---

## 2026-05-10 · [WT-T2] DiffView compact raw filter

**Что сделано:**
В diff-просмотрщике снапшотов добавлен переключатель **compact / все raw**.
В compact-режиме `extra.*` поля схлопнуты — видны только «важные» ключи
(`availability`, `in_stock`, `on_sale`, `original_price`, `sku`, `article`, `bonus_percent`).
В full-режиме отображаются все поля. Кнопка в тулбаре рядом с фильтром изменений.

**Как пользоваться:**
Открыть `/testing` → выбрать два снапшота → кнопка **«compact raw»** / **«все raw»** в верхней панели.

**Затронутые файлы:**
`frontend/src/components/testing/DiffView.tsx`.

---

## 2026-05-10 · [WT-F5.3] Status page

**Что сделано:**
Новая страница `/status` для ретроспектив состояния сервисов. Backend фиксирует
каждый ping (parsers + catalog) в локальной SQLite-таблице `ping_history`
с ретенцией 7 дней. Frontend рисует два AreaChart (unmatched_offers и total_games
во времени) и ленту событий с цветными статус-точками.

**Как пользоваться:**
- Открыть `http://localhost:5173/status` (или `:8000/status` в прод-режиме).
- При открытии страницы сразу делается пинг; далее — каждые 30 сек автоматически.
- Переключатель периода: **1ч / 6ч / 24ч / 7д**.
- Кнопка ↻ (refresh) — ручной пинг вне расписания.
- Пункт **«Статус»** (иконка Activity) появился в левом сайдбаре.

**Затронутые файлы:**
`app/db_local.py` (миграция v5 + методы),
`app/api/status.py` (новый роутер),
`app/main.py`,
`frontend/src/lib/api.ts`,
`frontend/src/pages/StatusPage.tsx`,
`frontend/src/App.tsx`.

---

## 2026-05-10 · [WT-F2.6] Bulk-import wizard top-N

**Что сделано:**
UI вокруг `import_bgg_ranks.py` — wizard для seed'а каталога из BGG ranks CSV.
Новая секция «Seed каталога из BGG ranks CSV» появилась первой на вкладке **BGG**
страницы Каталог. Catalog backend принимает CSV через multipart, фильтрует
по top-N и пакетно upsert'ит в `games` + `game_bgg`. Прогресс трекается через
ImportJob (polling каждые 1.5 сек).

**Как пользоваться:**
1. Скачать `boardgames_ranks.csv` с `boardgamegeek.com/data_dumps/bg_ranks` (требует BGG-аккаунт).
2. Открыть `/catalog` → вкладка **BGG** → секция **«Seed каталога из BGG ranks CSV»**.
3. Перетащить файл в drop-zone или кликнуть для выбора.
4. Указать **Top-N** (например, `500`). Пустое поле = все ~160K игр.
5. Оставить **Dry-run** включённым для первого запуска — покажет сколько будет импортировано.
6. После seed'а — запустить **«Batch-обогащение»** ниже на той же вкладке.

**Затронутые файлы:**
`catalog/routers/imports.py` (endpoint + background job),
`app/catalog_client.py`, `app/api/catalog.py`,
`frontend/src/lib/catalog.ts`,
`frontend/src/components/catalog/BggImportPanel.tsx`.

---

## 2026-05-09 · [WT-F4.4-extended] Suite baselines auto pass/fail

**Что сделано:**
Suite Runner теперь умеет сравнивать фактическое число товаров в ответе с зафиксированным
baseline. `product_count` захватывается в run loop и хранится в `suite_run_items`
(миграция SQLite v4). `BaselineBadge` показывает `✓ N / ≥M` (зелёный) или `✗ N / ≥M`
(красный). Кнопка фиксации baseline предзаполняет prompt фактическим счётчиком.

**Как пользоваться:**
- Открыть `/testing` → вкладка **Сьюты** → запустить suite.
- После прогона рядом с каждым query появится `BaselineBadge`.
- Кнопка **«Зафиксировать baseline»** — сохраняет текущий `product_count` как `min_count`.
- При следующих прогонах: зелёный = товаров ≥ baseline, красный = меньше ожидаемого.

**Затронутые файлы:**
`app/db_local.py` (миграция v4, `product_count` в `suite_run_items`),
`app/api/suites.py`,
`frontend/src/components/testing/SuiteRunner.tsx`.

---

## 2026-05-09 · [WT-F2.7] RU-first автоподсказки

**Что сделано:**
`GameSuggestRow` в `components/shared/` — RU-название как первичное, EN — бледный
суффикс (`text-gray-500`). При выборе из списка подставляется RU-вариант.
`getDisplayName(game)` в `lib/catalog.ts` — shared-хелпер для единообразного
отображения имён по всему приложению.

**Как пользоваться:**
- Поисковое поле в разделе **Каталог** — автоподсказки теперь показывают RU-название первым.
- Везде где используется `getDisplayName(game)` — автоматически RU-first.

**Затронутые файлы:**
`frontend/src/components/shared/GameSuggestRow.tsx` (новый),
`frontend/src/lib/catalog.ts` (`getDisplayName`).

---

## 2026-05-09 · [WT-F2.5] Offer history page

**Что сделано:**
Chevron-раскрытие каждого оффера в Offers-табе `GameDetailDrawer` с `PriceChart`
(история цен из parsers `price_observations`). Новый endpoint
`GET /history/by-external-id?store_slug=&external_id=` в parsers;
proxy `GET /api/offers/history` в web-test.

**Как пользоваться:**
- Открыть `/catalog` → найти игру → открыть drawer → вкладка **Offers**.
- Кликнуть шеврон ▶ на оффере — раскроется `PriceChart` с историей цен.

**Затронутые файлы:**
`parsers/routers/history.py` (новый endpoint),
`app/api/history.py` (proxy),
`frontend/src/components/catalog/GameDetailDrawer.tsx`.

---

## 2026-05-09 · [WT-F1.6] Selectors playground + [WT-T1] Удалить AliasList.tsx

**Что сделано:**
**[WT-F1.6]** `SelectorPlayground`-блок под body в `UrlPlayground` (Debug → URL Probe):
ввод CSS-селектора → `DOMParser` применяет к полученному HTML без сетевых запросов,
показывает список совпадений с текстом + `outerHTML`.
**[WT-T1]** Удалён устаревший компонент `AliasList.tsx` (заменён `AliasEditor`).

**Как пользоваться:**
- Открыть `/debug` → вкладка **URL Probe** → ввести URL → получить HTML → ввести
  CSS-селектор в поле Selectors playground → сразу увидеть совпадения.

**Затронутые файлы:**
`frontend/src/components/parsers/SelectorPlayground.tsx` (новый),
`frontend/src/components/parsers/UrlPlayground.tsx`,
удалён `frontend/src/components/catalog/AliasList.tsx`.

---

## 2026-05-09 · [PRS-2] Парсер avito.ru (первая итерация)

**Что сделано:**
`AvitoParser`: browser-as-a-service + JSON/HTML-парсинг `/nastolnye_igry`.
Поля `raw`: `condition`, `location`, `seller_type`, `in_stock: True`.
Регистрируется автоматически при наличии `BROWSER_SERVICE_URL` в env.

**Как пользоваться:**
- Поднять browser-service: `docker compose --profile browser up -d --build`.
- Убедиться что `BROWSER_SERVICE_URL=http://localhost:8010` в `.env`.
- Avito появится в списке парсеров на `/parsers` и в `/search`.
- Enrich (описания, состояние, seller info) — следующая итерация.

**Затронутые файлы:**
`parsers/parsers/avito.py` (новый),
`parsers/parsers/registry.py`.

---

## 2026-05-09 · [INFRA-5] services/browser/ — browser-as-a-service

**Что сделано:**
FastAPI-сервис с Playwright + playwright-stealth. Принимает `POST /fetch {url}`,
возвращает `{html, cookies, headers}`. Профиль `browser` в docker-compose
(не входит в `full` — образ ~700 MB). `browser_client.py` в parsers активируется
при `BROWSER_SERVICE_URL`.

**Как пользоваться:**
```bash
docker compose --profile browser up -d --build
# в .env добавить:
BROWSER_SERVICE_URL=http://localhost:8010
```
Затем парсеры, которым нужен браузер (avito.ru), начнут его использовать автоматически.

**Затронутые файлы:**
`services/browser/` (новый сервис),
`parsers/browser_client.py` (новый),
`docker-compose.yml` (профиль `browser`).

---

## 2026-05-08 · [WT-F4.1-extended] parsers DB explorer (8/8 виджетов)

**Что сделано:**
Полный набор виджетов на вкладке **«БД парсеров: графики»** в `/database`:
Inventory, ProductsBrowser, Analytics, Timeline, LatencyHistogram,
StoreDistribution, ParserBreakdown, RawKeys. Ванильный `/dashboard` в parsers
можно отключить.

**Как пользоваться:**
- Открыть `/database` → вкладка **«БД парсеров: графики»**.
- Каждый виджет раскрывается по клику; есть info-tooltip с описанием метрики.
- `LatencyHistogram` — p50/p95/p99 по магазинам.
- `RawKeys` — покрытие extra-полей по парсерам (heatmap).

**Затронутые файлы:**
`frontend/src/components/database/parsers/ChartsTab.tsx` и соседние компоненты,
`app/api/parsers_db.py` (новые endpoints для графиков).
