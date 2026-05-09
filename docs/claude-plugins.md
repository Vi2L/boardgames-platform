# Claude Code — установленные плагины

Все плагины установлены глобально (scope: user) и работают во всех проектах.
После установки или обновления нужен **перезапуск Claude Code**.

---

## 1. explanatory-output-style

**Тип:** SessionStart hook  
**Источник:** `claude-plugins-official` v1.0.0

Воспроизводит устаревший режим `"outputStyle": "Explanatory"`. При старте
сессии добавляет инструкции, которые заставляют Claude вставлять обучающие
блоки вокруг написанного кода:

```
`★ Insight ─────────────────────────────────────`
[2-3 ключевых момента про реализацию / паттерн / решение]
`─────────────────────────────────────────────────`
`
```

Инсайты фокусируются на специфике конкретного кода — не на общих концепциях.
Блоки появляются **до и после** написания кода, не в конце.

> ⚠️ Увеличивает количество токенов на сессию.

---

## 2. frontend-design

**Тип:** Skill (автоматически активируется для фронтенд-задач)  
**Источник:** `claude-plugins-official`

Направляет создание фронтенд-интерфейсов с продуманной дизайн-концепцией
вместо шаблонного «AI-вида».

**Что меняется в подходе:**

- **Типографика** — нестандартные, контекстные шрифты. Никаких Inter / Roboto / Arial.
- **Цвет** — чёткая палитра с острыми акцентами вместо пресных равномерных схем.
- **Анимации** — один хорошо срежиссированный вход лучше десятка случайных hover-эффектов. CSS-first, Motion library для React.
- **Композиция** — асимметрия, диагональный поток, grid-breaking элементы.
- **Фоны** — gradient meshes, noise, геометрия, grain-оверлеи вместо solid color.

**Запрещено внутри скилла:** purple-gradient-on-white, Space Grotesk, предсказуемые layout-паттерны.

**Как использовать:** просто описывай задачу, скилл срабатывает автоматически:

```
"создай дашборд для музыкального стриминга"
"сделай лендинг для AI-стартапа"
"построй тёмный settings panel"
```

---

## 3. claude-code-setup

**Тип:** Skill (вызывается по запросу)  
**Источник:** `claude-plugins-official` v1.0.0  
**Автор:** Isabella He (Anthropic)

Анализирует кодовую базу и рекомендует подходящие автоматизации для Claude Code.
Только читает файлы — ничего не меняет.

**Категории рекомендаций:**

| Категория | Примеры |
|---|---|
| MCP Servers | context7 (документация), Playwright (frontend-тесты) |
| Skills | Plan agent, frontend-design |
| Hooks | auto-format, auto-lint, блокировка sensitive-файлов |
| Subagents | security reviewer, performance reviewer |
| Slash Commands | /test, /pr-review, /explain |

**Как использовать:**

```
"recommend automations for this project"
"help me set up Claude Code"
"what hooks should I use here?"
```

---

## 4. feature-dev

**Тип:** Slash command + специализированные агенты  
**Источник:** `claude-plugins-official`  
**Автор:** Sid Bidasaria (Anthropic)

Структурированный 7-фазный воркфлоу для разработки новых фич.
Вместо «просто пиши код» — сначала исследование, вопросы, архитектура, потом реализация и ревью.

**Запуск:**

```
/feature-dev Add user authentication with OAuth
/feature-dev Add rate limiting to API endpoints
```

### 7 фаз воркфлоу

| Фаза | Название | Что происходит |
|---|---|---|
| 1 | Discovery | Уточнение требований, формулировка задачи |
| 2 | Codebase Exploration | 2–3 параллельных агента `code-explorer` исследуют похожие фичи, архитектуру, паттерны |
| 3 | Clarifying Questions | Список вопросов по неясным местам — ждёт ответа перед продолжением |
| 4 | Architecture Design | 2–3 агента `code-architect` проектируют варианты: minimal / clean / pragmatic, Claude рекомендует один |
| 5 | Implementation | Реализация по выбранной архитектуре, только после явного подтверждения |
| 6 | Quality Review | 3 агента `code-reviewer` параллельно: DRY/simplicity, bugs/correctness, conventions |
| 7 | Summary | Итог: что сделано, ключевые решения, изменённые файлы, следующие шаги |

### Агенты (можно вызывать вручную)

```
"Launch code-explorer to trace how authentication works"
"Launch code-architect to design the caching layer"
"Launch code-reviewer to check my recent changes"
```

**Когда использовать:** новые фичи затрагивающие несколько файлов, неочевидные требования, сложные интеграции.  
**Не использовать для:** hotfix-ов, однострочных правок, тривиальных изменений.

---

## 5. context7

**Тип:** MCP Server (от Upstash)  
**Источник:** `claude-plugins-official`

Подключает MCP-сервер, который тянет актуальную документацию и примеры
прямо из исходных репозиториев библиотек — вместо обучающих данных модели.

**Запускается как:** `npx @upstash/context7-mcp` (требует Node.js / npx).

**Когда полезен:** вопросы про конкретную версию библиотеки, свежие API,
которые могут не совпадать с тем, что было в обучающих данных.

---

## 6. warp (warp@claude-code-warp)

**Тип:** Интеграция с терминалом Warp  
**Источник:** `claude-code-warp` v2.0.0

Плагин от команды Warp. Добавляет интеграцию Claude Code с терминалом Warp —
контекст из открытых вкладок, история команд и прочие возможности Warp AI.

---

## Управление плагинами

```bash
# Список всех установленных
claude plugin list

# Установить
claude plugin install <name>@claude-plugins-official

# Отключить (без удаления)
claude plugin disable <name>@claude-plugins-official

# Включить снова
claude plugin enable <name>@claude-plugins-official

# Удалить
claude plugin uninstall <name>@claude-plugins-official

# Обновить
claude plugin update <name>@claude-plugins-official

# Список доступных маркетплейсов
claude plugin marketplace list
```
