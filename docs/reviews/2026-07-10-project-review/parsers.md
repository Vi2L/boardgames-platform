# Ревью services/parsers — 2026-07-10

Отчёт review-агента.

## 1. Баги и криво реализованное

### 1.1. `/search` возвращает 503 при легитимном пустом результате — **critical**
`services/parsers/parsers/service.py:187-194`. Ветка
`elif not products: raise RuntimeError("Все магазины вернули ошибку и кеша нет...")`
срабатывает и когда **все парсеры успешно отработали, но ничего не нашли**
(`errors == {}`). После введения strict-фильтров («лучше пусто, чем мусор»
у WB/Avito/Ozon) пустая выдача — штатный случай, но пользователь получает
503 с текстом про «ошибки», а в `request_log` пишется вводящий в
заблуждение `source="partial-cache"`. Тестов на этот путь нет.
Должно быть: 200 + пустой список.

### 1.2. Сохранённые товары могут «пропасть» из ответа + вечный re-parse — **major**
`services/parsers/parsers/db.py:249` (`WHERE p.normalized_title LIKE '%query%'`)
и `db.py:267-292` (`get_fresh_store_slugs`). Кеш читается назад
substring-матчем по title. Если магазин вернул товары, чьи заголовки
**не содержат** строку запроса буквально (Avito матчит по описанию; запрос
латиницей «carcassonne» против русских тайтлов), товары сохраняются в БД, но:
(а) не попадают в ответ `/search` (в пределе — ложный 503 из п.1.1),
(б) магазин никогда не считается «fresh» → **парсится заново на каждый
запрос**, TTL-кеш не работает. Туда же: negative-результаты не кешируются
вовсе — запрос, по которому у Avito пусто, дёргает Avito каждый раз.

### 1.3. SQLite без WAL, без busy_timeout, соединение на каждую операцию — **major**
`services/parsers/parsers/db.py:134-143` и весь класс: каждый метод делает
`aiosqlite.connect(self._path)`. Нет `PRAGMA journal_mode=WAL`,
`busy_timeout`, `foreign_keys`. При параллельной записи (fire-and-forget
`log_parser`/`log_request` из `service.py:143,150,198` + цикл
`upsert_product` + DLQ + snapshots по 1MB BLOB при `ENABLE_RAW_SNAPSHOTS=1`)
writer блокирует writer в режиме journal=DELETE — риск `database is locked`
после 5с дефолтного таймаута. Плюс `upsert_product` в цикле
(`service.py:155-157`) — N соединений и N коммитов на батч вместо одной
транзакции.

### 1.4. Ozon `_PRICE_RE` содержит `\s` — баг, уже исправленный в клоне, но не бэкпортирован — **major**
`services/parsers/parsers/stores/ozon.py:171`:
`r'([\d\s\xa0]{1,10})\s*₽'`. В `onlinetrade.py:174-182` в докстринге прямо
написано, почему `\s` внутри числа опасен: regex прыгает через `\n`/`\t` и
склеивает числа из соседних HTML-строк → ложная цена. Fix сделали в
OnlineTrade (парсер отключён!), а в живом Ozon-парсере — нет. Классическая
цена дублированного кода.

### 1.5. Таймаут `PriceService` отменяет парсер раньше, чем breaker запишет failure — **major**
`services/parsers/parsers/service.py:110-121` (`wait_for` 25с) против
`ozon.py:70-71` (fetch 60с + selector 45с). При зависании browser-service
`asyncio.wait_for` кидает `CancelledError` внутрь `search()`; это
`BaseException`, ветки `except Exception` в `ozon.py:126-128` его не ловят
→ `breaker.record_failure()` **никогда не вызывается для таймаутов**.
Основной сценарий, ради которого Ozon-breaker вводили («antibot может
зависнуть на минуты» — `ozon.py:98-99`), breaker не открывает: каждый
запрос честно висит 25с. Failure надо записывать в `_run_one` на
`TimeoutError`, либо согласовать таймауты.

### 1.6. Race на shared-состоянии парсеров — **minor**
Экземпляры парсеров — синглтоны процесса (`api.py:106-122`), но
`self._http_counter` и `self.last_metrics` — mutable state
(`base.py:135-140`), сбрасываемый в начале каждого `search()`. Два
конкурентных `/search` (или `/search` + `/api/debug/parse`) по одному
магазину портят метрики друг друга; `service.py:130` читает `last_metrics`
уже после `gather` — может прочитать метрики чужого запроса. Данные
(products) не задеты, только аналитика.

