# Ревью инфраструктуры монорепо — 2026-07-10

Отчёт review-агента. Проверено: compose + 4 Dockerfile, services/browser,
все pyproject, bin/, .env.example vs реально читаемые env-переменные, hooks,
docs, git-гигиена, packages/apps. Бизнес-код не ревьюился.

## 1. docker-compose.yml + Dockerfile'ы

**🔴 CRITICAL — web-test: рассинхрон имени env-переменной пути к БД →
volume не используется, данные теряются при пересоздании контейнера.**
- Код читает `PORTAL_DB_PATH` (`services/web-test/app/db_local.py:922`,
  default `data/portal.sqlite`).
- Compose передаёт `DB_PATH: /data/portal.sqlite` (`docker-compose.yml:141`),
  Dockerfile ставит `ENV DB_PATH=data/debug.sqlite`
  (`services/web-test/Dockerfile`).
- Итог: обе настройки мертвы, SQLite реально пишется в
  `/app/data/portal.sqlite` **внутри контейнера**, а volume
  `portal-data:/data` пустой. `docker compose up --force-recreate` /
  пересборка образа молча стирает историю поисков портала. Фикс — либо
  переименовать env в compose/Dockerfile на `PORTAL_DB_PATH=/data/portal.sqlite`,
  либо читать `DB_PATH` в коде.

**🟠 MAJOR — compose не пробрасывает в контейнеры половину «ручек»,
задокументированных в `.env.example`.**
- catalog (`docker-compose.yml:66-83`): передаются только `DATABASE_URL`,
  `LOG_LEVEL`, `REQUIRE_AUTH`, `BGG_*`. Но `catalog/config.py`
  (pydantic-settings) читает ещё `OLLAMA_BASE_URL`, `ML_ENABLED`,
  `ML_EMBED_MODEL`, `MATCH_WORKER_*`, `MATCH_T1/T2/T3_*`,
  `MATCH_DECISIONS_TTL_*` — все они есть в `.env.example:66-92`.
  В каноническом Docker-режиме (а по CLAUDE.md это режим по умолчанию)
  правка этих строк в `.env` **молча ничего не меняет** — `.env` в образ
  не попадает (он в `.dockerignore`), а compose их не форвардит. Сейчас
  работает на совпадении дефолтов в `config.py`.
- parsers (`docker-compose.yml:106-116`): не пробрасываются `PROXY`,
  `WB_BACKEND`, `WB_API_VERSION`, `WB_IMPERSONATE`,
  `OZON_WARMUP_INTERVAL_MINUTES`, `ONLINETRADE_WARMUP_INTERVAL_MINUTES`,
  `PARSERS_PER_PARSER_TIMEOUT_SECONDS` — при этом код их читает
  (`os.getenv` в `services/parsers/parsers/`), а `.env.example:100-166`
  подробно описывает как рабочие настройки. Та же ловушка.

**🟠 MAJOR — у parsers нет healthcheck вообще** (ни в compose, ни в
Dockerfile), при этом корневой CLAUDE.md обещает «`docker compose ps` —
все 4 healthy». Плюс `web-test.depends_on` — короткая форма без
`condition: service_healthy` (`docker-compose.yml:158-160`), т.е. web-test
стартует, не дожидаясь готовности зависимостей. Матрица непоследовательна:
catalog/browser — healthcheck в compose, web-test — в Dockerfile,
parsers — нигде.

**🟠 MAJOR — невоспроизводимые образы:** ни один Dockerfile не использует
`uv.lock`, все зависимости — только нижние границы (`fastapi>=0.110`...).
Каждый rebuild может притащить новые мажорные версии транзитивных пакетов.
Честно задокументировано в `.dockerignore` («если переходим на reproducible
builds — убрать»), но с ML/pgvector-стеком это уже реальный риск
расхождения local (.venv по локу) vs Docker (latest).

**🟠 MAJOR (для prod) — все 4 сервиса работают под root:** ни в одном
Dockerfile нет `USER`. Для локалки терпимо, но browser-сервис прямо
позиционируется под «AMD64 cloud» — туда без non-root ехать не стоит.
Отсутствует и `PYTHONUNBUFFERED=1` везде, кроме web-test.

