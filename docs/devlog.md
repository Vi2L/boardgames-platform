# Devlog — boardgames-platform

Журнал завершённых задач. Каждая запись: дата, ID, что сделано, как пользоваться.

> **Для агентов:** после завершения задачи **перенеси** её из `roadmap.md` сюда —
> добавь запись **в начало** файла (новые сверху) и удали строки из roadmap.
> Формат — см. примеры ниже. Не редактируй старые записи.

---

## 2026-05-18 · [CAT-FILTER] фильтр «только настолки» на 3 слоях (parsers + ingest + LLM)

**Что сделано:** трёхслойная защита от не-настольных товаров. Раньше на
запрос «книга» парсеры avito/ozon/onlinetrade возвращали книги/одежду,
catalog их сматчивал auto-T1 на похожие игры (книга «Каркассон.
Жан-Жак Руссо» → игра «Каркассон»).

**Слой 1 — парсеры.**
- avito: strict-фильтр локально по `microCategoryId` whitelist'у
  `{2301995, 2301997, 2301999}` («Настольные игры» внутри Спорт/Хобби).
  Параметр `categoryId` в URL `/web/1/js/items` Avito игнорирует —
  подтверждено probe'ами в `bin/probe_avito_*.py`.
- wildberries: убран soft twin-search fallback. Возвращаются только
  `subjectId == 120` (Настольные игры). Если в выдаче WB меньше limit'а
  настолок — возвращаем сколько есть.
- ozon: URL переключен с `/search/?text=` на
  `/category/nastolnye-i-kartochnye-igry-13506/?text=` —
  поиск внутри категории «Настольные и карточные игры».
- onlinetrade: URL `/search.html?search=` → `/catalogue/board_games/?search=`.

**Слой 2 — контракт + ingest.**
- `IngestOfferIn.category: str | None` (`packages/shared-py/bg_shared/
  ingest.py`). `catalog_publisher` проставляет `"boardgames"` для всех
  парсеров — они теперь возвращают исключительно настолки.
- `POST /ingest/offers` (catalog) проверяет
  `_ALLOWED_CATEGORIES = {boardgames, expansion, accessory, None}`.
  `None` оставлен для legacy-клиентов. Офферы вне whitelist'а дропаются
  до записи в БД. Ответ обогащён счётчиком `skipped_category`.

**Слой 3 — LLM arbiter (T3).**
- system-prompt qwen2.5 учит возвращать
  `{"game_id": null, "reason": "not_a_boardgame: <причина>", "confidence": 0.99}`
  для очевидно не-настольных товаров (книги, одежда, посуда).
- `tier_3_llm` распознаёт префикс `not_a_boardgame:` + confidence ≥
  threshold и возвращает `MatchAction.REJECT`. Worker `_finalize_reject`
  ставит `match_status='rejected'`, пишет negative cache в T0 →
  следующий ingest того же `title_norm` отсечётся ещё до T1.

**Cleanup-скрипт.** `services/catalog/catalog/scripts/reset_mismatched.py`
с dry-run/`--apply`/`--threshold`/`--store` для сброса исторических
auto-матчей маркетплейсов с низким `match_score` в `unmatched`.

**Как пользоваться:**

```bash
# 1. После деплоя сбросить кеш парсеров (TTL 4ч переждать не надо):
curl -X DELETE "http://localhost:8001/api/cache?confirm=true"

# 2. Проверить, сколько исторического мусора есть (dry-run):
docker compose exec catalog python -m catalog.scripts.reset_mismatched

# 3. Применить cleanup (threshold 0.75 — порог T1 auto-match):
docker compose exec catalog python -m catalog.scripts.reset_mismatched \
    --apply --threshold 0.75

# 4. Проверить здоровье через debug-парсе на «мусорные» запросы:
curl -sG "http://localhost:8001/api/debug/parse" \
    --data-urlencode "q=книга" --data-urlencode "stores=ozon,avito" \
    --data-urlencode "limit=5"
# Ожидаемо: 0 продуктов (категория не пропускает).
```

**Затронутые файлы:**
- Парсеры: `services/parsers/parsers/stores/{avito,wildberries,ozon,onlinetrade}.py`.
- Контракт: `packages/shared-py/bg_shared/ingest.py`,
  `services/parsers/parsers/catalog_publisher.py`,
  `services/catalog/catalog/{routers/ingest.py,schemas.py}`.
