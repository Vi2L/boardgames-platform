# CLAUDE.md (frontend)

Локальный конфиг Claude Code для **только** фронтенда `web-test`. Если ты
запустил `claude` именно из этой папки — это твоя cwd, и ниже описано,
что тебе можно, что нельзя, и где искать источники правды.

## Кто ты сейчас

Frontend-агент в split-режиме «backend + frontend» (см.
[`docs/parallel-agents.md`](../../../docs/parallel-agents.md) §5,
вариант C). Параллельная backend-сессия живёт в корне монорепо;
ваши папки сессий Claude Code разные (encoded-cwd) — друг друга
не перетрёте.

## Границы (важнее всего)

- **Не трогай Python-код выше** этой папки. Всё, что в
  `services/web-test/app/`, `services/catalog/`, `services/parsers/`,
  `packages/shared-py/` — зона backend-агента.
- **Не правь** корневой `pyproject.toml`, `docker-compose.yml`,
  `services/*/pyproject.toml`, alembic-миграции — то же самое.
- Если контракт API изменился (новые поля в response, новый endpoint) —
  попроси backend-агента в общем чате это сделать; ты потом подцепишь
  типы в `src/lib/api.ts`. Frontend никогда не правит endpoint первым.

Что внутри этой папки — твоё:
- `src/**`, `index.html`, `package.json`, `tailwind.config.ts`,
  `tsconfig.json`, `vite.config.ts`, `postcss.config.js`.
- `dist/` — build-артефакт, в индекс не попадает (gitignored).

## Команды

```bash
npm install          # один раз после клонирования / смены деп
npm run dev          # http://localhost:5173, прокси /api → :8000
npx tsc --noEmit     # type-check без билда
npm run build        # tsc + vite build → dist/, отдаётся FastAPI как статика
npm run preview      # запустить уже собранный dist/
```

Backend (`uvicorn`) должен быть поднят на `:8000` отдельно — иначе
Vite-прокси `/api` будет 502'ить. Источник правды по командам бэка —
`../CLAUDE.md` («Backend» секция).

## Архитектура `src/`

```
src/
├── App.tsx              layout: collapsible sidebar + 7 routes
├── main.tsx             entry, ReactQueryClient, Router
├── index.css            Tailwind base + кастомные классы
├── pages/               одна страница на роут (SearchPage, CatalogPage, …)
├── components/          по доменам: parsers/, catalog/, search/,
│                          database/, testing/, shared/
├── store/               Zustand: search.ts (SSE-state), loyalty.ts
├── lib/                 api.ts (~80 fetch-обёрток), catalog.ts (типы +
│                          мутации), sse.ts (useSSE hook), stores.ts
│                          (STORE_LABELS), similarity.ts, offer.ts,
│                          loyalty.ts (applyLoyalty)
└── types/               typed-only (api.ts, ...)
```

Полная схема страниц/компонентов — в `../CLAUDE.md` секция
«Architecture». Не дублирую здесь, чтобы при изменениях источник
правды был один.

## Паттерны

- **Страница** в `pages/<Domain>Page.tsx`, локальные компоненты — в
  `components/<domain>/`. `shared/` — кросс-доменные (CommandPalette,
  HealthBadge, JsonViewer, PriceChart, Skeleton).
- **State**:
  - **Server state** → TanStack Query 5. Мутации обязаны
    `invalidateQueries` всех затронутых ключей в onSuccess.
  - **UI state** → Zustand 4. Persist v2 в `store/search.ts`,
    persist в `store/loyalty.ts`.
- **Cache keys** (источник правды — `lib/api.ts`):
  `['catalog', ...]` / `['parsers', ...]` / `['parsers-db', ...]`
  / `['debug', ...]` / `['dlq']` / `['health-all']`. Не выдумывай
  свои — найди существующий префикс и добавляй сегмент.
- **SSE** через `lib/sse.ts:useSSE(url, handler)`. Используется для
  поиска и suite-run.
- **Polling** через `refetchInterval` с auto-stop по статусу — для
  job-based операций (Import Wizard).
