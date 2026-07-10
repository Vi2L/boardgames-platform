# Ревью проекта — 2026-07-10

Полное ревью монорепо, выполненное Claude (4 параллельных агента + ручная
верификация критичных находок). Детальные отчёты:

- [catalog.md](catalog.md) — сервис catalog (matching, импортёры, scheduler)
- [parsers.md](parsers.md) — сервис parsers (магазины, кеш, DLQ, breaker)
- [web-test.md](web-test.md) — backend-прокси + React frontend
- [infra.md](infra.md) — docker-compose, uv workspace, bin/, документация, git

**Статус находок:** пункты раздела «Критичное» проверены вручную по коду
(file:line подтверждены). Остальное — выводы агентов, перед фиксом
перепроверять по указанным строкам.

---

## Общая оценка

База у проекта крепкая — чистая git-история, продуманные compose-профили,
хорошая документация-как-код (CLAUDE.md, roadmap, devlog), образцовые тесты
местами (WB-парсер, breaker, T0/T1). Но с конца мая накопился заметный дрейф:
4 подтверждённых сломанных флоу, системный баг в ключе matching-кэша,
просроченные чекпоинты roadmap и незакоммиченная правка, висящая ~6 недель.

---

## 🔴 Критичное — реально сломано (проверено вручную)

### 1. Catalog: T0-кэш пишется и читается по разным ключам

ML-кэширование фактически не работает.
Чтение: `engine.py` считает ключ как `normalize_title(pipeline.process(title_raw))` —
после среза префиксов издателя и «настольная игра»
(`catalog/matching/v2/engine.py:82-86`). Запись: везде
`normalize_title(product.title)` — **без** pipeline (`routers/ingest.py:267,321`,
`matching/v2/worker.py:269,326`, `routers/matching.py:240,297,631`).

Для любого title, который pipeline меняет (а это как раз маркетплейсы —
основной поток T2/T3): кэш никогда не хиттится, LLM пересматривает один и тот
же товар при каждом ingest, negative-кэш «не настолка» не работает,
сматченные офферы флапают auto→unmatched→auto.

**Фикс:** engine возвращает вычисленный `title_norm` в `MatchResult`,
все записи используют его.

### 2. web-test: редактирование scheduler-job'ов на /bgg-sync сломано всегда

В `app/catalog_client.py` метод `reschedule_job` определён **дважды**
(`:325` и `:709`) — в Python побеждает второе, kw-only определение,
а `app/api/bgg_sync.py:48` вызывает его позиционно → гарантированный
`TypeError` → 500. Задублированы также `trigger_scheduler_job` и
`list_scheduler_jobs`. Судя по всему — артефакт merge.

**Фикс:** удалить первый блок определений, вызов в `bgg_sync.py` перевести
на kwargs.

### 3. Docker: БД портала web-test живёт вне volume

Код читает `PORTAL_DB_PATH` (`app/db_local.py:922`), а compose передаёт
`DB_PATH: /data/portal.sqlite` (`docker-compose.yml:141`), Dockerfile —
вообще `DB_PATH=data/debug.sqlite`. Обе настройки мертвы: SQLite пишется в
`/app/data/portal.sqlite` внутри контейнера, volume `portal-data` пустой.
Любой `--force-recreate` молча стирает историю поисков.

**Фикс:** одна строка в compose (`PORTAL_DB_PATH: /data/portal.sqlite`).

### 4. Parsers: `/search` отдаёт 503 на легитимно пустую выдачу

`service.py:186-194` — ветка `elif not products:` кидает
`RuntimeError("Все магазины вернули ошибку...")` даже когда `errors == {}`
и все парсеры честно отработали. После введения strict-фильтров
(«лучше пусто, чем мусор») пустой результат — штатный случай.

**Фикс:** 200 + пустой список; тест на «все парсеры успешны, 0 результатов».

### 5. Инфра: защитные Claude-хуки не работают

`bin/block-env-edit.sh` и `bin/ruff-on-edit.sh` — без exec-бита, при этом
прописаны в `.claude/settings.json`. Плюс блокирующие хуки используют
`exit 1`, а PreToolUse блокирует только на `exit 2`. Защита `.env` и
авто-ruff фактически отключены; CI, который бы подстраховал, отсутствует.

### Также подтверждено

