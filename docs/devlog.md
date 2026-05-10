# Devlog — boardgames-platform

Журнал завершённых задач. Каждая запись: дата, ID, что сделано, как пользоваться.

> **Для агентов:** после завершения задачи **перенеси** её из `roadmap.md` сюда —
> добавь запись **в начало** файла (новые сверху) и удали строки из roadmap.
> Формат — см. примеры ниже. Не редактируй старые записи.

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
