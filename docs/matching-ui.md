# Matching UI — Split-view + Unlink flow

**Дата:** 2026-05-09  
**Время:** ~16:00 MSK  
**Затронутые сервисы:** `catalog`, `web-test` (backend + frontend)

---

## Что сделано

### 1. Новый флаг `Offer.was_linked` (catalog, миграция 0008)

В таблицу `offers` добавлен булевый столбец `was_linked` (default `false`).  
Становится `true` когда оператор вручную отвязывает оффер от игры.  
Используется очередью матчинга для приоритизации таких офферов — они
всплывают в отдельную группу «Возвращены», чтобы оператор не потерял их
среди сотен других.

### 2. Endpoint `POST /matching/{offer_id}/unlink` (catalog)

Отвязывает оффер от игры и возвращает в очередь:
- `game_id → null`
- `match_status → "unmatched"`
- `was_linked → true`
- `match_score` сохраняется (помогает при повторном триаже)
- Алиас, добавленный при линковке, **не удаляется** — он улучшает
  будущий авто-матч других офферов с тем же `title_raw`

HTTP 409 если оффер не привязан (`match_status` ≠ `manual`/`auto`).

### 3. Split-view страница матчинга (web-test, вкладка «Матчинг»)

Вместо одной flat-таблицы — двухпанельный интерфейс:

```
┌───────────────────────┬──────────────────────────────────────┐
│  Store tabs           │  Детали выбранного оффера            │
│  Bucket filter        │  Поиск по каталогу (debounce 300ms)  │
│  ─────────────────    │  Список кандидатов (до 20)           │
│  ⚠ Возвращены (N)     │  score-бейдж · title · год · via    │
│  □ Оффер A            │  ─────────────────────────────────   │
│► □ Оффер B (выбран)   │  [Отклонить]  [Reassess ↻]          │
│  □ Оффер C            │                                      │
│  [Загрузить ещё]      │                                      │
│  [Отклонить N выбр.]  │                                      │
└───────────────────────┴──────────────────────────────────────┘
```

**Левая панель:**
- Store-табы (из `matching/stats`) — фильтруют очередь по магазину
- Bucket-фильтр (`good / candidate / cold`) — фильтрация на клиенте по score
- Группа «Возвращены» — офферы с `was_linked=true` всплывают первыми
- Чекбоксы → batch «Отклонить выбранные»
- Кнопка «Загрузить ещё» (шаг +50, не бесконечный скролл)
- «Reassess всё» — запускает `/matching/reassess-all` для текущего store-фильтра

**Правая панель (появляется при выборе оффера):**
- Метаданные оффера: title, store, цена, score, бейдж «был привязан»
- Поиск по каталогу с debounce 300ms и лимитом 20 кандидатов
- Кандидаты кликабельны → `POST /matching/{id}/link`
- Кнопки «Отклонить» и «Reassess ↻»

### 4. Исправление ошибочного матча (GameDetailDrawer → вкладка Offers)

Каждая строка оффера в drawer'е игры получила два новых действия:

| Кнопка | Семантика |
|--------|-----------|
| **⇄** (Переназначить) | Раскрывает inline-пикер прямо в строке; поиск с debounce 300ms; выбор кандидата вызывает `POST /matching/{id}/link` с новым game_id |
| **✕** (Отвязать) | `window.confirm` → `POST /matching/{id}/unlink` → оффер уходит обратно в очередь с `was_linked=true` |

---

## Как пользоваться

### Обычный триаж новых офферов

1. Открыть **Каталог → вкладка «Матчинг»**
2. Выбрать магазин в store-табах (или оставить «все»)
3. Кликнуть оффер слева — справа появятся кандидаты
4. Если кандидат верный — кликнуть его → оффер привязан, исчезает из очереди
5. Если кандидатов нет — нажать «Reassess ↻» (если недавно добавили алиасы/BGG)
   или «Отклонить» (спам, не игра)

### Исправление ошибочного матча

**Вариант A — через GameDetailDrawer:**
1. Найти игру в каталоге → открыть drawer → вкладка «Offers»
2. Найти неверный оффер → нажать **✕ (Отвязать)** → подтвердить
3. Оффер вернётся в очередь матчинга с пометкой «был привязан»
4. Зайти в «Матчинг» — оффер будет в группе «⚠ Возвращены» вверху списка
5. Выбрать его и связать с правильной игрой

**Вариант B — прямо в Offers tab:**
1. Найти неверный оффер → нажать **⇄ (Переназначить)**
2. В inline-пикере скорректировать поисковый запрос если нужно
3. Выбрать правильную игру из кандидатов

### Batch-отклонение

1. В левой панели очереди отметить чекбоксы у ненужных офферов
2. Нажать кнопку **«Отклонить N»** внизу панели → подтвердить
3. Все отмеченные офферы получают `match_status = rejected`

---

## Технические детали

### Измененные файлы

| Файл | Изменения |
|------|-----------|
| `services/catalog/catalog/models.py` | `Offer.was_linked: bool` |
| `services/catalog/catalog/schemas.py` | `OfferOut.was_linked: bool` |
| `services/catalog/catalog/routers/matching.py` | `POST /unlink`, параметр `was_linked` в `GET /queue`, сортировка `was_linked DESC` |
| `services/catalog/alembic/versions/20260509_0008_offer_was_linked.py` | Миграция: `ALTER TABLE offers ADD COLUMN was_linked BOOLEAN NOT NULL DEFAULT FALSE` |
| `services/web-test/app/catalog_client.py` | `unlink_offer()`, `was_linked` в `matching_queue()` |
| `services/web-test/app/api/catalog.py` | Proxy `POST /matching/{id}/unlink`, `was_linked` в `/matching/queue` |
| `services/web-test/frontend/src/lib/catalog.ts` | `CatalogOffer.was_linked`, `unlinkOffer()`, `wasLinked` в `fetchMatchingQueue()` |
| `services/web-test/frontend/src/components/catalog/GameDetailDrawer.tsx` | Кнопки ⇄/✕ в OfferRow, `InlineReassignPicker` |
| `services/web-test/frontend/src/pages/CatalogPage.tsx` | Split-view: `QueueOfferRow`, `MatchingOfferDetail`, `MatchingSection` |

### API

```
# Новый endpoint
POST /matching/{offer_id}/unlink
  → 200 OfferOut  (match_status=unmatched, was_linked=true)
  → 404           offer not found
  → 409           offer is not linked (status=unmatched/rejected)

# Расширенный endpoint
GET /matching/queue?store=&was_linked=&limit=&offset=
  → сортировка: was_linked DESC, match_score DESC NULLS LAST
```