- **toast** через `sonner` для успехов/ошибок мутаций.
  `window.confirm` для destructive (delete observation, merge
  games, replay-all DLQ).
- **Таблица + drawer/details** — основной UX. `ProductDrawer`,
  `GameDetailDrawer`. Inline-формы для CRUD (`AliasEditor`,
  `GameEditor`).

## Help-контент (WT-F13)

### Палитра механизмов — какой инструмент когда применять

| Механизм | Файл | Когда использовать |
|---|---|---|
| **InfoTip** | `components/matching/InfoTip.tsx` | 1-строчное plain-string пояснение к метрике / лейблу. CSS-only hover-bubble, max 280px, без JSX. Не закрывается кликом — пишет аналог `title=""`. |
| **Tooltip** (Radix) | `components/ui/Tooltip.tsx` | Короткий JSX-тултип к action-кнопке (хоткей, статус). Hover, 300ms delay. Не для понятий — для action-подсказок. |
| **HelpBox** | `components/shared/HelpBox.tsx` | Объяснение понятия 2-6 предложений JSX, click-open popover. Поддерживает `<code>`, `<a>`, `<ul>`. Основной механизм контекстной справки. |
| **HowItWorks** | `components/matching/HowItWorks.tsx` | Collapsible `<details>`-блок в шапке таба. Объясняет всю подсистему целиком (T0..T4, skipped flow). |
| **MatchingHelpTab** | `components/matching/MatchingHelpTab.tsx` | Full inline-doc tab с anchor navigation. Длинный prose для одного домена. |
| **help.html** | `public/help.html` | Standalone справочник — print, sharing, offline. Открывается в новой вкладке. |

Не путать с `<Popover>` (`components/ui/Popover.tsx`) — это базовый
Radix-обёртка, на которой построен HelpBox. Использовать `Popover`
напрямую — только если HelpBox с типизированным словарём не подходит.

### Когда добавлять новый help-топик

**При любом изменении в web-test, которое вводит или меняет:**
- Новый scheduler-job, runtime-flag, breaker, threshold или порог.
- Новый статус / bucket / tier в матчинге / каталоге.
- Новую колонку с неочевидным значением (поле БД, метрика).
- Новый параметр в form / cron-job, который оператор может править.
- Новый action-кнопку с неочевидными последствиями (replay, revert,
  invalidate, merge).

Жаргон проекта — `T0/T1/T2/T3`, `match_status`, `skipped_reason`,
`breaker`, `DLQ`, `auto_t1`, `tier`, `bge-m3`, `qwen2.5`, `pg_trgm` —
**требует HelpBox**, если впервые встречается на новой странице или
без объяснений в контексте.

### Чек-лист «добавить help-топик»

1. Открыть `src/lib/help-topics.tsx`.
2. Добавить запись в `HELP_TOPICS` через `defineTopics`:
   ```tsx
   'domain.concept_name': {
     title: 'Краткий заголовок',
     body: (
       <>Объяснение 2-6 предложений. Допустим <code>code</code>, <strong>strong</strong>, ссылки.</>
     ),
     learnMore: { label: 'Подробнее в roadmap', href: '...' },  // опционально
   },
   ```
3. Тип `TopicId` обновится автоматически — не нужно ничего править вручную.
4. Импортировать HelpBox в нужный компонент и вставить рядом с концептом:
   ```tsx
   import { HelpBox } from '../shared/HelpBox'
   ...
   <span className="inline-flex items-center gap-1.5">
     T1 порог
     <HelpBox topic="matching.tier_t1" />
   </span>
   ```
5. Запустить `npx tsc --noEmit` — несуществующий topic = ошибка
   компиляции на месте вызова.

### Конвенция именования topic_id