**🟡 MINOR:**
- `node:20-alpine` в `services/web-test/Dockerfile` — Node 20 достиг EOL
  30.04.2026 (сегодня 07.2026). Обновить на `node:22-alpine`.
- Устаревший комментарий там же: «postgres:16-alpine в docker-compose.yml» —
  фактически уже `pgvector/pgvector:pg16` (мажор совпадает, pg_dump-пин
  корректен, но комментарий врёт).
- Паттерн `COPY pyproject.toml . && pip install -e .` до копирования кода
  (catalog/parsers/browser) — работает, но хрупкий: держится на том, что
  setuptools молча собирает пустой editable-пакет; с hatchling (как в
  web-test) сломается.
- `services/parsers/Dockerfile`: `ENV DB_PATH=data/prices.sqlite` — дефолт
  вне volume; без compose-override данные не персистятся (compose корректно
  ставит `/data/prices.sqlite`).
- Дефолтные креды `catalog/catalog` как fallback в compose — для локалки
  ок, секретов в compose нет.

**Хорошее:** `restart: unless-stopped` везде; профили согласованы (browser
сознательно вне `full` и это задокументировано в комментариях compose);
`log_statement=mod` как audit-trail; PGDG-пин `postgresql-client-16` в
web-test — образцово прокомментирован; `.dockerignore` полный и с
объяснениями; `docker compose config` валиден.

## 2. services/browser — недокументированный четвёртый сервис

Это **живой** мини-сервис «browser-as-a-service» (Camoufox/Playwright,
382 строки `browser/api.py`, порт 8003), полноценный участник инфры:
member uv workspace (`pyproject.toml:23`), сервис в compose (profile
`browser`), свой Dockerfile с ARM64/AMD64-ветвлением. Последний коммит —
2026-05-14.

- **🟠 MAJOR:** отсутствует в карте сервисов корневого `CLAUDE.md`
  (0 упоминаний слова «browser»), в `README.md` и в `docs/architecture.md`
  («платформа из трёх backend-сервисов»). Нет `services/browser/CLAUDE.md`.
  Агент/новый разработчик, следующий CLAUDE.md, о нём не узнает; при этом
  `.env.example` его подробно описывает — источники правды противоречат
  друг другу. Судя по memory и roadmap (PRS-3: «L2-fallback через
  camoufox»), сервис — стратегический запасной путь, а не мусор, значит
  его надо документировать, а не удалять.
- **🟡 MINOR:** нет тестов и он не в `bin/test-all.sh` (пока нечего
  гонять — но при появлении тестов список сервисов в скрипте захардкожен).

## 3. pyproject.toml

- **🟡 MINOR — дубль dev-зависимостей:** корневой `[dependency-groups].dev`
  (pytest, pytest-asyncio, httpx, ruff) и практически те же списки в
  `optional-dependencies.dev` каждого сервиса. Пока версии совпадают, но
  это 4 места для дрейфа — можно оставить только корневую группу.
- **🟡 MINOR — разнобой нижних границ:** `pydantic>=2` (web-test) vs
  `pydantic>=2.6` (catalog, browser, shared-py); `playwright>=1.40`
  продублирован в browser (deps) и parsers (extra).
- **🟡 MINOR — web-test единственный на hatchling**, остальные на
  setuptools. Осознанно или исторически — стоит унифицировать или
  прокомментировать.
- Версии Python согласованы: `requires-python >=3.12` везде,
  `.python-version=3.12`, ruff `target-version=py312`, базовые образы
  `python:3.12-slim`. `uv.lock` актуален (pymorphy3 из последнего CAT-17
  в локе есть, mtime лока новее всех pyproject).
- Ruff-конфиг разумный (F/E/W/I, line-length 100, исключены
  alembic/versions и frontend).

## 4. bin/*.sh

- **🟠 MAJOR — hook-скрипты `bin/block-env-edit.sh` и `bin/ruff-on-edit.sh`
  не исполняемые (`-rw-r--r--`)**, при этом прописаны в
  `.claude/settings.json` как PreToolUse/PostToolUse-команды. Запуск
  `bin/block-env-edit.sh` даст «permission denied» (exit 126) → хук тихо
  не работает: **защита `.env` от перезаписи и авто-ruff фактически
  отключены**. Фикс: `chmod +x`.