- `GET /admin/runtime-flags/bgg` в catalog недостижим — порядок регистрации
  роутов (`routers/runtime_flags.py:36` перехватывает `/bgg` как `{key}`).
- `scripts/reset_mismatched.py` падает на несуществующей колонке
  `match_log.created_at` (в таблице — `performed_at`).
- Один тест web-test падает на main (`tests/test_diff.py` не обновлён вслед
  за кодом `app/diff.py`).

---

## 🟠 Криво реализованное (major, сводка — детали в отчётах)

**Catalog** ([подробно](catalog.md)):
- Зависший `ImportJob(running)` навсегда блокирует scheduler — нет
  startup-recovery (есть только для `match_queue`); `create_task` без
  трекинга ×10; except без `session.rollback()`.
- `predicted_kind`/`kind_filter` (CAT-17.1) — мёртвая фича: значение не
  доходит от engine до worker.
- `reassess` может застрять в `pending_ml` навсегда (skip-путь воркера).
- `match_log` растёт вечно — progress-записи не подпадают под retention.
- `games/merge` не инвалидирует T0-кэш и теряет вектора алиасов.
- Race worker vs manual link (check-then-write без `FOR UPDATE`).
- Аудит фиктивен: `request.state.api_key_owner` нигде не присваивается.
- Нет индекса `offers.last_seen_at` — seq scan на каждый отчёт.
- T2/T3/worker и scheduler — ноль тестов; `requires_db` молча скипает
  16/28 файлов.

**Parsers** ([подробно](parsers.md)):
- Кеш read-back через `LIKE '%query%'` теряет товары и ломает TTL-детекцию →
  вечный re-parse; negative-результаты не кешируются → лишние 429.
- SQLite без WAL/busy_timeout, соединение на операцию.
- `_PRICE_RE` с `\s` внутри числа: баг исправлен в отключённом OnlineTrade,
  но жив в Ozon (`stores/ozon.py:171`).
- Breaker не ловит таймауты: `wait_for(25с)` отменяет парсер раньше его
  таймаутов, `CancelledError` не доходит до `record_failure()`.
- DLQ без тестов; payload теряется при ошибке валидации до `_send`.
- `prune_snapshots()` написан, но не вызывается; retention логов нет.
- Тесты на синтетическом HTML — drift реальной вёрстки не ловится;
  CrowdGames — ноль тестов.

**web-test** ([подробно](web-test.md)):
- Прокси-слой: ~1900 строк boilerplate, 91 endpoint отдаёт 500 вместо 502
  при падении catalog — чинится одним глобальным exception handler.
- Auth отсутствует полностью (не только `/api/debug/*` как в WT-F6.1):
  wipe кеша, pg_dump, merge, kill-switch ML — без авторизации.
- 13 монолитов >500 строк (PromotionPanel 1153, GameDetailDrawer 1063).
- Polling-шторм на /matching: >100 запросов/мин при готовой SSE-инфре.
- Frontend без тестов и линтера (31K строк); `tsc --noEmit` при этом чистый.

**Инфра** ([подробно](infra.md)):
- Compose не пробрасывает половину переменных `.env.example` (весь
  ML/matching-блок catalog, WB/proxy-блок parsers) — правка `.env` в
  Docker-режиме молча ничего не меняет.
- parsers без healthcheck; `depends_on` без `condition: service_healthy`.
- Образы невоспроизводимы (`uv.lock` не используется в Docker).
- Все контейнеры под root; `node:20-alpine` — EOL.

---

## 🗑 Лишнее / мёртвый код

- `services/parsers/DEPRECATED/chrome-extension/` — дедлайн удаления
  (2026-06-15, PRS-4) просрочен; блокер (Avito L0 ≥95%) не перепроверен.
- `ParsersPage.tsx` + `ParserCard.tsx` — дедлайн 2026-06-10 (WT-F9.1)
  прошёл; с ними уходит orphan `GET /api/parsers/{slug}/run`.
- Legacy `MatchingSection` в `CatalogPage.tsx` (~440 строк) — дублирует
  `/matching`.
- Catalog: `MatchEngine.match_async` (расходящаяся копия T2→T3-оркестрации),
  `matcher.find_best_match`, `embedder.build_text`, `iter_enrich`,
  `_parse_release_date`+`MONTH_RU` (живы только за счёт тестов).