`<domain>.<concept_name_in_snake_case>` — где `domain` совпадает с
сайдбар-разделом или ключом cache:
- `matching.*` — `/matching` ControlTab, QueuePanel, JournalTab
- `catalog.*` — `/catalog` (Каталог + Очередь матчинга)
- `bgg_sync.*` — `/bgg-sync` (scheduler-job'ы и их параметры)
- `debug.*` — `/debug` (Live Test, Контракт, snapshots)
- `dlq.*` — `/dlq`
- `search.*` / `database.*` / `testing.*` — для будущей раскатки

### Когда HelpBox **не нужен**

- Очевидные метрики (`elapsed`, `total`, `count`) — слово говорит за себя.
- Тривиальные кнопки (`Обновить`, `Закрыть`, `Сохранить`) — Tooltip или
  ничего.
- Поля формы с обычным смыслом (`Заголовок`, `Описание`) — placeholder
  и label достаточно.

### Когда HelpBox **обязателен** (по этому списку соблюдаем при PR-review)

- Появилась новая колонка в таблице со значением-аббревиатурой или
  жаргоном проекта.
- Введён новый scheduler-job — он должен попасть в `JOB_HELP_TOPICS`
  внутри `SchedulerHealth.tsx`.
- Введён новый bucket / tier / status / reason — добавить запись в
  словарь, врезать рядом с первой встречей лейбла.

## Контракты с backend

Web-test backend — тонкий proxy к `services/parsers` и
`services/catalog`. Frontend знает только про web-test API
(`/api/*`), никогда не дёргает соседей напрямую.

- **Типы для всех endpoints** — в `src/lib/api.ts` и
  `src/types/api.ts`. Расхождения с реальными ответами parsers
  однажды ломали `/database` чёрным экраном — см.
  «Подводные камни» в `../CLAUDE.md` («Имена полей parsers ↔
  frontend»). Если тип не сходится с runtime-данными — правь
  тип, не данные.
- **Catalog-специфичные мутации** в `src/lib/catalog.ts`.
- **STORE_LABELS** (имена и цвета магазинов) — в
  `src/lib/stores.ts`. Single source of truth, не дублируй.

## Подводные камни (frontend-only)

- **Cache key consistency**: после мутации в одном домене часто
  нужно invalidate несколько ключей. Например, `linkOffer`
  инвалидирует `['catalog','matching-queue']` И
  `['catalog','matching-stats']` — иначе dashboard висит со
  старыми числами.
- **Snapshot diff**: `extra` разбивается на `extra.<key>` уже на
  бэкенде (`app/diff.py`). Тест в `app/` фронт не трогает.
- **Popover'ы и overflow-hidden**: `ui/Popover.tsx` (и `Tooltip`, и
  `HelpBox` поверх него) рендерится через Radix Portal в `document.body`,
  поэтому `overflow-hidden`/`overflow-clip` родителя не обрезает контент.
  Если делаешь свой кастомный popover — используй `ui/Popover` или
  Radix Portal напрямую, а не `position: absolute` внутри dom-родителя
  (раньше `HealthBadge` ломался в свёрнутом sidebar именно из-за этого).
- **`extra.on_sale` / `extra.original_price`** ставит парсер
  HobbyGames при акционной цене (`original_price` в **копейках**).
  Используется на `/search` для бейджа «sale» и блокировки
  HG-бонусов в loyalty (бонусами оплачивается только товар без
  акции).
- **`isInStock(p)`** (`lib/offer.ts`): `extra.availability` для
  HG, `extra.in_stock` для CrowdGames; для Лавки/GaGa →
  `true` (нет признака → считаем «в наличии»).
- **Цены**: `/search` отдаёт `price_rub` (рубли, float),
  `/history` — `price` (копейки, int). Конвертация — на стороне
  фронта.
- **Tailwind**: `tailwind.config.ts` сканирует `src/**/*.{ts,tsx}`.
  Динамические классы (`bg-${color}-500`) Tailwind не видит —
  используй полные имена либо `tailwind.config.ts.safelist`.

## Не делать

- Не править `package.json` без явного запроса (новые зависимости
  обсуждаются — у backend-агента может быть мнение).
- Не трогать `dist/` руками — это билд-артефакт.
- Не делать prefetch при загрузке приложения «на всякий случай» —
  TanStack Query lazy-fetch'ит сам, лишний трафик никому не нужен.
- Не push в remote без явного разрешения пользователя.
