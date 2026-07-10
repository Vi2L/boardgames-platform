# Ревью services/web-test — 2026-07-10

Отчёт review-агента. Проверено: backend `app/` (18 роутеров, 2 HTTP-клиента,
PortalDB), frontend `frontend/src/` (12 страниц, ~31.5K строк TSX/TS),
тесты, roadmap/PLAN/CLAUDE.md. `npx tsc --noEmit` — прогнан,
`uv run pytest` — прогнан.

## 1. Backend

### 🔴 Critical

- **Дублирующиеся определения методов в `CatalogClient` ломают PATCH
  scheduler на /bgg-sync.**
  `app/catalog_client.py:325` определяет `reschedule_job(self, job_id, payload)`,
  а `app/catalog_client.py:709` — **второй раз** `reschedule_job(self, job_id,
  *, cron_expr=…, enabled=…, params=…)` (kw-only). В Python побеждает второе
  определение. При этом `app/api/bgg_sync.py:48` вызывает
  `client.reschedule_job(job_id, payload)` **позиционно** →
  `TypeError: takes 2 positional arguments but 3 were given` → 500.
  Реальный потребитель есть: `frontend/src/lib/bgg-sync.ts:83` →
  `SchedulerHealth.tsx:424` и `SchemaForm.tsx` — т.е. редактирование
  cron/params job'ов на странице BGG Sync сейчас сломано. Так же
  задублированы `trigger_scheduler_job` (`:332` и `:700`) и
  `list_scheduler_jobs` (`:320` и `:728`) — эти совпадают по сигнатуре и
  «просто» мусор, но это мина.

### 🟠 Major

- **91 catalog-proxy endpoint отдаёт 500 вместо 502, когда catalog лежит.**
  `app/api/catalog.py` (69 блоков), `app/api/sources.py` (10),
  `app/api/bgg_sync.py` (12) ловят только `CatalogServiceError`, а
  `httpx.ConnectError`/`ReadTimeout` из `_ok_or_raise` не проходят через
  него — сырое 500 с трейсбеком. Для контраста `app/api/parsers_db.py:20-169`
  и `app/api/dlq.py` ловят `Exception → 502`. Нужен единый exception handler
  на приложение (`app.exception_handler(httpx.TransportError)` в `main.py`) —
  одна строка вместо правки 91 места.