### 1.7. Fire-and-forget `create_task` без хранения ссылки — **minor**
`service.py:88,143,150,165,177,187,198`. Ссылки на таски не сохраняются
(риск GC по документации asyncio), исключения внутри становятся «Task
exception was never retrieved», при shutdown незавершённые записи логов
теряются. Особенно `publish()`: если `IngestRequest`-валидация упадёт
(`catalog_publisher.py:85-89`), исключение вылетит **до** `_send` →
payload не попадёт в DLQ и потеряется молча.

### 1.8. GaGa: `query.encode("cp1251")` без обработки ошибок — **minor**
`services/parsers/parsers/stores/gaga.py:77`. Запрос с символом вне cp1251
(эмодзи, «™») даёт `UnicodeEncodeError` → падение всего парсера. Нужен
`errors="replace"` или предварительная фильтрация.

### 1.9. LIKE-wildcards в пользовательском запросе не экранируются — **minor**
`db.py:234,275`, `db.py:439`, `db.py:1179`: `f"%{query.lower()}%"` — `%` и
`_` в query трактуются как маски. Не инъекция, но `DELETE /api/cache?q=%`
тихо чистит всё (обходя `confirm=true`), поиск «100%_оригинал» матчит лишнее.

### 1.10. `BrowserClient` timeout 45с противоречит собственному комментарию и payload'у — **minor**
`browser_client.py:32-39`: комментарий «timeout с запасом над максимальным
timeout_ms=120с», а фактически `timeout=45.0`. Ozon передаёт
`timeout_ms=60_000` + selector 45с — httpx-клиент оборвёт соединение
раньше, чем browser-service закончит работу.

### 1.11. HobbyGames: regex карточки зависит от порядка атрибутов — **minor**
`hobbygames.py:202`: `data-product_id="(\d+)"\s+data-price="(\d+)"` — при
смене порядка атрибутов/вёрстки тихо деградирует на JSON-LD цену **без
скидки** (fallback есть, но скидочные цены пропадут незаметно; сигнала
«карточки перестали матчиться» нет).

### 1.12. Мелочи
- `breaker.py:110-111`: `opens_until_iso` в состоянии `half_open`
  возвращает время в прошлом — путает UI.
- `wildberries.py:163` / `avito.py:102`: `_http_counter = 1` захардкожен —
  retry-попытки не считаются в метриках.
- `db.py:139-142`: миграции глотают **все** исключения
  (`except Exception: pass`) — реальная ошибка (диск, повреждённая БД)
  неотличима от «колонка уже есть».
- `db.py:192`: `image_url=excluded.image_url` перетирается NULL'ом, тогда
  как остальные опциональные поля защищены COALESCE — непоследовательно
  (CLAUDE.md декларирует COALESCE-политику).

## 2. Мёртвый / лишний код

- **`DEPRECATED/chrome-extension/` (28K) — просрочен**: целевая дата
  удаления 2026-06-15 (roadmap PRS-4, перенос с 2026-05-28), сегодня
  2026-07-10. Надо перепроверить 14-дневный success-ratio Avito и удалить
  (вместе с tombstone-endpoint `POST /api/avito/cookies` →
  `api.py:385-403`).
- **`stores/onlinetrade.py` (376 строк) + `tests/test_onlinetrade_parser.py`
  (324 строки)** — парсер отключён (незакоммиченный diff в `api.py`), но
  модуль по-прежнему импортируется в `stores/__init__.py:6` и тестируется.
  Осознанное решение «оставить для возврата», но тогда: diff надо
  закоммитить, а в `stores/__init__.py` — пометить/убрать, иначе это
  выглядит как живой код. — minor
- **`db.py:1047 prune_snapshots()` — ни разу не вызывается** (единственное
  вхождение — определение). Метод retention написан, но не подключён ни к
  endpoint'у, ни к фоновой задаче. — major (см. п.4.3)
- **`beautifulsoup4` в зависимостях не используется** (`pyproject.toml:12-13`,
  комментарий «фолбэк для avito» устарел — grep по `bs4|BeautifulSoup`
  находит только фразу «зачем regex, а не BeautifulSoup» в комментарии).
  `playwright` extra тоже не используется сервисом (браузер вынесен в
  отдельный browser-service). — minor
- `api.py:511`: повторный `from .stores.wildberries import WildberriesParser`
  внутри функции при живом module-level импорте — шум.

### Дублирование между stores/*.py (просится в базовый класс) — **major (техдолг)**
- `hobbygames.py:60-108`, `lavkaigr.py:65-113`, `gaga.py:73-123` — три
  побайтово почти идентичных `search()`: сброс метрик → recorder → client →
  поиск → `gather(_enrich)` → `zip/replace` → `ParserMetrics`. ~150 строк,
  template-method в `StoreParser` (`base.py`) сократил бы каждый парсер до
  «распарси страницу поиска + распарси карточку».
