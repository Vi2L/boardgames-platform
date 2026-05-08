# Параллельная работа нескольких агентов Claude Code в `boardgames-platform`

> **Кому этот документ.** Junior-разработчику, который пришёл в проект и хочет одновременно вести две-три задачи в Claude Code, не сломав себе репо. Документ объясняет «как» (команды) и «почему» (что происходит под капотом).

---

## 0. TL;DR — если читать некогда

1. Запусти **две сессии Claude Code в разных папках одного клона**: одну в корне репо (для Python-бэкенда), вторую в `services/web-test/frontend/` (для React-фронта). Это **вариант C**, базовый режим. Setup за 5 минут.
2. Когда нужны две **разные** фичи параллельно — сделай **git worktree** для второй (вариант A).
3. **Никогда** не запускай два `claude` в одной и той же папке — поломаешь себе историю сессий.
4. **Никогда** не делай `alembic revision --autogenerate` параллельно из двух мест без согласования — упрёшься в two heads.
5. **Контракт `POST /ingest/offers`** правит только один агент за раз, одним атомарным коммитом — он живёт в двух сервисах сразу.

Дальше — подробно с пояснениями.

---

## 1. Контекст: зачем нужен этот план

**Проект.** Монорепо `boardgames-platform`: 3 backend-сервиса (catalog/parsers/web-test) + React-frontend в `services/web-test/frontend/`. См. `CLAUDE.md` в корне для общей карты.

**Ситуация.** Активная разработка идёт сразу в двух местах: backend catalog'а (BGG-парсер, источники, dicefest) и web-test (UI-страница для тех же фич). Если работать одной сессией — бутылочное горлышко. Если запустить две сессии без подготовки — сломаешь session-state, миграции и контракты.

**Цель.** Организовать **2–3 одновременных Claude Code-сессии** так, чтобы:
- они не перетирали друг другу историю чата;
- не ломали `.venv`/`node_modules`/docker-стек;
- не конфликтовали по миграциям и контрактам;
- ты понимал, **почему** каждое правило существует (и мог его адаптировать).

---

## 2. Глоссарий — что такое все эти слова

> **Зачем читать этот раздел.** Дальше будут понятия `worktree`, `cwd`, `subagent`, `session`, `uv workspace`. Если не уверен — посмотри сюда.

### `cwd` (current working directory)
Папка, **из которой запущен** процесс. Для shell — то, что показывает `pwd`. Для Claude Code — папка, из которой ты набрал команду `claude`. Важно потому, что Claude Code **запоминает сессии в папке, привязанной к этому пути** (см. ниже).