- Дублирование хуже roadmap: `_utcnow` ×9 (не 4), enrich-loop ×5 (не 3),
  own_client ×10 (не 6) — CAT-13/14/15 пора выполнять.
- Parsers: `beautifulsoup4` — мёртвая зависимость; 324 строки тестов на
  отключённый OnlineTrade.
- 7 orphan-endpoints в web-test без потребителя во frontend.
- Незакоммиченный diff отключения OnlineTrade висит с 2026-05-23.

---

## 📄 Документация разошлась с реальностью

- **`services/browser` — «сервис-призрак»**: живой участник compose и
  workspace (порт 8003, Camoufox), отсутствует в карте сервисов CLAUDE.md,
  README, `docs/architecture.md`; нет своего CLAUDE.md.
- roadmap не обновлялся с 2026-05-23: просроченные PRS-4 и WT-F9.1,
  ссылка на несуществующую ветку `feat/admin-panel-redesign`.
- CLAUDE.md web-test отстал (нет 4 роутеров, секция Design system неверна);
  `packages/README.md` пишет «пусто», хотя shared-py живёт.

---

## 💡 Функциональность, которую стоит добавить

1. **Price history API** — `offer_prices` write-only: данные копятся, никто
   не читает. `GET /games/{id}/price-history` (= roadmap CAT-19), UI-компонент
   `<PriceChart>` уже есть.
2. **Janitor-task в parsers** — один фоновый цикл: prune snapshots +
   retention логов + авто-replay DLQ с backoff. Закрывает INFRA-8, PRS-1 и
   мёртвый `prune_snapshots` разом.
3. **Инкрементальный embedding в catalog** — вектор при создании
   игры/алиаса или nightly-diff-job (сейчас — только ручной warmup).
4. **SSE-канал для /matching** вместо 10+ таймеров (инфра `lib/sse.ts` есть).
5. **Generic catalog-proxy в web-test** — `{path:path}` с allowlist убирает
   ~1900 строк и третье место синхронизации.
6. **Negative-cache в parsers** — «store X по query Q дал 0» → убирает
   вечный re-parse, снижает 429.
7. **Минимальный CI (INFRA-7)** — ruff + `bin/test-all.sh` +
   `docker compose config`. После падающего теста на main и нерабочих
   хуков — уже не «nice to have».

---

## План действий (по приоритету)

| # | Что | Усилие |
|---|---|---|
| 1 | Санитарный проход: закоммитить OnlineTrade-diff, `chmod +x` хукам + `exit 2`, `PORTAL_DB_PATH` в compose, healthcheck parsers | ~час |
| 2 | Catalog C1: `title_norm` в `MatchResult` + все записи через него | полдня |
| 3 | web-test: дубли в `catalog_client.py` + глобальный handler `httpx.TransportError` + падающий тест | ~час |
| 4 | Parsers: 503-на-пусто + backport `_PRICE_RE` в Ozon + WAL/busy_timeout | полдня |
| 5 | Compose: пробросить недостающие env (или пометить «host-only») | ~час |
| 6 | Уборка мёртвого кода + актуализация roadmap/CLAUDE.md + карта сервисов с browser | полдня |
| 7 | Catalog: recovery для ImportJob + rollback в except + retention match_log | день |
| 8 | Тесты на worker/T2/T3 и DLQ; минимальный CI | 1–2 дня |

---

## Уроки (паттерны, стоящие за находками)

1. **Асимметрия ключа кэша** (C1): любая трансформация ключа должна жить в
   одной функции, через которую проходят и запись, и чтение. Когда
   нормализация размазана по вызывающим сторонам, эволюция одной из них
   (добавление pipeline в CAT-17.2) молча ломает симметрию — кэш деградирует
   без единой ошибки в логах.
2. **Клонированный код расходится в момент багфикса** (`_PRICE_RE`): баг
   починили в одной копии (которую потом отключили!) и не в другой.
   Дублирование опасно не само по себе, а тем, что фиксы не реплицируются.
3. **Дедлайны в roadmap без внешнего триггера не срабатывают** (PRS-4,
   WT-F9.1): даты прошли, никто не заметил. Помогает либо CI-джоб,
   проверяющий просроченные даты, либо периодический «санитарный» проход.