- **Гигантское дублирование прокси-бойлерплейта.** `app/api/catalog.py`
  (963 строки) — ~90 идентичных `try/return await client.X()/except`;
  `app/catalog_client.py` (933 строки) — ~80 однострочных обёрток; плюс
  `_ok_or_raise`-логика скопирована инлайн 8 раз
  (`catalog_client.py:503-508, 731-736, 770-775, 788-793, 863-871, 885-892`).
  Кандидат на generic pass-through proxy (allowlist префиксов +
  `httpx.request(method, path, content=body)`) — это сократило бы
  ~1900 строк до ~200 и убрало бы третье место синхронизации при каждом
  новом catalog-endpoint (сейчас цепочка: catalog → client → router →
  lib/*.ts).
- **Security: незащищено всё, а не только `/api/debug/*` и `/api/dlq/*`.**
  Roadmap WT-F6.1 (`docs/roadmap.md:177`) занижает масштаб: auth-middleware
  в `app/main.py` нет вообще, grep по `app/` не находит ни одной проверки.
  Без авторизации доступны деструктивные ручки:
  `DELETE /api/parsers/cache?confirm=true` (wipe всей БД parsers-кеша,
  `app/api/parsers.py:35`), `POST /api/catalog/backup` (запуск pg_dump,
  `app/api/backup.py:76`), `POST /api/catalog/games/merge` (`catalog.py:271`),
  `PATCH /api/catalog/admin/runtime-flags/{key}` (kill-switch ML,
  `catalog.py:734`), `DELETE /api/parsers-db/observations/{id}`,
  DLQ replay/delete. `CATALOG_API_KEY` со scope admin вшит в прокси —
  любой, кто достучался до :8000 (порт публикуется на хост,
  `docker-compose.yml:139`), получает admin-доступ к catalog. Для
  локального dev терпимо, но фиксировать в roadmap стоит как «весь
  `/api/*`», не два префикса.
- **Копипаста health-логики.** `app/api/status.py:26-78` (`_collect_health`)
  — дословная копия `app/api/health.py:46-108` (`health_all`). Правка
  метрик потребует синхронных правок в двух местах. Вынести в общий модуль.
- **Падающий тест на main.** `tests/test_diff.py::test_diff_extra_field_changes`
  — `54 passed, 1 failed`: тест ожидает ключ `extra`, а `app/diff.py` давно
  разбивает на `extra.<key>` (задокументировано в CLAUDE.md «Подводные
  камни»). Тест не обновили вместе с кодом — сейчас он маскирует любые
  реальные регрессии диффа.

### 🟡 Minor

- **Orphan endpoints (нет потребителя во frontend):**
  - `GET /api/parsers-db/price-distribution` — `app/api/parsers_db.py:95`;
    `PriceHistogram.tsx` строит гистограмму из props, ручку никто не зовёт.
  - `GET /api/stats/summary`, `GET /api/stats/errors` — `app/api/stats.py:27,52`;
    обёртки `fetchStatsSummary`/`fetchStatsErrors` (`lib/api.ts:104,110`)
    никем не импортируются.
  - `GET /api/snapshots/{id}` — `app/api/snapshots.py:109`; `fetchSnapshot`
    (`lib/api.ts:432`) не используется.
  - `GET/PUT /api/suites/{id}` — `app/api/suites.py:51,62`; `fetchSuite` не
    используется, PUT-обёртки нет вовсе (редактировать suite из UI нельзя —
    только create/delete).
  - `GET /api/suites/{id}/runs/{run_id}` — `app/api/suites.py:174`; фронт
    зовёт только список runs.
  - `POST /api/catalog/matching/decisions/invalidate` (bulk) —
    `app/api/catalog.py:688`; `invalidateDecisionsBulk` в `lib/catalog.ts`
    не используется.
  - `GET /api/parsers/{slug}/run` — `app/api/parsers.py:53`; единственный
    потребитель — мёртвый `ParserCard.tsx:79` (см. ниже).
- **`asyncio.create_task` без удержания ссылки** — `app/api/search.py:233`,
  `app/api/suites.py:156`, `app/api/parsers.py:64`. По докам asyncio таск
  может быть собран GC посреди работы; хранить в set или использовать
  `BackgroundTasks`.
- **Неограниченный fan-out в batch-истории.** `app/parsers_client.py:401-423`
  (`get_history_batch`) — `asyncio.gather` без семафора;
  `GET /api/products/price-stats?ids=` при лимите поиска 500 даст 500
  параллельных запросов к parsers (`app/api/history.py:105`). Ограничить
  `asyncio.Semaphore(10-20)`.
- **Таймауты одинаковые 30s на всё** (`parsers_client.py:45`,
  `catalog_client.py:28`): для `reassess-all`/`bulk-revert` может не
  хватить, для health-ping — избыточно (health-блоки ждут до 30с прежде
  чем сказать «down»). Стоит развести: короткий на health, длинный/None
  на batch.

## 2. Frontend

### 🟠 Major

- **Мёртвый legacy-код с истёкшим дедлайном.** `pages/ParsersPage.tsx` +
  `components/parsers/ParserCard.tsx` не импортируются никем (App.tsx
  рендерит `Navigate` на `/debug`, `App.tsx:114-116`). Дедлайн удаления —
  2026-06-10 (roadmap WT-F9.1, `docs/roadmap.md:192-195`), прошёл месяц.
  Вместе с ними уходит orphan `GET /api/parsers/{slug}/run`.
- **Дублирование матчинг-UI: legacy `MatchingSection` внутри CatalogPage.**
  `pages/CatalogPage.tsx:521-958` (~440 строк: очередь, `QueueOfferRow`,
  `MatchingOfferDetail`, `ScoreBadge`) дублирует функциональность
  `/matching` (`QueuePanel.tsx`, `SingleMatchTab.tsx`). Roadmap прямо
  помечает её как legacy (`docs/roadmap.md:25-28`). Пока живы обе — каждый
  фикс в матчинг-flow надо делать дважды.
- **Компоненты-монолиты — 13 файлов >500 строк.** Худшие:
  - `components/catalog/PromotionPanel.tsx` — 1153 строки, 11 useState,
    9 queries/mutations;
  - `components/catalog/GameDetailDrawer.tsx` — 1063 строки, **19**
    queries/mutations, 11 useState;
  - `pages/CatalogPage.tsx` — 974 (см. выше, минус legacy — станет ~530);
  - `components/matching/QueuePanel.tsx` — 922, 15 queries, 12 useState,
    5 разных `refetchInterval`;
  - `components/matching/SingleMatchTab.tsx` — 762; `ControlTab.tsx` — 750;
    `GameGroupDrawer.tsx` — 666.
  GameDetailDrawer и QueuePanel — первоочередные кандидаты на распил по
  табам/секциям (внутри уже есть явные подкомпоненты-функции).
- **Раскол дизайн-систем — примерно пополам.** Файлов с классами старой
  палитры `gray-*` — **69**, с новой `zinc-*` — 51, `indigo-*` — 85,
  `violet-*` — 2 (осталось точечно). Целые домены на старой:
  `components/bgg-sync/*` (7 файлов), `components/parsers/*` (9),
  `components/sources/*` (7), `components/matching/*` (8 — причём
  `MatchingPage.tsx:11-12` фиксирует «gray-900/violet-700, не zinc/indigo»
  как осознанное решение). Токены (`statusSystem`) при этом уже на main —
  раскатка WT-DESIGN-PR3 прошла по страницам, но не по этим компонентам.
- **Нет ни одного frontend-теста и линтера.** `package.json` — нет
  `test`/`lint` скриптов, нет vitest/eslint конфигов,
  `find src -name "*.test.*"` пуст. Для `lib/loyalty.ts`,
  `lib/similarity.ts`, `lib/offer.ts` (чистая бизнес-логика с денежными
  расчётами) — это прямой риск.

### 🟡 Minor

- **TypeScript чистый**: `npx tsc --noEmit` — 0 ошибок (strict-режим
  билдится через `tsc && vite build`). Плюс, а не минус — фиксирую как факт.
- **Кнопка Cmd+K в топбаре не работает.** `App.tsx:104` передаёт
  `onOpenCommandPalette={() => setPaletteOpen(true)}`, но `CommandPalette`
  (App.tsx:140) state не получает — `paletteOpen` подавлен хаком
  `{void paletteOpen}` (App.tsx:147, там же TODO). Хоткей работает, клик
  по кнопке `Topbar.tsx:52` — нет.
- `bgJobsCount={0}` захардкожен (App.tsx:105, TODO PR 3+).
- Молчаливых `catch` практически нет — пустые catch только вокруг
  localStorage/JSON.parse (`lib/searchHistory.ts:30`,
  `ui/CommandPalette.tsx:101`, `lib/sse.ts:128`) — легитимно.
  `toast.error` — 63 вызова; ошибки мутаций покрыты хорошо.

## 3. Данные / UX

- **`/matching` — шторм polling'а** (major). Одновременно активны:
  `MatchingPage.tsx` 3 запроса × 5s, `ControlTab.tsx` 4 × 5s,
  `ActiveJobsStrip.tsx` × 3s, `QueuePanel.tsx` 5 интервалов
  (5s/15s/15s/30s/60s), `SingleMatchTab.tsx` до 3 × 1.5–2s при открытом
  прогоне — суммарно >100 запросов/мин с одной вкладки, и каждый проходит
  двойной хоп web-test→catalog. SSE-инфраструктура в проекте уже есть
  (`lib/sse.ts`, search/suites) — логичный шаг: один SSE-канал
  `/api/catalog/matching/events` (queue depth, ml-status, worker tick)
  вместо 10+ таймеров. Для Import Wizard/JobHistory polling с авто-стопом
  (`refetchInterval: (q) => …`) — адекватен, менять не надо.
- **`POST /status/ping` каждые 30с с клиента** (`app/api/status.py:81`):
  история пингов пишется только пока вкладка /status открыта — ретроспектива
  «когда сломался ingest» получается дырявой. Логичнее server-side цикл
  (asyncio task в lifespan) с тем же интервалом.
- `GET /api/suites/{id}/run` — GET с побочными эффектами (создаёт
  snapshots/run-записи, `suites.py:137`). Вынужденно из-за EventSource, но
  стоит хотя бы пометить в docstring и не кешировать.

## 4. Тесты

- **Backend**: 11 файлов в `tests/`, 55 тестов — покрывают db_local, diff,
  SSE search/suites, health, history, stats-proxy, snapshots. Но: 1 тест
  падает на main (см. выше), и **нет ни одного теста на крупнейший роутер
  `api/catalog.py`** (963 строки, 69 endpoints) и на `catalog_client.py` —
  дубликат `reschedule_job` поймался бы элементарным smoke-тестом.
- **Frontend**: тестов нет совсем (см. выше).

## 5. Идеи функциональности (из уже написанного кода)

1. **Generic catalog-proxy** — одна ручка `api.route("/catalog/{path:path}")`
   с allowlist + пробросом query/body убирает три слоя синхронизации;
   частные роутеры остаются только там, где есть логика (валидация merge,
   multipart CSV).
2. **Баннер «admin-функции отключены»** (WT-F6.2) — `deps.py` уже знает про
   `CATALOG_API_KEY`; достаточно отдать флаг в `/api/health` и показать
   баннер в `AppShell`. Дёшево и закрывает молчаливые 401.
3. **Suite baselines auto pass/fail** — `product_count` уже пишется в
   `suite_run_items` (`suites.py:273-277`), baseline с `min_count` уже
   хранится: сравнить в `_run_suite_task` и эмитить `baseline-fail` — это
   ~20 строк (PLAN.md:54-66 это уже описывает — довести).
4. **Журнал поисков UI** — `/api/db/searches` полноценно работает
   (`app/api/db.py:93`), фронт его дергает только в DatabasePage; история
   запросов с фильтром по магазину на `/` почти бесплатна (WT-F8.1).
5. **Snapshot retention** — PLAN.md:113 фиксирует разрастание portal-БД;
   cron-prune в `db_local.py` + кнопка «очистить старше 30д» на /testing.
6. **Обновить документацию**: CLAUDE.md сервиса отстал — в списке роутеров
   нет `backup.py`, `bgg_sync.py`, `sources.py`, `status.py`; секция Design
   system утверждает «на main этого ещё нет», хотя `ui/`, `AppShell`,
   `/__design` давно на main; PLAN.md упоминает несуществующий
   `AliasList.tsx` и «7 страниц» (их 12).

## Главные выводы

1. **Есть один реально сломанный флоу**: дубликаты методов в
   `catalog_client.py` (:325 vs :709) ломают PATCH scheduler со страницы
   BGG Sync — чинится удалением первого блока определений и вызовом kwargs
   в `bgg_sync.py:48`. Плюс один падающий тест на main.
2. **Прокси-слой — главный источник энтропии**: ~1900 строк однотипного
   boilerplate'а (client + router), 91 endpoint отдаёт 500 вместо 502 при
   падении catalog, каждый новый upstream-endpoint требует правок в
   4 местах. Generic proxy + глобальный exception handler решают обе
   проблемы разом.
3. **Уборка просрочена и дешева**: ParsersPage/ParserCard (дедлайн
   2026-06-10 прошёл), MatchingSection в CatalogPage (~440 строк дубля
   /matching), 7 orphan endpoints, стейл-доки — всё это удаляется за один
   PR без риска.
4. **Дизайн-система застряла на середине**: 69 файлов на gray против 51 на
   zinc; хуже всего — `components/matching/*` и `bgg-sync/*`, где старая
   палитра закреплена комментариями как «осознанное временное». Чем дольше
   висит, тем дороже раскатка.
5. **Асимметрия зрелости**: backend с тестами и аккуратным error mapping
   (для parsers), frontend — 31K строк без единого теста и линтера, с
   монолитами по 900–1150 строк и polling-штормом на /matching. Следующие
   вложения стоит направить туда: vitest на `lib/{loyalty,similarity,offer}.ts`,
   распил GameDetailDrawer/QueuePanel, SSE для matching-метрик.
