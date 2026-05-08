# PLAN.md — web-test debug-портал

> **Верхний уровень roadmap'а монорепо** — [`/docs/roadmap.md`](../../docs/roadmap.md).
> Этот файл — оперативный roadmap **только для `services/web-test`**:
> что сделано недавно, что не доделано, что планируется дальше.
> Архитектурный обзор сервиса — в [`CLAUDE.md`](CLAUDE.md).

## Текущее состояние

Web-test превратился из тонкой обёртки над `/api/search` парсеров в
единый «cockpit» разработчика: 7 страниц, 6 backend-роутеров,
~50+ методов API. Покрывает три домена:

1. **Парсеры** — отладка, debug-инструменты, аналитика парсинга.
2. **Каталог + матчинг** — UI для catalog API: карточки игр, алиасы,
   импорт BGG/Tesera, ручной/batch reassess.
3. **Cross-service** — DLQ, health overview, baselines.

Подробно реализованные блоки см. в [CLAUDE.md → Project Overview](CLAUDE.md#project-overview).
В git-истории все 19 фич закоммичены префиксами `F1.1..F5.2` (см.
`git log --grep="^feat.*F[1-5]" --oneline`).

## Roadmap — что не доделано или хочется улучшить

### Парсеры

- **F4.1-extended (parsers DB explorer)** — ✅ **ЗАВЕРШЕНО** (8/8 виджетов).
  Все реализованы: Inventory, ProductsBrowser, Analytics, + 5 новых в вкладке
  «БД парсеров: графики» (`ChartsTab.tsx`): Timeline (stacked bar по cache/network/partial),
  LatencyHistogram (бины), StoreDistribution (доли + карточки), ParserBreakdown
  (search vs enrich, таблица), RawKeys (extra-ключи per-store).
  Можно отключить vanilla `/dashboard` в parsers — заменён полностью.
- **Selectors playground** (исходно P1.2 в плане-источнике) — текущий
  URL probe (F1.4) даёт raw HTML, но не пробует CSS-селекторы.
  Расширение: textarea с селектором + кнопка «применить» к raw HTML →
  показ выбранных элементов. Реализуется чисто на фронте через DOMParser.

### Каталог и матчинг

- **Авто-matching эвристики** — `matcher.py` пока считает только
  pg_trgm similarity. В коде есть TODO: бонус +0.1 для match по alias,
  штраф при несовпадении publisher/year, обработка expansions
  («Каркассон: Король и разбойник» не должна матчиться на базовый
  «Каркассон»). Требует расширения `find_best_match` и `find_match_candidates`.
- **Оffer history page** — на странице каталога нет вкладки «офферы
  игры» (что catalog уже отдаёт через `Game.offers`). Полезно при
  ручном матчинге: видеть, какие магазины уже привязаны.
- **Bulk-import wizard** — сейчас Import Wizard принимает batch BGG ID,
  но нет варианта «импортировать топ-N по rank» (есть CLI-скрипт
  `import_bgg_ranks.py`, но не вынесен в UI).

### QA / Testing

- **F4.4-extended (suite baselines auto pass/fail)** — пока используется
  только `min_count`, baselines не сравниваются автоматически на
  прогоне. Нужно:
  1. Вынести `product_count` в `ItemState` (сейчас он только в snapshot).
  2. На бэкенде в `app/api/suites.py:_run_suite_task` после прогона
     query тянуть baseline (если есть) и эмитить SSE-событие
     `baseline-pass` или `baseline-fail` со score-сравнением.
  3. UI: подсветка строк прогона по baseline-status, summary-counter
     pass/fail в `SuiteRunner.tsx`.
- **`expected_stores` / `min_field_coverage` в baselines** — поля
  есть в `SuiteBaselineSpec`, но не используются. Нужны: UI-форма
  редактирования baseline (сейчас только prompt для min_count) и
  логика compare на сервере.

### Cross-service

- **DLQ retry с backoff** — текущий `replay` срабатывает только по
  ручному действию. Опционально: cron-таск в parsers, который
  пробует replay'нуть DLQ-записи каждые N минут с экспоненциальным
  backoff (`attempt_count` уже есть). При `attempt_count > 10` —
  алерт через лог.
- **Status page** — `HealthBadge` показывает popover, но нет
  отдельной страницы `/status` с историей пингов и timeline'ом
  unmatched-counter'а. Полезно при ретроспективном анализе
  «когда сломался ingest».

### Auth и безопасность

- **`/api/debug/*` и `/api/dlq/*` без auth** — для dev OK, но при
  деплое наружу (если когда-нибудь web-test будет публичен) нужно
  закрыть как минимум через nginx auth_basic или JWT-middleware.
- **Catalog admin scope в web-test** — все mutations (link, merge,
  alias CRUD, game CRUD, import) требуют `CATALOG_API_KEY` со scope
  `admin`. Если catalog запущен с `REQUIRE_AUTH=1` без ключа в env
  web-test — UI получит 401. Нужен баннер «admin-функции отключены»
  при отсутствии ключа.

### Технический долг

- **`AliasList.tsx` устарел** — после F2.2 заменён на `AliasEditor.tsx`,
  но сам файл остался как dead-code. Удалить или вынести в read-only
  view (например, для не-admin режима).
- **Snapshot diff `extra` сейчас разбивается на `extra.<key>`** —
  это даёт более гранулярный diff, но если у магазина в `raw` живёт
  100 ключей, UI становится шумным. Нужен фильтр «показывать только
  изменения значений ≥ X%» или whitelist важных raw-ключей.
- **Frontend cache-key consistency** — каждая mutation invalidate'ит
  список ключей вручную. Лучше — единый `useInvalidate(domain)` хук,
  который по domain-name инвалидирует все связанные ключи.

## Известные ограничения

- **Парсеры — только 4 магазина** (hobbygames, lavkaigr, gaga,
  crowdgames). Добавление нового — задача на parsers, в web-test
  только дополнение `STORE_LABELS` в `frontend/src/lib/stores.ts`.
- **Tesera blocked from non-RU IPs** — Cloudflare блокирует
  `api.tesera.ru` с большинства не-RU-IP. Import Wizard вкладка Tesera
  в dev часто падает с 403. См. `services/catalog/CLAUDE.md` секция
  «Tesera — отложено».
- **Snapshot retention** — нет автоматической чистки старых snapshots.
  При активном использовании БД портала может разрастаться (один
  snapshot ~100KB). Решение — cron в `db_local.py` через
  `prune_snapshots(keep_days=30)`.

## Верификация после крупных изменений

```bash
# Из корня монорепо
docker compose --profile full up -d --build

# Smoke-тест всех новых фич:
curl http://localhost:8000/api/health/all                   # F5.2
curl http://localhost:8000/api/dlq                          # F5.1
curl http://localhost:8001/api/debug/contract               # F1.5
curl http://localhost:8002/matching/stats                   # F3.2

# UI:
open http://localhost:8000
# 1. /debug → Live Test (F1.1) на «каркассон»
# 2. /catalog → клик на игру → drawer с BGG/Wikidata (F2.1) + alias edit (F2.2)
# 3. /catalog → вкладка матчинга → reassess one (F3.3)
# 4. /database → «БД парсеров: товары» → удалить observation (F4.2)
# 5. /testing → запустить suite → pin baseline (F4.4)
# 6. /dlq → должен быть пустой (F5.1)
```