### Сессия Claude Code
Один разговор с Claude. Все сообщения, tool calls, изменения файлов — внутри одной сессии. Файл сессии лежит в `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. **`encoded-cwd` строится из абсолютного пути cwd.**

> Junior-объяснение: если ты запустил `claude` из `/Users/vitaliy/Projects/boardgames-platform`, твоя сессия живёт в `~/.claude/projects/-Users-vitaliy-Projects-boardgames-platform/`. Если запустил из `/Users/vitaliy/Projects/boardgames-platform/services/web-test/frontend`, сессия живёт в другой папке `~/.claude/projects/-Users-vitaliy-Projects-...-frontend/`. Это и есть «изоляция сессий по cwd».

### `git worktree`
Вторая (третья, четвёртая…) рабочая копия одного и того же репо, **на другой ветке**, в другой папке на диске. У всех worktrees общий `.git` (история, объекты), но разные файлы рабочей копии.

```
основной клон   → /Users/vitaliy/Projects/boardgames-platform   (ветка bgg-catalog-parser)
worktree А      → /Users/vitaliy/Projects/bg-feat-X             (ветка feat-X)
worktree B      → /Users/vitaliy/Projects/bg-review             (ветка PR-review)
```

> Junior-объяснение: вместо того, чтобы делать `git stash` и переключать ветки в одной папке, ты держишь две папки одновременно. Можешь править обе параллельно. Это как клон, но без полного копирования `.git`.

### `uv workspace`
В корне `pyproject.toml` объявляет workspace: список «членов» — `services/catalog`, `services/parsers`, `services/web-test`. Команда `uv sync --all-packages --group dev` создаёт **один общий `.venv` в корне**, в нём установлены все три сервиса как editable.

> Junior-объяснение: один Python virtual env на весь монорепо. Если поменял код в `services/catalog/` — он сразу виден из тестов, без переустановки.

### Subagent (Agent tool)
**Внутри** одной сессии Claude Code можно делегировать подзадачу под-агенту: исследование, ревью, написание плана. Subagent работает в своём контексте (не засоряет основной), возвращает текстовый отчёт.

> Junior-объяснение: это **не** «второй чат». Это «делегирование одной задачи внутри текущего чата». Параллельность есть, но она внутри одной сессии.

### Headless mode
Запуск Claude Code как обычной CLI-команды без интерактивного чата:

```bash
claude -p "проверь линт в services/catalog" --output-format json
```

Возвращает JSON-результат. Подходит для скриптов, batch-задач, CI.

### Hooks и `.claude/settings.json`
`.claude/settings.json` в репо — общий конфиг Claude Code для всех, кто работает в этом проекте. В нём — разрешённые Bash-команды (`allow`-список) и опциональные **hooks** — скрипты, которые запускаются автоматически на события (например, перед каждым tool call). Этот файл shared между сессиями: правка из одной сессии видна другой.

`.claude/settings.local.json` — локальные настройки (gitignored), у каждого разработчика свои.

### Alembic «head»
Каждая миграция БД — узел в графе. У графа должен быть **один последний узел (head)**. Если две ветки добавили миграцию с одним `down_revision` — голов становится две, БД не знает, какую применить. Ситуация называется **two heads** и обычно требует ручной починки.

### Контракт между сервисами
Не код, а **договор о форме данных** между двумя сервисами. У нас главный — `POST /ingest/offers` (parsers → catalog). Если parsers начнёт слать поле `discount_pct`, а catalog ещё не умеет — оба упадут или потеряют данные. Поэтому контракт нужно менять **синхронно**.

---

## 3. Как Claude Code устроен под капотом (мини-курс)

> **Зачем читать.** Чтобы понять, **почему** правила параллелизма именно такие.

### 3.1 Где живёт сессия

Файл сессии: `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`.

`encoded-cwd` строится **из абсолютного пути**, в котором ты запустил `claude`, заменой `/` на `-`. То есть:
- запуск из `/Users/vitaliy/Projects/boardgames-platform` → `~/.claude/projects/-Users-vitaliy-Projects-boardgames-platform/`
- запуск из `/Users/vitaliy/Projects/boardgames-platform/services/web-test/frontend` → `~/.claude/projects/-Users-vitaliy-Projects-boardgames-platform-services-web-test-frontend/`

**Следствие 1.** Разные cwd = разные папки сессий = **сессии не пересекаются**, не перетирают друг друга, `/resume` показывает только сессии своей cwd.

**Следствие 2.** Две сессии из **одной и той же** cwd → попадают в одну папку. Одна перезапишет файл другой. Поэтому **никогда не запускай два `claude` из одной папки**.

### 3.2 Как Claude Code работает с файлами

В Claude Code **нет блокировок на файлы**. Если сессия A пишет в `services/catalog/catalog/api.py` через Edit, и сессия B одновременно тоже пишет — последняя запись побеждает, первая теряется без предупреждения.

> Junior-объяснение: это значит, что параллельность работает на уровне **разных файлов** и **разных папок**. Если две сессии правят разные файлы — окей. Если один и тот же файл — кто последний, тот и прав.

### 3.3 `.claude/settings.json` shared

`.claude/settings.json` лежит в индексе git, его читают **все сессии в этом проекте**. Если ты добавил разрешение `Bash(rm -rf*)` в одной сессии — оно сразу действует и в другой. Поэтому правки `.claude/settings.json` — **отдельный согласованный коммит**, а не «по дороге».

### 3.4 Subagents — параллелизм внутри сессии

Когда делаешь `Agent(...)` — Claude поднимает **другого Claude** в отдельном контекстном окне с заданием. Возможны несколько одновременно (если запущены в одном tool-блоке). Это полезно для разведки/ревью, не для долгих интерактивных задач.

### 3.5 Headless и Agent SDK

`claude -p "..." --output-format json` — одиночный запуск. Несколько таких можно запустить параллельно через `&` в shell. Каждый — своя сессия (если не передан `--resume <id>`).

---

## 4. Карта проекта `boardgames-platform`

Уровень детализации, нужный, чтобы понимать «где конфликты, где безопасно».

### 4.1 Сервисы

```
boardgames-platform/
├── services/
│   ├── catalog/         FastAPI + Postgres (asyncpg) + Alembic   :8002
│   ├── parsers/         FastAPI + SQLite (aiosqlite)              :8001
│   └── web-test/        FastAPI + статика React                   :8000
│       └── frontend/    React 18 + Vite + TypeScript              :5173 (dev)
├── packages/
│   ├── shared-py/       (пусто, будущий общий код)
│   └── shared-ts/       (пусто, будущий API-клиент)
├── pyproject.toml       uv workspace, ruff config
├── docker-compose.yml   единый стек со всеми сервисами + postgres
├── .env.example         все переменные окружения
└── bin/test-all.sh      pytest пер-сервис в отдельных процессах
```

### 4.2 Точки сцепления (важно для параллельности)

| # | Точка | Где | Как часто меняется | Риск конфликта |
|---|---|---|---|---|
| 1 | `IngestRequest` (контракт parsers→catalog) | `services/catalog/catalog/schemas.py:268` + `services/parsers/parsers/catalog_publisher.py` | редко | **средний** — два места правки |
| 2 | Alembic миграции | `services/catalog/alembic/versions/` | высокая (7 за 2 дня) | **высокий** — короткий `revision: "0007"` дублируется легко |
| 3 | Корневой `pyproject.toml` | uv workspace, ruff | редко | низкий |
| 4 | `docker-compose.yml` | стек, порты, имена | редко | низкий, но с сильными последствиями (см. §6) |
| 5 | `.env.example` | переменные среды | редко | низкий |
| 6 | `.claude/settings.json` | разрешения Claude Code | очень редко | низкий |
| 7 | API web-test ↔ frontend | `services/web-test/app/api/*.py` ↔ `services/web-test/frontend/src/lib/*` | высокая | низкий, если backend и frontend ведут разные агенты |

### 4.3 Что **не** конфликтует (хорошие новости)

- **БД у catalog (Postgres) и parsers (SQLite) полностью раздельны.** Не делят даже файлы.
- **Тесты:** у каждого сервиса свой `tests/conftest.py` и своя тестовая БД. `bin/test-all.sh` запускает их **отдельными процессами pytest** — никаких pluggy-конфликтов.
- **Frontend живёт отдельным toolchain'ом** (npm/Vite). uv его не трогает. Можно работать над фронтом, не зная Python.
- **conftest.py в каждом сервисе изолирует фикстуры.** Никаких общих фикстур нет.

---

## 5. Варианты организации — пять штук с разбором

### Вариант A. Worktrees per feature-branch (полная изоляция)

**Суть.** Для каждой задачи — отдельная папка-копия рабочего дерева на отдельной ветке. Каждая сессия Claude Code в своём worktree.

```
/Users/vitaliy/Projects/
├── boardgames-platform/        ← основной клон (например, ветка main или интеграционная)
├── bg-feat-bgg/                ← worktree для фичи BGG-парсера
├── bg-feat-sources/            ← worktree для фичи источников
└── bg-review-pr-42/            ← worktree для ревью чужого PR
```

**Плюсы.**
- Полная изоляция git-state. Можно делать `git rebase`, `git reset --hard` в одном worktree, не задевая другие.
- Claude Code сессии в разных папках (encoded-cwd разный) — изолированы автоматически.
- Можно одновременно держать несколько фич в IDE, переключаться без `git stash`.

**Минусы.**
- **Каждый worktree — свой `.venv` (~сотни МБ) и свой `node_modules` (~250 МБ).** Первичный `uv sync` ~30–60 секунд.
- **Docker-compose на нашей машине один.** Контейнеры `bg-postgres`, `bg-catalog`, `bg-parsers`, `bg-web-test` имеют **фиксированные имена** в `docker-compose.yml` (`container_name: bg-...`). Два docker-стека одновременно — коллизия имён.
  - **Решение «лайт»:** один docker-стек на машину, общий postgres, разные тестовые БД (`catalog_test_a`, `catalog_test_b`). См. §7.2.
  - **Решение «полное»:** разные `--project-name`, разные хост-порты в worktree-локальном `.env`. Сложнее, дороже.
- При rebase/merge ветки — может потребоваться `uv sync` повторно, если изменился lock-файл.

**Когда применять.**
- Длинные параллельные фичи в разных PR.
- Экспериментальная ветка, которую не страшно сломать.
- Ревью чужого PR без переключения с активной задачи.

### Вариант B. Per-service в одном клоне

**Суть.** Один клон, одна ветка. Агент 1 правит только `services/catalog/`, агент 2 — только `services/parsers/`, агент 3 — только `services/web-test/`.

```
boardgames-platform/    ← один клон, одна ветка
├── services/
│   ├── catalog/        ← агент 1 работает здесь
│   ├── parsers/        ← агент 2 работает здесь
│   └── web-test/       ← агент 3 работает здесь
```

**Плюсы.**
- Один `.venv`, один `node_modules`, один docker-стек. Setup нулевой.
- Естественные границы: pytest per-service, conftest per-service.

**Минусы.**
- **Активные фичи сейчас кросс-сервисные.** BGG-парсер живёт и в catalog (модель + endpoint), и в web-test (UI, API-прокси). Если один агент пишет catalog-сторону, другой — web-test-сторону одной фичи, они правят файлы одной фичи в разных папках, без атомарных коммитов.
- **Контракт `/ingest/offers` живёт в parsers И catalog одновременно.** Per-service split не позволяет атомарно его поправить.
- Запуск двух `claude` в одной папке `/Users/vitaliy/Projects/boardgames-platform` — конфликт session-state. Решение: запускать каждый агент из подпапки сервиса (`cd services/catalog && claude`), тогда encoded-cwd разный. Но всё равно работающее дерево одно — конфликт по сторонним файлам (`pyproject.toml`, `docker-compose.yml`) сохраняется.

**Когда применять.**
- Только когда задачи **реально не пересекаются** по сервисам. Пример: новый парсер магазина в `services/parsers/parsers/stores/myshop.py` без необходимости что-либо менять в catalog.
- Сейчас в проекте **этот режим непригоден как основной**.

### Вариант C. Backend + Frontend split в одном клоне (РЕКОМЕНДУЕМЫЙ БАЗОВЫЙ)

**Суть.** Один клон, одна ветка. Агент 1 ведёт **все** backend-сервисы (catalog, parsers, web-test/app), Python-мир. Агент 2 ведёт **только** `services/web-test/frontend/` — React-мир.

```
boardgames-platform/                            ← клон, одна ветка
├── services/
│   ├── catalog/           ← agent 1 (backend)
│   ├── parsers/           ← agent 1 (backend)
│   └── web-test/
│       ├── app/           ← agent 1 (backend, Python API)
│       └── frontend/      ← agent 2 (frontend, React)
```

**Запуск (это и есть хитрость).**
- Агент 1: `cd /Users/vitaliy/Projects/boardgames-platform && claude` → cwd = корень → encoded-cwd = `-Users-vitaliy-Projects-boardgames-platform`
- Агент 2: `cd /Users/vitaliy/Projects/boardgames-platform/services/web-test/frontend && claude` → cwd = подпапка → encoded-cwd = другой → сессия отдельная.

**Плюсы.**
- Технологические стеки физически не пересекаются: uv vs npm. Разные тесты, разные конфиги, разные `CLAUDE.md`.
- Изоляция сессий бесплатно — за счёт разной cwd.
- Один docker-стек, один postgres — никаких хост-конфликтов.
- Естественен для текущей фичи: backend-агент пишет endpoint, frontend-агент рисует страницу.

**Минусы.**
- Контракт frontend ↔ web-test API нужно сериализовать: backend сначала добавляет endpoint, frontend потом потребляет. Решается **в чате**: «эй, добавь endpoint X с такими полями, я подцеплюсь».
- Один git working tree → если оба агента случайно правят один файл (например, `services/web-test/frontend/dist/` через docker build) — last-write-wins. Правило простое: **backend никогда не трогает `services/web-test/frontend/src/`, frontend никогда не трогает `services/web-test/app/`.**

**Когда применять.**
- Любая фича вида «бэкенд API + UI» (~80% активных задач).
- Это **режим по умолчанию** для нашего проекта на ближайшие недели.

### Вариант D. Headless batch (CI-style)

**Суть.** Запуск Claude Code как обычной CLI без интерактива:

```bash
claude -p "обнови docstrings в services/catalog/catalog/api.py" \
  --output-format json
```

Несколько таких можно запустить параллельно через `&`:

```bash
claude -p "task A" --output-format json > a.json &
claude -p "task B" --output-format json > b.json &
wait
```

**Плюсы.**
- Полная параллельность без worktree.
- Идеально для рутины: «прогнать ревью всех PR», «обновить CLAUDE.md в каждом сервисе», «генерировать семплы парсеров».

**Минусы.**
- Не для интерактивной разработки. Нет диалога, нет правки по обратной связи.
- Если задача нетривиальная — Claude может зайти в тупик, и ты узнаешь только из логов.

**Когда применять.**
- Massивная правка по шаблону.
- Прогон бенчмарков.
- Параллельный ревью.

### Вариант E. Subagents внутри сессии

**Суть.** Не отдельная сессия, а делегирование подзадач **внутри** одной сессии через Agent tool.

```
Сессия Claude Code
├── основной агент ведёт диалог с тобой
└── Agent(...) → запущен subagent A "прочитать catalog/parsers/bgg/* и саммари"
                Agent(...) → запущен subagent B "найти все вызовы IngestRequest"
                ↓ оба возвращают отчёты
```

**Плюсы.**
- Никакого внешнего setup'а — встроено.
- Хорошо для разведки/анализа: subagent читает файлы, основной агент не засоряет контекст.

**Минусы.**
- Не настоящий top-level параллелизм — ты ведёшь один разговор.
- Agent tool возвращает **текстовый результат**, не оставляет «открытую сессию» для итерации.

**Когда применять.**
- В любой из сессий A/B/C — для разведки, ревью, поиска ссылок, анализа кода.
- **Не вместо** параллельных сессий, а **в дополнение к ним**.

---

## 6. Рекомендация для нашего проекта

Сводная таблица:

| Режим | Когда | Setup-стоимость |
|---|---|---|
| **C (backend + frontend split)** | базовый режим, текущие фичи | 5 минут |
| **A (worktree)** | escape hatch — две разные фичи параллельно | 10–15 минут |
| **E (subagents)** | внутри любой сессии — для разведки и ревью | 0 минут |
| **D (headless)** | batch-задачи (массовый рефакторинг, ревью, документация) | 0 минут |
| **B (per-service)** | только если задачи **реально** не пересекаются по сервисам | не рекомендуется как базовый |

**Базовый план:**
1. Используй **C** как режим по умолчанию.
2. Когда нужна вторая параллельная фича в отдельной ветке — поднимай **A** для неё.
3. Внутри любой сессии используй **E** для разведки.
4. **D** держи в голове для batch-рутины.

---

## 7. Setup-сценарии (пошагово, с пояснениями)

### 7.1 Сценарий C — рекомендуемый старт

**Цель.** Запустить две сессии Claude Code: одну для backend-разработки, одну для frontend.

**Шаги.**

```bash
# === Окно 1 (backend) ===
# Шаг 1: перейти в корень репо.
cd /Users/vitaliy/Projects/boardgames-platform

# Шаг 2: поднять docker-стек (если ещё не поднят).
# Profile "full" поднимает postgres + catalog + parsers + web-test (4 контейнера).
docker compose --profile full up -d

# Шаг 3: проверить, что все 4 контейнера healthy.
docker compose ps

# Шаг 4: установить Python-зависимости workspace (один .venv в корне).
# Делается один раз, потом повторяется только если изменился pyproject.toml/uv.lock.
uv sync --all-packages --group dev

# Шаг 5: запустить Claude Code.
# Сессия будет жить в ~/.claude/projects/-Users-vitaliy-Projects-boardgames-platform/
claude
```

```bash
# === Окно 2 (frontend) — в другом терминале ===
# Шаг 1: перейти в папку фронтенда. Это критично — даёт другую cwd.
cd /Users/vitaliy/Projects/boardgames-platform/services/web-test/frontend

# Шаг 2: установить npm-зависимости (один раз).
npm install

# Шаг 3: поднять Vite dev-сервер. Он проксирует /api на :8000 (web-test backend).
# Запускаем в фоне, чтобы окно осталось свободным для Claude Code.
npm run dev &

# Шаг 4: запустить Claude Code из этой же папки.
# Сессия будет жить в ~/.claude/projects/-Users-vitaliy-Projects-...-frontend/
# То есть в другой папке, чем backend-сессия → не пересекаются.
claude
```

**Что получилось.**
- Две сессии Claude Code, две папки сессий, ноль конфликтов session-state.
- Один docker-стек, один postgres, один `.venv`, один `node_modules` — никаких дублирований.
- Backend-агент видит весь репо (его cwd = корень), но по умолчанию работает с Python.
- Frontend-агент по умолчанию остаётся в папке frontend.

**Проверка.**

```bash
ls ~/.claude/projects/ | grep boardgames
# должно быть две папки:
# -Users-vitaliy-Projects-boardgames-platform
# -Users-vitaliy-Projects-boardgames-platform-services-web-test-frontend
```

### 7.2 Сценарий A — worktree для второй задачи

**Когда.** Ты в Окне 1 ведёшь BGG-парсер на ветке `bgg-catalog-parser`, и тебе пришёл PR на ревью или хочется параллельно начать другую фичу. Не хочешь переключать ветки.

**Шаги.**

```bash
# Шаг 1: создать worktree.
# Команда говорит: «создай папку ../bg-feat-X, переключи её на новую ветку
# feat-X, ответвлённую от main».
cd /Users/vitaliy/Projects/boardgames-platform
git worktree add ../bg-feat-X -b feat-X main

# Альтернатива (если ветка уже есть):
git worktree add ../bg-feat-X feat-X

# Шаг 2: перейти в worktree.
cd ../bg-feat-X
# Проверка: git branch покажет, что ты на feat-X.

# Шаг 3: установить зависимости.
# В worktree свой корень → свой .venv создастся.
uv sync --all-packages --group dev

# Шаг 4 (вариант "лайт"): использовать общий docker-стек.
# Скопировать .env.example как .env (он gitignored).
cp .env.example .env

# Создать отдельную тестовую БД, чтобы pytest в этом worktree
# не сносил данные другого.
docker exec bg-postgres createdb -U catalog catalog_test_featx

# Прогнать миграции на новой тестовой БД.
cd services/catalog
DATABASE_URL=postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test_featx \
  uv run --package boardgames-catalog alembic upgrade head
cd ../..

# Отредактировать .env вручную: подменить TEST_DATABASE_URL.
# Открой .env и поменяй строку:
#   TEST_DATABASE_URL=postgresql+asyncpg://catalog:catalog@localhost:5433/catalog_test_featx
# DATABASE_URL оставить общий с main-worktree — обе сессии пишут в один dev-каталог.

# Шаг 5: запустить Claude Code в worktree.
claude
```

**Альтернатива «полная изоляция» (только если очень надо):**

```bash
# Если хочешь два полностью отдельных docker-стека одновременно.
# Тогда в .env worktree подменяем все хост-порты:
#   POSTGRES_PORT=5443
#   CATALOG_PORT=8012
#   PARSERS_PORT=8011
#   WEB_TEST_PORT=8010
# И запускаем compose с другим project name (имя проекта определяет имена контейнеров):
docker compose --project-name bg-featx --profile full up -d
```

> Junior-объяснение: в `docker-compose.yml` строка `name: boardgames-platform` фиксирует имя проекта. Два compose-стека с одним именем не запустятся одновременно — будет коллизия имён контейнеров (`bg-postgres` уже занято). Флаг `--project-name` это переопределяет.

**Удаление worktree (когда фича замержена):**

```bash
# Удалить worktree (он отвяжется от .git).
git worktree remove ../bg-feat-X

# Если внутри worktree были незакоммиченные правки — нужен --force.
git worktree remove --force ../bg-feat-X
```

### 7.3 Сценарий E — subagents внутри сессии

**Не требует setup'а.** В чате просто пишешь:

> Запусти Explore-агент: прочитай `services/catalog/catalog/parsers/bgg/` и сделай саммари API: какие endpoints, какие модели, как вызывается клиент BGG.

Subagent ушёл копать, основной чат не заблокирован — можно параллельно работать. Когда subagent вернётся — увидишь его отчёт.

**Полезные паттерны.**
- «Запусти 3 subagent'а параллельно: один читает миграции, второй — тесты ingest, третий — promotion. Сводка через 5 минут.»
- «Запусти subagent для ревью этого PR: проверь типы, проверь миграции, проверь контракты.»

### 7.4 Сценарий D — headless batch

**Пример: прогнать ревью на трёх сервисах параллельно.**

```bash
cd /Users/vitaliy/Projects/boardgames-platform

claude -p "сделай security-review для services/catalog" \
  --output-format json > /tmp/review-catalog.json &

claude -p "сделай security-review для services/parsers" \
  --output-format json > /tmp/review-parsers.json &

claude -p "сделай security-review для services/web-test" \
  --output-format json > /tmp/review-web-test.json &

wait
echo "Все три ревью готовы. Смотри /tmp/review-*.json"
```

> Junior-объяснение: `&` запускает команду в фоне. `wait` ждёт, пока все фоновые процессы завершатся. Так получаешь параллельность на уровне shell.

---

## 8. Протокол разрешения конфликтов

### 8.1 Изменения в `pyproject.toml` / uv-зависимостях

**Когда возникает.** Один агент добавляет зависимость в `services/catalog/pyproject.toml` (например, `httpx`), второй агент в это же время правит корневой `pyproject.toml` (добавляет dev-зависимость).

**Правила.**
1. **Корневой `pyproject.toml`** правит **только тот агент, который ведёт инфраструктурную задачу**. Один за раз.
2. **Per-service `services/<name>/pyproject.toml`** правит владелец сервиса (в split C — backend-агент).
3. **`uv.lock` всегда коммитится вместе** с правкой `pyproject.toml`. Никогда отдельно. Если они расходятся — следующий `uv sync` решит, и кто-то другой получит surprise-изменения в lock.
4. После `git pull` другого агента: **всегда** `uv sync --all-packages --group dev`. Иначе можешь работать со старым `.venv`.

**Что делать, если конфликт всё-таки случился (merge-conflict в `uv.lock`):**

```bash
# Откатить локальный lock к origin'у и пересобрать.
git checkout origin/main -- uv.lock
uv lock          # пересобирает lock с учётом обоих pyproject.toml
git add uv.lock
git commit -m "chore: rebuild uv.lock after merge"
```

### 8.2 Создание новых alembic-миграций

**Это самое острое место в репо.** Сейчас в миграциях:

```python
# services/catalog/alembic/versions/20260509_0007_source_scrape_runs.py
revision: str = "0007"
down_revision: Union[str, None] = "0006"
```

**Что произойдёт, если два агента сделают `alembic revision --autogenerate` параллельно:**
- Оба получат `down_revision = "0007"` (текущая голова).
- Оба впишут `revision = "0008"` (следующий по счёту).
- При merge — два узла с `revision="0008"` и общим родителем `"0007"`. **Two heads.**
- `alembic upgrade head` упадёт с ошибкой: «несколько head-ов, не знаю какой применить».

**Правила.**
1. **Один владелец миграций** в любой момент времени. В split C — backend-агент. У frontend-агента повода создавать миграции нет в принципе.
2. **Перед** `alembic revision --autogenerate`:
   ```bash
   git fetch origin
   git log origin/main..HEAD -- services/catalog/alembic/versions/
   alembic heads     # покажет текущие головы — должна быть одна
   ```
3. Если две ветки уже сделали миграции с одинаковым `revision` — **никогда** не запускай `alembic merge` без согласования (риск потери данных). Вместо этого:
   - Первый коммитит свою миграцию первым.
   - Второй после rebase **руками** меняет `revision: str` и `down_revision: str` так, чтобы получилась цепочка (его миграция стала после первой).
   - Файл переименовать через `git mv` если изменился timestamp в имени.
4. Если что-то пошло не так — **остановись и спроси**. Не запускай `alembic merge`.

### 8.3 Изменения в HTTP-контракте `POST /ingest/offers`

**Где живёт контракт (4 точки):**
- `services/catalog/catalog/schemas.py:268` — Pydantic-модель `IngestRequest` (consumer-side).
- `services/catalog/catalog/routers/ingest.py` — обработчик endpoint'а.
- `services/parsers/parsers/catalog_publisher.py` — формирование payload (producer-side).
- Тесты: `services/catalog/tests/test_ingest_and_matching.py`, `services/parsers/tests/test_catalog_publisher.py`.

**Правила.**
1. **Один атомарный коммит** на все 4 точки. Никогда «сначала producer, потом consumer» — это окно, в котором parsers шлёт мусор в catalog, и тот падает.
2. До правки агент **явно объявляет в чате**: «правлю `IngestRequest`». Второй агент не лезет в эти файлы.
3. В split C это естественно: backend-агент владеет всеми тремя сервисами, делает один коммит. В split B — это место, где split B ломается.
4. Долгосрочно — вынести `IngestRequest` в `packages/shared-py/`, тогда контракт станет одним файлом (см. §10).

### 8.4 `docker-compose.yml` / `.env`

**Правила.**
1. `docker-compose.yml` — один владелец за раз. Обычно backend-агент (frontend в Docker не нуждается).
2. `.env` — gitignored, **per-developer и per-worktree**. Не делится коллективно. Если поменял что-то у себя — это твоё дело.
3. `.env.example` правит тот, кто добавил переменную в свой сервис. Изменения — отдельным коммитом, чётко описывающим что появилось.

### 8.5 `.claude/settings.json`

- Лежит в индексе — shared между всеми сессиями. Правка из одной сессии видна другой.
- Меняется отдельным коммитом, согласованно. Не в потоке других правок.
- `.claude/settings.local.json` — **per-developer** (gitignored). Можно держать свой.

---

## 9. Анти-паттерны (что НЕ делать)

### 9.1 Не запускать два `claude` в одной cwd
**Что произойдёт.** Совпадёт `encoded-cwd` → `~/.claude/projects/<...>` совпадёт → файлы сессий перетрут друг друга. Симптом: «куда делась моя история?», «`/resume` показывает чужую сессию».
**Решение.** Либо worktree, либо запуск в подпапке.

### 9.2 Не использовать split B для кросс-сервисных фич
**Что произойдёт.** Атомарный коммит на BGG-фичу станет невозможным: catalog-сторона у одного агента, web-test-сторона у другого. История запутается, ревью PR станет адом.
**Решение.** Split C для кросс-сервисных фич, split B только для реально изолированных задач.

### 9.3 Не запускать два docker-compose стека под именем `boardgames-platform`
**Что произойдёт.** Имена контейнеров `bg-postgres`, `bg-catalog` и т.п. фиксированы в `docker-compose.yml`. Второй `docker compose up` упадёт с ошибкой «container name already in use».
**Решение.** Либо общий стек на машину (рекомендуется), либо разные `--project-name` + переопределённые порты в worktree-локальном `.env`.

### 9.4 Не делать `alembic revision --autogenerate` параллельно из двух мест
**Что произойдёт.** Two heads, ручная починка. См. §8.2.
**Решение.** Один владелец миграций.

### 9.5 Не править `IngestRequest` из двух мест одновременно
**Что произойдёт.** producer и consumer разойдутся — parsers начнёт слать поле, которое catalog не понимает (или наоборот). Проверка контракта работает на runtime, не на compile.
**Решение.** Атомарный коммит, объявление в чате.

### 9.6 Не запускать `uv sync` в подпапке сервиса
**Что произойдёт.** Создастся `services/<name>/.venv`, который uv workspace не использует. CLAUDE.md явно предупреждает: такие лишние `.venv` нужно удалять.
**Решение.** `uv sync` всегда из корня репо (или корня worktree).

### 9.7 Не запускать pytest из корня репо
**Что произойдёт.** В корне нет `[tool.pytest.ini_options]` — это сделано намеренно. Pluggy не может удержать два модуля с именем `tests.conftest` в одной сессии → `ImportPathMismatchError`.
**Решение.** Либо `cd services/<name> && uv run pytest`, либо `bin/test-all.sh` (он запускает pytest пер-сервис в отдельных процессах).

### 9.8 Не использовать headless mode (D) для интерактивной разработки
**Что произойдёт.** Claude уйдёт в работу, ты не сможешь корректировать его в процессе, узнаешь о проблемах из логов после.
**Решение.** D — для batch-задач. Для разработки — A/B/C.

### 9.9 Не забывать про расхождения `.env` между worktree
**Что произойдёт.** В одном worktree `POSTGRES_PORT=5443`, в другом `5433`. Тесты в одном worktree пишут в одну БД, в другом — в другую. Симптом: «у меня всё проходит локально, в Docker ломается».
**Решение.** Помни, что `.env` per-worktree. После создания worktree — сразу проверь его `.env`.

### 9.10 Не коммитить чувствительные файлы
- `.env` (секреты)
- `data/*.sqlite` (БД parsers/web-test)
- `node_modules/`
- `.venv/`
- `services/web-test/frontend/dist/` (build-артефакты, попадают через docker)

Все они в `.gitignore`. Перед коммитом — `git status`, чтобы убедиться.

---

## 10. Roadmap-улучшения (что починить, чтобы параллелизм стал безопаснее)

Это не обязательная часть плана — это **возможные шаги**, которые снимут самые острые риски. Реализую по запросу.

### 10.1 Длинный alembic `revision`-id [высокий приоритет]
**Проблема.** Сейчас `revision: str = "0007"` — короткий int-string. Коллизии при параллельной работе очень вероятны.
**Решение.** Перейти на `revision = "20260509_0007_source_scrape_runs"` (полное имя файла без `.py`). Никогда не совпадёт случайно.
**Что менять:**
- `services/catalog/alembic/script.py.mako` — шаблон новых миграций.
- Опционально: разовый rename существующих миграций (риск — переписать `down_revision` цепочкой).
**Эффект.** Снимает главный риск из §8.2.

### 10.2 Вынести `IngestRequest` в `packages/shared-py/` [высокий приоритет]
**Проблема.** Контракт parsers↔catalog живёт в двух местах. Атомарный коммит обязателен, легко ошибиться.
**Решение.** В `packages/shared-py/` создать общий пакет с pydantic-моделью. Catalog и parsers импортируют оттуда.
**Что менять:**
- Новый пакет `packages/shared-py/shared/contracts.py`.
- Зарегистрировать его как member workspace в корневом `pyproject.toml`.
- `services/catalog/catalog/schemas.py` — убрать `IngestRequest`, заменить на импорт.
- `services/parsers/parsers/catalog_publisher.py` — убрать локальное dict-описание, импортировать модель и валидировать через неё.
**Эффект.** Контракт становится одним файлом. Половина рисков из §8.3 снимается.

### 10.3 `services/web-test/frontend/CLAUDE.md` [средний приоритет]
**Проблема.** Сейчас CLAUDE.md есть в trex backend-сервисах, но не во фронте. Frontend-агенту неоткуда узнать local правила.
**Решение.** Создать `services/web-test/frontend/CLAUDE.md` с инструкциями:
- «Не трогай Python-код выше этой папки».
- «Контракты приходят через `services/web-test/app/api/*.py`. Типы для них — в `src/lib/api.ts`.»
- «Тесты фронта — `npm run test` (если будут).»
- Стиль кода, паттерны, важные компоненты.
**Эффект.** Split C становится самоподдерживающимся.

### 10.4 `.claude/scheduled_tasks.lock` в `.gitignore` [низкий приоритет]
**Проблема.** Lock-файл постоянно появляется в `git status` как untracked. Шумит у обоих агентов.
**Решение.** Одна строка в `.gitignore`:
```
.claude/scheduled_tasks.lock
```
**Эффект.** Чистый `git status`.

### 10.5 Pre-commit hook на `alembic heads` [низкий приоритет, после 10.1]
**Проблема.** Two heads ловится поздно — на CI или при `alembic upgrade`.
**Решение.** Добавить в `.claude/settings.json` или git pre-commit hook, который перед коммитом миграции запускает `alembic heads` и падает, если голов больше одной.
**Эффект.** Дешёвый guard-rail для миграций. Имеет смысл только после 10.1, иначе будет ложно срабатывать на коротких revision-id.

---

## 11. Верификация: как убедиться, что всё работает

После настройки сценария C (или A) пройди этот чеклист:

- [ ] `ls ~/.claude/projects/ | grep boardgames` — видно две папки сессий с разными encoded-cwd.
- [ ] `docker compose ps` — все 4 контейнера healthy.
- [ ] `git status` в обеих сессиях даёт одинаковый ответ (если split C — общий клон) или независимые ответы (если worktree).
- [ ] В одной сессии создаёшь файл, в другой делаешь `ls` — файл виден сразу (split C) или невидим (разные worktrees).
- [ ] Backend-агент коммитит `services/catalog/...`, frontend-агент — `services/web-test/frontend/src/...`. `git pull --rebase` проходит без конфликтов.
- [ ] `bin/test-all.sh` зелёный после правок из обеих сессий.
- [ ] `cd services/catalog && uv run --package boardgames-catalog alembic heads` — ровно одна голова.
- [ ] (Worktree) `git worktree list` показывает все активные worktrees, никаких сирот.

---

## 12. FAQ для junior

**Q: Я запустил `claude` дважды в одной папке. Как починить?**
A: Закрой обе сессии. Зайди в `~/.claude/projects/<encoded-cwd>/` и посмотри `*.jsonl` — там твоя история. Если файл одного из агентов перетёрт — увы, потерян. На будущее: всегда одна папка = одна сессия.

**Q: Можно ли запустить frontend-сессию в любой подпапке, не обязательно `frontend/`?**
A: Можно. Главное — другая cwd, чем у backend-сессии. Папка frontend удобна потому, что Vite, npm и весь React-мир там.

**Q: Что если я случайно начал править Python-код во frontend-сессии?**
A: Технически ничего не сломается — у frontend-сессии есть доступ ко всему репо. Но это рассинхронизирует разделение. Просто скажи в чате: «эта правка для backend-сессии, верни как было».

**Q: У меня worktree, как его обновить от main?**
A: Внутри worktree: `git fetch origin && git rebase origin/main` (или merge, как привычнее). После — `uv sync --all-packages --group dev`, если изменился `uv.lock`.

**Q: Я создал миграцию в worktree. Как её перенести в main-worktree?**
A: Никак — миграция уже в общем `.git`. Когда замержишь ветку worktree в main, миграция станет частью main. `alembic upgrade head` в любом worktree применит всё что есть в текущей ветке.

**Q: Сколько worktree разумно держать одновременно?**
A: 2–3 — сладкая зона. Больше — путаешься в папках, теряется visual working directory. Каждый worktree это ещё `.venv` (~сотни МБ), `node_modules` (~250 МБ), отдельная история сессий.

**Q: Я хочу запустить parsers-сервис локально (не в Docker), пока catalog в Docker. Сломается?**
A: Нет, если отредактируешь `.env`: `CATALOG_INGEST_URL=http://localhost:8002/ingest/offers` и `DATABASE_URL=...localhost:5433...`. Имя `postgres` (как в docker-сети) с хоста не разрезолвится — только `localhost:5433`.

**Q: Один агент случайно сделал `git push`. Как откатить?**
A: Зависит от ветки. Если на свою feature-ветку — ничего страшного, продолжай. Если на main — стоп, спроси старшего: force-push на main без подтверждения запрещён правилами проекта.

---

## 13. Чеклист «первого дня» (TL;DR в виде списка)

- [ ] Прочитал §2 (глоссарий), §3 (как работает Claude Code), §4 (карта проекта).
- [ ] Понял, что **cwd определяет, где живёт сессия**.
- [ ] Запустил сценарий C: backend-сессию из корня, frontend-сессию из `services/web-test/frontend/`.
- [ ] Проверил, что `~/.claude/projects/` содержит две разные папки сессий.
- [ ] Знаю, что **миграции и `IngestRequest`** правит только один агент за раз.
- [ ] Знаю про worktree (вариант A) и могу его поднять, когда нужна вторая фича.
- [ ] Прочитал §9 (анти-паттерны) — не делаю этих вещей.
- [ ] Запомнил §11 (верификация) — могу пройти чеклист, когда что-то пошло не так.

---

## 14. Критичные файлы (чтобы было под рукой)

- [`CLAUDE.md`](../CLAUDE.md) — каноническая методичка проекта.
- [`docker-compose.yml`](../docker-compose.yml) — фиксированные имена `bg-*`, источник риска при двух стеках.
- [`.env.example`](../.env.example) — переменные, которые надо переопределять в worktree.
- `services/catalog/alembic/script.py.mako` — шаблон новых миграций (точка для roadmap-10.1).
- `services/catalog/catalog/schemas.py` (`IngestRequest`, ~строка 268) и `services/parsers/parsers/catalog_publisher.py` — две стороны контракта `/ingest/offers`.
- `.claude/settings.json` — shared-конфиг Claude Code (allow-list разрешённых Bash-команд).
- [`bin/test-all.sh`](../bin/test-all.sh) — правильный способ запустить все тесты.
- [`.gitignore`](../.gitignore) — куда добавить `.claude/scheduled_tasks.lock` (roadmap-10.4).