- **🟠 MAJOR — блокирующие хуки используют `exit 1`, а PreToolUse в Claude
  Code блокирует tool-call только на `exit 2`** (`bin/block-env-edit.sh`,
  `bin/check-alembic-heads.sh`; exit 1 = non-blocking warning). Даже после
  chmod guard'ы будут только ругаться в stderr, не блокируя. Стоит
  перепроверить на актуальной версии Claude Code и заменить на `exit 2`.
- **🟡 MINOR:** `test-all.sh` и `backup-catalog.sh` — только `set -e`,
  без `-u`/`-o pipefail` (у check-alembic-heads.sh, для сравнения, полный
  `set -euo pipefail`). `backup-catalog.sh` хардкодит
  `DB_USER=catalog`/`DB_NAME=catalog` вместо чтения `.env` — сломается
  молча при смене кредов.
- **🟡 MINOR:** 8 разовых probe-скриптов (`bin/probe_avito_*.py`,
  `bin/probe_wb*.py`, май) лежат вперемешку с инфра-скриптами; половина
  даже без exec-бита. По собственной конвенции репо им место в `.scratch/`.
- Логика самих скриптов корректна (ротация бэкапов, restore с
  подтверждением, обход pytest-коллизий — всё аккуратно).

## 5. .env.example

- Реальных секретов нет — `BGG_API_TOKEN=your-bgg-token-here` плейсхолдер,
  пароли только дефолтные dev (`catalog/catalog`). ✅
- **🟡 MINOR — неполнота:** `WB_IMPERSONATE` читается кодом parsers
  (и упомянут в roadmap), но в `.env.example` отсутствует. Отсутствуют и
  `BGG_FAMILY_CASCADE_*` (есть в `catalog/config.py`).
- **🟡 MINOR — мусор в реальном `.env`:** `AVITO_COOKIES` больше не
  читается кодом (осталось от до-L0 эпохи) — кандидат на чистку вручную.
- **🟡 MINOR:** `catalog/config.py` использует `env_file=".env"`
  (относительный путь) — при host-запуске из `services/catalog/` (pytest)
  корневой `.env` не подхватится. Работает, потому что дефолты совпадают,
  но это неочевидное поведение.
- Главная проблема .env — не сам файл, а то, что compose не форвардит
  половину его переменных (см. п.1, MAJOR).

## 6. CI / автоматизация

- **🟠 MAJOR — CI отсутствует полностью:** нет `.github/`, нет
  `.pre-commit-config.yaml`. Вся автоматизация качества — три
  Claude-hook'а, из которых два не исполняемые, а блокирующая семантика
  (exit 1) не работает (п.4). Итог: ruff и тесты не гоняются нигде
  принудительно; при этом комментарии в `check-alembic-heads.sh` и roadmap
  ссылаются на «CI / staging», которых нет. Минимальный GitHub Actions
  (ruff + `bin/test-all.sh` + `docker compose config`) закрыл бы дыру.
- `.claude/settings.json` permissions-список разумный; `.mcp.json` с
  connection-string `postgresql://catalog:catalog@localhost:5433`
  закоммичен — dev-креды, приемлемо, но стоит помнить.

## 7. Документация vs реальность

- **🟠 MAJOR — roadmap протух (не обновлялся с 2026-05-23, сегодня 2026-07-10):**
  - `docs/roadmap.md:302-307` — **PRS-4**: удаление
    `services/parsers/DEPRECATED/chrome-extension/` с целевой датой
    **2026-06-15** — просрочено почти на месяц; «перепроверить через месяц»
    от 2026-05-18 тоже не сделано. Папка на месте (28K). Блокер
    (success ratio Avito L0 ≥95%) не перепроверен — задача требует решения:
    удалить или перенести дату с новым замером.
  - `docs/roadmap.md:193-195` — **WT-F9.1**: удалить redirect `/parsers`
    «после 2026-06-10» — просрочено.
  - Секция «Сейчас в работе» ссылается на ветку `feat/admin-panel-redesign`,
    которой нет в `git branch` (есть `feat/wt-redesign-rollout`,
    `feat/wt-f11-drawer`).