- LLM/worker: `services/catalog/catalog/matching/v2/{llm_arbiter,worker}.py`.
- Cleanup: `services/catalog/catalog/scripts/reset_mismatched.py`.
- Probes: `bin/probe_avito_{category,item_keys,microcategory}.py`.

Коммит `715e6cd`. Тесты: 153 parsers + 53 catalog passed.

---

## 2026-05-17 · [WT-F11-DRAWER] GameGroupDrawer с табами Офферы/История/Матчинг/Raw

**Что сделано:** Полный split-view drawer для канонической группы из
master-таблицы (`/` страница, group mode). Заменяет proxy-решение из
PR5 (клик по группе открывал `ProductDrawer` с min-offer'ом).

Ветка `feat/wt-f11-drawer`, коммит `55febcc`. Реализует
`pages/05-search.md` § Drawer полностью.

**Архитектура:** Один файл `components/search/GameGroupDrawer.tsx`
(~480 строк) — hybrid (как `BggImportPanel`/`CatalogPage`). Inner-функции
на каждый таб + extracted hook `useGroupHistory()` для нетривиальной
агрегации `fetchHistory(id)` параллельно по offers через `useQueries`.

**4 таба:**
- **Офферы** — Hero (cover + price range + stores in-stock) + sorted offers
  list (in-stock first, asc по цене), min-price emerald, sale-tag +
  line-through original_price если on_sale.
- **История цен** — Sparkline 90д для main-серии (min без Avito) +
  ОТДЕЛЬНЫЙ sparkline для Avito (б/у-рынок, clarify Q2). Last 10 changes
  (date / store / from→to / Δ%) по всем offers группы.
- **Матчинг** — `fetchMatchCandidates(canonicalTitle, 5)` через catalog API
  → best-effort кандидаты с Badge (auto/manual/pending по thresholds).
  Frontend-fallback: нет `game_id` в ProductOut, поэтому не «linked
  offers», а «вероятные кандидаты» с link на /catalog (clarify Q1 var. B).
- **Raw** — pretty-print `ProductGroup + offers[]` JSON.

**UX:**
- Split-view через `ui/Drawer` (Radix Dialog modal=false) — таблица за
  drawer'ом остаётся кликабельной.
- Cmd+↑/↓ — prev/next group (clarify Q5).
- Esc — close (Radix).
- Footer: «Открыть карточку игры» → `/catalog?tab=games&q={title}`
  (clarify Q3 — нет game_id для direct id deep-link).
- Один drawer на screen (clarify Q6) — invariant в SearchPage:
  `selectedGroup` ИЛИ `selectedProduct`, не оба одновременно.

**Как пользоваться:**
1. `/` → введи запрос (group-mode по умолчанию).
2. Клик на строку группы → GameGroupDrawer с табом «Офферы».
3. Cmd+↑/↓ — пройдись по соседним группам без закрытия drawer'а.
4. Таб «История цен» — для группы со ≥2 магазинами + накопленной историей.
5. Таб «Матчинг» — top-5 catalog candidates для ручной привязки в /matching.

**Затронутые файлы:**
- `services/web-test/frontend/src/components/search/GameGroupDrawer.tsx` — новый (~480 строк).
- `services/web-test/frontend/src/pages/SearchPage.tsx` — state `selectedGroup`,
  invariant «один drawer на screen», `handleSelectProduct/Group` helpers.

**Не сделано (отложено):**
- Backend `/search/grouped` с `game_id` — после этого таб «Матчинг»
  заменится на «linked offers + кнопка отвязать» (handoff var. A).
- URL-state для активного tab (`?tab=history`) — пока локальный.

---

## 2026-05-17 · [WT-DESIGN-PR4/PR5] Job UI shared + Search WT-F11 grouping

**Что сделано:** Финальные коммиты ветки `feat/wt-redesign-rollout` —
два глубоких feature-PR'а поверх hygiene PR3.

**PR4 — Job UI** (`pages/04-jobui.md`, commit `820af0d`):
- Новый каталог `components/jobs/` (468 строк):
  - `JobView.tsx` — generic-шаблон активного job'а: header (status badge
    из statusSystem + name + phase + elapsed/ETA), `<ProgressBar>` из ui/
    с meta `ok/skip/fail`, 4-col stats grid (rate/elapsed/eta/ok-fail),
    `<PhaseStrip>`, `<JobLogPanel>` из ui/.
  - `PhaseStrip.tsx` — phase pills (done emerald / current indigo+pulse
    / pending neutral) с ChevronRight-разделителями.
  - `adapters.ts` — `importJobToJobLike()` маппит `ImportJob` (BGG/Tesera/
    Dicefest) на унифицированный `JobLike`. ETA — linear extrapolation
    если backend не отдаёт rate.