- `ozon.py:193-343` и `onlinetrade.py:211-376` — клонированные
  `_parse_cards`/`_title_from_slug`/`_build_raw`/`warmup_interval_seconds`/
  `warmup_once` (~150 строк дубля); именно из-за клона возник баг 1.4.
- `_HEADERS` с одним и тем же UA Chrome 124 повторён в 4 файлах;
  `og:image`-regex в 3 `_enrich`.
- Мелкий обман в докстринге: `crowdgames.py:6` «качаем все страницы
  параллельно» — фактически строго последовательно (`crowdgames.py:82-91`).

## 3. Архитектура: контракт ParsedProduct и категории

**PRS-8 подтверждаю** — category-фильтр действительно неоднороден и живёт
в 4 разных местах разными механизмами:
- WB — локальный фильтр `subjectId == 120` (`wildberries.py:48,300`);
- Avito — локальный whitelist `microCategoryId ∈ {2301995,2301997,2301999}`
  (`avito.py:52,194-196`);
- Ozon — категория зашита в URL (`ozon.py:64,110`);
- OnlineTrade — раздел в URL (`onlinetrade.py:105`);
- HobbyGames/Lavka/GaGa/CrowdGames — guard'ов нет вовсе;
- а `category="boardgames"` проставляется **не парсерами, а publisher'ом**
  литералом (`catalog_publisher.py:144`) — `ParsedProduct`
  (`models.py:14-30`) поля `category` вообще не имеет.

Прочая неоднородность контракта:
- **in_stock**: HobbyGames кладёт `raw["availability"]` (bool),
  CrowdGames/WB/Avito/Ozon — `raw["in_stock"]`; publisher вынужден
  перебирать оба ключа (`catalog_publisher.py:117-121`). Просится единое
  поле в `ParsedProduct`.
- **image_url**: WB намеренно `None` (`wildberries.py:319`), Avito кладёт
  максимальное разрешение в `image_url` (а не `image_url_hd`), классические
  магазины разносят thumbnail/HD. Для потребителя поле означает разное.
- **enrich**: у 3 магазинов есть, у 4 нет — это ок, но следствие:
  `description/players/age_min` систематически NULL у маркетплейсов (видно
  в field-coverage), и matching в catalog получает разнокачественные офферы.
- **Цена**: Ozon кладёт в `price` цену «с Ozon-картой», остальные —
  обычную полку (`ozon.py:229-234`). Для сравнения цен между магазинами это
  систематическое смещение Ozon вниз; как минимум стоит зафиксировать в
  контракте/README.

## 4. Надёжность

### 4.1. Circuit breaker (`utils/breaker.py`) — реализация в целом корректна
Sliding window, min_samples, half-open с lazy probe, тесты через
monkeypatch `time.monotonic` (`tests/test_breaker.py`) — хорошо. Замечания:
half-open допускает неограниченное число параллельных probe
(задокументировано, приемлемо); `opens_until_iso` даёт прошлое время в
half_open (п.1.12); главная проблема — таймаут-кейс не долетает до
breaker'а (п.1.5). Также breaker покрывает только wb/ozon/avito —
hobby/lavka/gaga/crowd без защиты (для них приемлемо).

### 4.2. Падение catalog_publisher — данные в основном не теряются (DLQ есть), но:
- потеря возможна при ошибке валидации `IngestRequest` до `_send` (п.1.7);
- `dlq_save` сам может упасть (SQLite locked) — тогда payload потерян,
  только error-лог (`catalog_publisher.py:176-177`);
- **replay только ручной** — нет фонового retry (заведено как PRS-1),
  DLQ без cap'а по размеру/возрасту;
- **DLQ не покрыт тестами вообще**: в `tests/` нет ни одного вхождения
  «dlq» — ни `dlq_save/dlq_list/replay`, ни endpoints `api.py:334-382`.
  Для единственного механизма гарантии доставки это пробел. — major

### 4.3. Рост БД без retention — **major**
`request_log`, `parser_log`, `price_observations`, `catalog_dlq` не
чистятся никогда; `parser_snapshot` имеет написанный, но не подключённый
`prune_snapshots` (`db.py:1047`). При включённых snapshots (до 1MB на
HTTP-ответ, каждый ответ каждого парсера) SQLite-файл раздувается быстро;
`/api/db/meta` покажет размер, но никто не удалит. Нужен фоновый
janitor-task в lifespan (раз в сутки: prune snapshots 72h, логи 30-90d) —
дешёво и закрывает вопрос.