- **🟠 MAJOR — корневой CLAUDE.md расходится с реальностью:**
  «3 backend-сервиса» и карта из 3 сервисов при 4 фактических (browser);
  «`docker compose ps` — все 4 healthy» неверно для parsers (нет
  healthcheck); в списке портов нет 8003. `docs/architecture.md` — та же
  картина («из трёх сервисов», browser не упомянут).
- Битых ссылок из числа подозрительных **не найдено**:
  `docs/architecture.md`, `docs/parallel-agents.md`,
  `services/web-test/PLAN.md`, все `services/*/CLAUDE.md` (кроме browser)
  существуют. ✅
- Devlog в порядке: верхняя запись 2026-05-27 соответствует последнему
  коммиту, формат соблюдён.

## 8. Git-гигиена

- **🟠 MAJOR — незакоммиченная правка висит ~6 недель:**
  `services/parsers/parsers/api.py` (+15/−46) — отключение
  OnlineTrade-парсера, датированное в комментарии 2026-05-23, до сих пор
  не в истории. Риск потерять при любом reset/checkout; плюс роняет
  консистентность доков (архитектура/README всё ещё считают источники
  по-старому).
- История чистая: крупнейший blob — `uv.lock` (455KB), бинарей/дампов в
  истории нет. ✅
- `.gitignore` работает (проверено `git check-ignore`): `.env`, `*.sqlite`,
  `services/*/data/`, `.scratch/`, `.venv/`, `node_modules/` —
  игнорируются; `egg-info`/`__pycache__` не затреканы. ✅ Дампы >5MB лежат
  только в игнорируемом `.scratch/backups/`. Стрей-`.venv` в сервисах нет.
  Единственный worktree — main.

## 9. packages/ и apps/

- `apps/` — пустая заготовка с честным README, протухшего кода нет. ✅
- `packages/shared-py` — живой member (bg_shared/ingest.py, используется
  catalog и parsers). **🟡 MINOR:** `packages/README.md` протух — пишет
  «Сейчас пусто. В будущем сюда приедут packages/shared-py… Сейчас
  IngestRequest дублируется» — а shared-py уже существует и дублирование
  устранено (о чём говорят комментарии в pyproject обоих сервисов).

## Главные выводы

1. **Самая опасная находка — тихая потеря данных web-test**: рассинхрон
   `DB_PATH` (compose/Dockerfile) vs `PORTAL_DB_PATH` (код) оставляет
   volume `portal-data` пустым; БД портала живёт внутри контейнера и
   умирает при пересоздании. Чинится одной строкой в compose.
2. **`.env` как панель управления — иллюзия в Docker-режиме**: compose
   пробрасывает лишь часть переменных, а весь ML/matching-блок catalog и
   WB/proxy/timeout-блок parsers, подробно расписанные в `.env.example`,
   до контейнеров не доходят. Нужно либо форвардить (`env_file:`/явные
   строки), либо честно пометить их «host-run only».
3. **Защитная автоматизация сломана и не подстрахована**: два из трёх
   Claude-hook'ов не исполняемые, блокировка построена на `exit 1` вместо
   `exit 2`, а CI и pre-commit отсутствуют вовсе — ruff/тесты/alembic-heads
   фактически ни на чём не enforced.
4. **services/browser — «сервис-призрак»**: полноценный участник compose и
   workspace, отсутствующий во всей верхнеуровневой документации
   (CLAUDE.md, README, architecture.md) и без собственного CLAUDE.md —
   надо ввести его в карту сервисов.
5. **Процессная гигиена просела с конца мая**: просроченные чекпоинты
   roadmap (PRS-4 от 2026-06-15, WT-F9.1), незакоммиченное отключение
   OnlineTrade и устаревшие README/architecture — стоит сделать один
   «санитарный» проход: закоммитить diff, актуализировать roadmap/доки,
   chmod +x хукам, добавить healthcheck parsers.

При этом база крепкая: чистая git-история, рабочий .gitignore, грамотный
.dockerignore, продуманные compose-профили и комментарии, аккуратные
скрипты бэкапа — большинство проблем — это дрейф документации и
«недокрученные» связки, а не архитектурные ошибки.