- Интегрировано: `bgg-sync/JobHistoryTable` (expanded row), `catalog/
  BggImportPanel` (две секции активного job'а).

**PR5 — Search WT-F11** (`pages/05-search.md`, commit `a481da2`):
- `lib/searchGrouping.ts` (180 строк) — greedy-clustering по
  `titleSimilarity` ≥ 0.6. O(n×k) на ≤500 results = ~5-10 мс. Группы
  с 1 оффером → `orphans[]`. Backend пока не возвращает `game_id`,
  поэтому frontend-fallback (var. B из спеки).
- `components/search/ResultsTableGrouped.tsx` — Master-таблица:
  canonical_title · stores in-stock/total · min · spread (±X% amber
  если >30%) + stores-pills.
- `components/search/UnmatchedSection.tsx` — collapsible секция с
  amber-border, ссылка «Сматчить» → /matching.
- `store/search.ts` — `groupMode: 'group' | 'flat'` (persist v2 partialize).
- `pages/SearchPage.tsx` — toggle group/flat (segmented control),
  условный рендеринг.

**Как пользоваться:**
1. `git checkout feat/wt-redesign-rollout && cd services/web-test/frontend && npm run dev`.
2. /bgg-sync → таб «История» → клик по любой строке job → видишь
   новый JobView (status badge + progress + phase strip + log).
3. /catalog → таб «BGG» → запусти BGG-import → JobView показывает
   живой прогресс в едином UI.
4. / (Поиск) → введи запрос → результаты по умолчанию группируются
   («По игре»). Toggle справа от tabs `По игре / Плоский`. Под основной
   таблицей — секция «Не сматчено» (orphans).

**Затронутые файлы:**
- `services/web-test/frontend/src/components/jobs/*` — новые (4 файла).
- `services/web-test/frontend/src/components/search/{ResultsTableGrouped,UnmatchedSection}.tsx` — новые.
- `services/web-test/frontend/src/lib/searchGrouping.ts` — новый.
- `services/web-test/frontend/src/store/search.ts` — расширен `groupMode`.
- `services/web-test/frontend/src/pages/SearchPage.tsx` — toggle + grouped рендеринг.
- `services/web-test/frontend/src/components/bgg-sync/JobHistoryTable.tsx` — JobView в expanded row.
- `services/web-test/frontend/src/components/catalog/BggImportPanel.tsx` — JobView вместо inline progress.

**Что отложено:**
- `<GameGroupDrawer>` с табами Офферы/История/Матчинг/Raw для grouped-режима —
  пока drawer reuses `ProductDrawer` (открывает min-offer группы). Roadmap
  `WT-F11-DRAWER`.
- `suiteRunToJobLike()` adapter для SuiteRunner (testing) — отдельная итерация.
- `JobView.canCancel` — backend пока не поддерживает (CLAUDE.md handoff §11).

## 2026-05-17 · [WT-DESIGN-PR3] Раскатка дизайн-системы на весь портал

**Что сделано:** Ветка `feat/wt-redesign-rollout` — 3 коммита, раскатка
новой `ui/*` + `design-tokens` на все страницы `web-test/frontend` и 51
sub-компонент. Без структурной перестройки (cache-keys, store-схемы,
backend-контракты не тронуты).

- **3a · 11 страниц** (`728b705`) — inline-табы повсюду заменены на
  `<Tabs>` из ui/ (Radix-based, единый focus-ring); эмодзи `✓ ⭐ 💾 ⚡ 🌐`
  → lucide-иконки; ad-hoc status-цвета (`bg-yellow-950 text-yellow-400`)
  → `<Badge status="…">` / `<Tag tone="…">` через `statusSystem`; plain
  `<button>` → `<Button variant="…">` / `<IconButton>`; `gray-*` → `zinc-*`
  (нейтральный undertone — handoff §5); custom StatusDot на StatusPage
  → `<StatusDot>` из ui/; числа в колонках получили `tabular-nums`.
- **3b · CatalogPage Games** (`0541209`) — Sticky thead z-10, активная
  строка `bg-indigo-500/10`, hover `zinc-800/30`, resize-handle indigo
  (был violet), SourceBadge через alpha-tokens (`bg-orange-500/15` для
  BGG, `bg-blue-500/15` для tesera), ColumnsPicker через Button-обёртки,
  «Показать ещё» как `<Button variant="ghost" loading>`. Глубокая
  переделка по `pages/03-games.md`. MatchingSection (legacy, заменена
  `/matching`) обновлена только по цвету (violet → indigo).
- **3c · 51 sub-компонент** (`1cfa168`) — violet → indigo по 50 файлам;
  status-pills `bg-green-900/40` → `bg-emerald-500/15` из tokens; эмодзи
  в UI рендеринге (`✓ done`, `✗ Ошибка`, `✓ да`, `✓ в каталоге`) →
  `<CheckCircle2 />` / `<XCircle />`. Затронуто: `parsers/`, `catalog/`,
  `matching/`, `database/parsers/`, `bgg-sync/`, `sources/`, `testing/`.

`/matching` сознательно осталась в gray/violet — это решение из
`pages/06-matching-v2-improvements.md` (дельта-апгрейд WT-MATCH-UX
поверх существующего стиля, не путать с proof из §01).

**Как пользоваться:** `git checkout feat/wt-redesign-rollout` → `npm run
dev` в `services/web-test/frontend/` → http://localhost:5173. Обход
страниц: /, /parsers, /debug, /database, /catalog, /matching, /bgg-sync,
/sources, /testing, /dlq, /status. Проверь визуально — табы везде с
indigo underline, никаких эмодзи в UI (только в toast-сообщениях
осталось — handoff не запрещает), статусы единообразно через Badge.

**Не сделано (отложено в roadmap):**
- PR 4 Job UI (`components/jobs/JobView.tsx` + reuse в BggSync/Testing/
  Catalog) — `pages/04-jobui.md`.
- PR 5 Search WT-F11 group-by-game — `pages/05-search.md` (требует
  либо backend endpoint, либо frontend-fallback агрегации).

**Затронутые файлы:**
- `services/web-test/frontend/src/pages/*` — 11 страниц.
- `services/web-test/frontend/src/components/*` — 51 файл.
- Build: `1366 KB → 1367 KB` (изменения чисто визуальные).

## 2026-05-17 · [WT-HELP] Раздел «Помощь» с интерактивной HTML-инструкцией

**Что сделано:** Self-contained HTML-страница `frontend/public/help.html` (~79 КБ)
с инструкцией администратора по всем 12 разделам портала — sticky TOC слева
с активной подсветкой через `IntersectionObserver`, полнотекстовый AND-поиск
по содержимому + `data-keywords` (синонимы), сворачиваемые секции, табы внутри
секций, hotkey <kbd>/</kbd> для фокуса на поиске, 8 готовых workflow-рецептов,
блок troubleshooting. `NavItem` в Sidebar получил флаг `external?: boolean` —
такие пункты рендерятся как `<a target="_blank">` минуя React Router; то же
поле добавлено в `NavCommandItem` для CommandPalette (open через `window.open`).
В прод-сборку html попадает автоматически из `public/` через Vite.

**Как пользоваться:** В сайдбаре снизу появился пункт **Помощь** (иконка 📖
BookOpen) — клик открывает <http://localhost:8000/help.html> в новой вкладке.
Также доступно через Cmd+K → «Помощь». Внутри: <kbd>/</kbd> — поиск,
<kbd>Esc</kbd> — снять фокус, клик по заголовку секции — свернуть/развернуть.
Печать (Cmd+P) даёт чистый print-friendly документ без сайдбара.

**Затронутые файлы:**
- `services/web-test/frontend/public/help.html` — новый (1364 строки HTML+CSS+JS).
- `services/web-test/frontend/src/components/layout/Sidebar.tsx` — `NavItem.external`,
  ветка рендера для `<a target="_blank">`.
- `services/web-test/frontend/src/App.tsx` — пункт «Помощь» в NAV.
- `services/web-test/frontend/src/components/ui/CommandPalette.tsx` —
  `NavCommandItem.external` + open через `window.open`.

---

## 2026-05-16 · [WT-MATCH-UX] Matching UX upgrade — §A..§G (handoff 06-matching-v2-improvements)

**Что сделано:** Полный точечный апгрейд `/matching` admin-панели по handoff'у
`docs/cat-4-matching-v2.md` (artboards `wireframes.html → 08`). Стиль gray/violet
сохранён — переключение на zinc/indigo это отдельный track в `feat/admin-panel-redesign`.

Ветка: **`feat/admin-panel-redesign`** (коммиты `4d7826e` + `d348395`).

**Backend** (5 новых endpoint'ов в catalog + миграция 0014):

- `GET /matching/queue/depth?range_hours=24` — sparkline по bucket'ам (peak/now/drainage/ETA).
  Реконструкция по `created_at`/`processed_at` (не точный snapshot).
- `GET /matching/queue/{id}` — lookup match_queue записи + `position_in_pending`.
- `DELETE /matching/queue/{id}` — cancel pending (409 если processing).
- `POST /matching/ml-models/{name}/probe` — force probe для UI Контроль.
- `/admin/auto-recovery-rules` CRUD (миграция 0014, новая таблица; runner-job TODO).
- `OllamaHealth` теперь tracks **p50/p95/rps_1m** per-model + `last_error_text`
  (rolling-buffer 60 точек, `record_success(model, duration_ms)`).
- `scheduler._TICK_HISTORY` — ring-buffer 30 тиков per interval-job; отдаётся через
  `SchedulerJobOut.tick_history`.
- `MatchAction.T2_PROGRESS`/`T3_PROGRESS` — intermediate match_log entries из worker'а
  для UI live-stages (revert этих action'ов запрещён).

**Frontend** (4 новых компонента + полный апгрейд 3 вкладок):

- `MetricSpark.tsx` — inline-SVG sparkline (без recharts).
- `ActiveJobsStrip.tsx` — persistent indicator активных ImportJob'ов.
- `ConfirmPanel.tsx` — inline confirm (filter summary + impact list + Esc/Enter)
  заменяет `window.confirm` в kill-switch / re-enqueue.
- `KeyboardCheatsheet.tsx` — overlay по `?`, 4 группы шорткатов.
- `store/matching-metrics.ts` — Zustand client-buffer 60 snapshot'ов (fallback
  если backend depth_history degraded).

`MatchingPage` header — **6-section dense strip** (title / models с rps+p50+p95+fail /
queue stats c delta / depth sparkline 24h / worker countdown 250ms / ActiveJobsStrip).
Tab strip — live counters (`Очередь · 142` с амбер фоном при >100), alert-dot на
`Контроле` при CB open/half_open, KBD shortcuts 1-5+`?`.

`ControlTab` — KillSwitch с ConfirmPanel impact preview (X pending останутся,
Y processing завершат batch); ModelsCard с расширенными метриками + latency sparkline
+ Force-probe button; WorkerCard с tick countdown + 3 mini-метрик (duration / error rate / history).

`QueuePanel` — DepthChartSection (full-width 24h), ReasonBreakdownSection
(horizontal bars, clickable → ConfirmPanel re-enqueue by reason),
AutoRecoveryRulesSection (CRUD list + create form).

`SingleMatchTab` — ProgressDrawer теперь polling `/matching/queue/{id}` →
**3-step position indicator** (enqueued → picked → processing); T2/T3 stages
из intermediate match_log entries; ETA-countdown на базе qwen.p50; Cancel button
(Esc) для pending записей.

**SPA fallback fix** (`d348395`): `SPAStaticFiles(StaticFiles)` подкласс — на 404
от static отдаём `index.html`, чтобы direct URL и refresh не ломались
(`localhost:8000/matching` → 200 вместо 404).

**Как пользоваться:**
- `docker compose build catalog web-test && docker compose up -d --force-recreate catalog web-test`
- Открой `http://localhost:8000/matching` — увидишь полную панель.
- Шорткаты: `1-5` — вкладки, `?` — cheatsheet, `Esc` — закрыть/cancel.
- Force-probe модели — Контроль → ML-модели → кнопка появляется при open/half_open.
- Auto-recovery rules — Очередь → нижняя секция → `[+ add]` → JSON-форма
  (runner ещё не реализован, правила сохраняются «armed but not executing»).

**Затронутые файлы (29 файлов):**

Backend:
- `services/catalog/alembic/versions/20260516_0014_auto_recovery_rules.py` (new)
- `services/catalog/catalog/routers/auto_recovery.py` (new)
- `services/catalog/catalog/routers/{matching,scheduler}.py`, `api.py`, `models.py`, `schemas.py`
- `services/catalog/catalog/matching/v2/{queue_repo,health,embedder,llm_arbiter,worker,auditor,domain}.py`
- `services/catalog/catalog/scheduler.py`

Proxy:
- `services/web-test/app/{main,catalog_client}.py`, `app/api/catalog.py`

Frontend:
- `services/web-test/frontend/src/components/matching/{MetricSpark,ActiveJobsStrip,ConfirmPanel,KeyboardCheatsheet}.tsx` (new)
- `services/web-test/frontend/src/store/matching-metrics.ts` (new)
- `services/web-test/frontend/src/pages/MatchingPage.tsx`
- `services/web-test/frontend/src/components/matching/{ControlTab,QueuePanel,SingleMatchTab}.tsx`
- `services/web-test/frontend/src/lib/matching.ts`

**Известные ограничения:**
- Auto-recovery rules runner — не реализован. Правила создаются и видны, но
  не выполняются автоматически (нужен scheduler-job `auto_recovery_runner`).
- `queue_depth_history` — реконструкция по `created_at`/`processed_at`,
  не точный snapshot. Для production-grade — нужна snapshot-таблица + cron.
- Skipped-таблица в Очереди — без `shift-range select` / `hover-actions` /
  `relative time` (handoff 06 §D.5 — упрощено, оставлено как было).

---

## 2026-05-16 · [WT-DESIGN-PR1] Foundation — design tokens + ui primitives + AppShell

**Что сделано:** PR 1 из handoff-пакета `docs/web-test-redesign-brief.md`
(см. также `.scratch/admin-panel-design/` — оригинальный handoff). Создаёт
базу для полного редизайна `web-test` под единый design-system: zinc base +
indigo-400 accent + Inter / JetBrains Mono. Существующие страницы продолжают
работать без изменений — они теперь рендерятся внутри `AppShell`.

Ветка: **`feat/admin-panel-redesign`** (коммит `1e3c107`).

**Foundation:**
- `src/lib/design-tokens.ts` — runtime tokens (colors zinc+indigo, узкая
  10-18px fontSize шкала, density compact 32px, stores mapping, statusSystem
  с 12 ключами → tone, toneClasses bundle).
- `tailwind.config.ts` extend через `tokens.tailwind`.
- `index.html` — Google Fonts preconnect + Inter + JetBrains Mono.
- `src/vite-env.d.ts` — типы для `import.meta.env`.

**UI primitives** (`src/components/ui/`, 20 файлов + barrel):
- Form/action: `Button`, `IconButton`, `Input`, `Textarea`, `Select` (Radix),
  `Combobox` (cmdk+Popover).
- Status/display: `Badge`, `StatusDot`, `Tag`, `ProgressBar`, `Skeleton`,
  `KBD`, `EmptyState`.
- Overlays: `Dialog`, `Drawer` (Radix Dialog с modal=false split-view),
  `Tooltip` + `TooltipProvider`.
- Navigation/containers: `Tabs` (Radix underline), `Toolbar`.
- Composite: `DataTable` (TanStack Table + virtual ≥500 строк через
  `@tanstack/react-virtual`), `JobLogPanel`, `HealthCard` (sparkline),
  `CommandPalette` с register-API через хук `useCommand`.

**Layout** (`src/components/layout/`, 4 файла): `AppShell`, `Sidebar`,
`Topbar`, `BgJobsIndicator`. Sidebar collapse persist в `localStorage`.

**Design System gallery** — `/__design` доступен при `import.meta.env.DEV`,
16 секций со всеми примитивами в variants × sizes (smoke-test PR 1
acceptance).

**Deps**: `@radix-ui/react-{dialog,tooltip,tabs,select,popover,slot}`,
`@tanstack/react-virtual`, `class-variance-authority`. Никаких UI-библиотек
целиком — только точечные Radix-примитивы.

**Старая `src/components/shared/CommandPalette.tsx`** помечена `@deprecated`,
новая в `ui/` смонтирована. Старая будет удалена через 1-2 итерации, когда
страницы мигрируют.

**Как пользоваться:**
- В новом коде импортируй из `'@/components/ui'` или
  `'../../components/ui'` — `import { Button, Badge, Drawer } from '@/components/ui'`.
- Статусы — через `<Badge status="auto" />`, не локальные color-словари
  (источник правды — `tokens/status-system.md`).
- Density `compact` (32px row) — default. `cozy` / `comfortable` — для
  отдельных страниц через Settings dialog (TODO).

**Acceptance (handoff PR 1 §8):**
- ✅ `tailwind.config.ts` extend через tokens
- ✅ 20 примитивов экспортируются из `ui/index.ts`
- ✅ `/__design` галерея под `import.meta.env.DEV`
- ✅ TypeScript строгий, нет `any`
- ✅ `npm run build` чистый, 361KB gzip JS
- ✅ AppShell обернул все маршруты, collapse persist'ит
- ✅ Существующие страницы не сломались

**Что НЕ в скоупе PR 1:**
- Переписывание страниц на новый ui — отдельные PR 2/3+ (Matching proof,
  Games, Search, BggSync, остальные).
- Миграция `HealthBadge` в `ui/HealthCard` — отдельный track с правкой /status.
- `useBgJobs()` агрегатор — заглушка `count=0`, реальная агрегация позже.
- `breadcrumbs.ts` модуль — пока inline в App.tsx.
- Settings dialog (density toggle) — отдельная задача.

**Затронутые файлы (36 файлов):**
- 27 новых: `src/lib/design-tokens.ts`, `src/components/ui/*` × 20 + `index.ts`,
  `src/components/layout/*` × 4, `src/pages/__design/DesignSystemPage.tsx`,
  `src/vite-env.d.ts`.
- 6 изменённых: `App.tsx`, `tailwind.config.ts`, `index.html`,
  `components/shared/CommandPalette.tsx` (@deprecated), `package.json`,
  `package-lock.json`.

---

## 2026-05-16 · [WT-F8] Log поисковых запросов на странице `/` (решено иначе)

**Что сделано:** Цель пункта — быстрый доступ к журналу запросов без перехода
в `/database`. По факту решена через таб `api-log` в `SearchPage.tsx`
(`type Tab = 'results' | 'api-log'`, переключатель в шапке секции результатов).
Zustand-store `useSearchStore` (`store/search.ts`) пишет `apiLogs: ApiLog[]`
по ходу SSE-стрима поиска — виден список запросов с тайминами и raw-фреймами
для каждого магазина.

**Почему не как в roadmap'е:** изначально планировался persistent `<SearchLogDrawer>`
поверх endpoint'а `/api/db/searches`. В процессе WT-F5.x обнаружилось, что
api-log таб закрывает 90% повседневного сценария «помню что искал утром,
повтори/посмотри что вернулось». Persistent журнал из БД с фильтром по
магазину/тексту остаётся в бэклоге как `[WT-F8.1]` — заводим только если
возникнет конкретный кейс «недельный архив с поиском по тексту».

**Как пользоваться:**
- На `/` после запуска поиска переключи таб с «Результаты» на «API log» —
  увидишь все SSE-события текущей сессии.
- Полный персистентный журнал (между сессиями) — по-прежнему на `/database`
  → вкладка «Журнал» (endpoint `/api/db/searches`), сценарий «архив».

**Затронутые файлы:**
- `services/web-test/frontend/src/pages/SearchPage.tsx` — таб `api-log`.
- `services/web-test/frontend/src/store/search.ts` — `apiLogs` в Zustand store.
- `services/web-test/frontend/src/types/api.ts` — тип `ApiLog`.

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