### 4.4. Отсутствие auth на мутирующих endpoint'ах
`DELETE /api/cache` (wipe с `confirm=true`), `DELETE /api/db/observations/{id}`,
DLQ-операции — без auth (задокументировано в CLAUDE.md:277 как «закрыть в
проде reverse-proxy»). Пока сервис внутренний — ок, но
`DELETE /api/cache?q=%` (п.1.9) усиливает риск. — minor

## 5. Тесты

**Хорошо**: 14 файлов, ~2700 строк; WB покрыт образцово (strict-фильтр, обе
схемы цены, retry-429 с проверкой backoff-задержек через monkeypatch —
`test_wildberries_parser.py:228-289`); breaker — через фейковое время;
Ozon/Avito — маппинг и edge-cases; HobbyGames/Lavka/GaGa — парсинг+enrich в
`test_service.py`; инварианты Live Test (`test_debug_parse.py` — не пишет в
products/request_log, `is_test=1`).

**Пробелы**:
- **CrowdGames — ноль тестов** (grep «crowdgames» по tests/ пуст):
  пагинация `_next_page`, price-fallback, `in_stock` по CSS-классам — всё
  не покрыто. — major
- **DLQ — ноль тестов** (см. 4.2). — major
- **Нет фикстур с реальными ответами магазинов**: весь HTML синтезируется в
  тестах под ожидания regex'ов (`test_service.py:168,319,484`). Тесты
  проверяют «regex матчит то, что мы сами написали», а не реальную
  вёрстку — drift сайта не ловится (для OnlineTrade это прямо признано в
  `onlinetrade.py:43-45`). Стоит завести `tests/fixtures/*.html` со
  слепками реальных страниц. — major
- Нет теста на «все парсеры успешны, но 0 результатов» — поэтому баг 1.1
  не пойман.
- 324 строки тестов на отключённый OnlineTrade — тратят CI-время на код,
  который не исполняется в проде.

## 6. Идеи функциональности (из логики кода)

1. **Janitor-task в lifespan**: `prune_snapshots(72)` + retention логов +
   авто-replay DLQ с exp-backoff (закрывает 4.2/4.3 и PRS-1 одним
   background-циклом по образцу ozon warmup).
2. **Negative-cache**: писать в `parser_log`-подобную таблицу факт «store X,
   query Q, 0 результатов, ts» и учитывать его в `get_fresh_store_slugs` —
   убирает вечный re-parse (п.1.2) и снижает нагрузку на Avito/WB (меньше
   429 → реже открывается breaker).
3. **Реализовать PRS-8** (поле `category` в `ParsedProduct` +
   `fixed_category` в `StoreParser`) — дизайн в roadmap уже хороший,
   заодно унифицировать `in_stock`.
4. **Базовый template-method для HTTP-парсеров**
   (`search_page → parse → enrich`) — сократит 3 магазина на ~150 строк и
   предотвратит расхождения типа п.1.4.
5. **`Retry-After` и per-host rate-limit**: WB backoff не читает
   `Retry-After` header; примитивный token-bucket per-store сгладил бы
   burst'ы от параллельных запросов сильнее, чем jitter.

## Главные выводы

1. **Самый заметный user-facing баг — 503 на пустой выдаче**
   (`service.py:187-194`): после перехода на strict-фильтры «пусто» стало
   нормой, а сервис трактует его как аварию. Фикс на пару строк + тест.
2. **Кеш-слой концептуально хрупкий**: read-back через `LIKE '%query%'`
   теряет сохранённые товары и ломает TTL-детекцию свежести (вечный
   re-parse), negative-результаты не кешируются. Это же — главный источник
   лишней нагрузки на защищённые источники.
3. **SQLite эксплуатируется неоптимально и небезопасно для конкуренции**:
   нет WAL/busy_timeout, соединение на операцию, фоновые записи конкурируют
   с батчевыми upsert'ами; retention не подключён (включая написанный, но
   мёртвый `prune_snapshots`).
4. **Дублирование между парсерами уже приносит реальные баги**:
   исправленный в OnlineTrade `_PRICE_RE`-дефект живёт в Ozon
   (`ozon.py:171`); тройной клон `search()` у HTTP-магазинов и двойной клон
   SSR-парсера просятся в базовый класс. PRS-8 (единый category-контракт)
   подтверждён и спроектирован — стоит выполнить.
5. **Гигиена репо**: DEPRECATED/chrome-extension просрочен к удалению
   (дедлайн 2026-06-15), diff отключения OnlineTrade не закоммичен,
   `beautifulsoup4` — мёртвая зависимость, DLQ и CrowdGames без тестов,
   HTML-фикстуры синтетические — тесты не ловят drift реальной вёрстки.
