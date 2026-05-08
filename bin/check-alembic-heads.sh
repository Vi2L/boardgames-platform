#!/usr/bin/env bash
# Pre-commit guard для alembic heads (catalog).
#
# Hook'ается через .claude/settings.json:PreToolUse[Bash] перед каждым
# Bash-вызовом Claude Code. Скрипт читает stdin JSON со схемой
# {"tool_input":{"command":"..."}} и проверяет команду на git commit.
#
# Если коммитятся файлы в services/catalog/alembic/versions/ и
# `alembic heads` показывает > 1 голову — exit 1 (блок) с понятным
# сообщением. Иначе exit 0 (no-op).
#
# Зачем: ловит two heads до коммита, а не на CI / при `alembic upgrade`.
# Сценарий, который защищаем — два агента в параллельных worktrees
# делают `alembic revision` одновременно и оба попадают в одну голову.
# См. docs/parallel-agents.md §8.2 / §10.5.
#
# Толерантность: если alembic не отработал (БД недоступна, скрипт
# упал) — пропускаем, не блокируем коммит. Финальную проверку всё
# равно сделает CI / `alembic upgrade head` на staging.

set -euo pipefail

# 1. Если есть stdin (вызов из Claude Code hook) — фильтруем по командам.
#    Если stdin'а нет (ручной запуск из терминала) — проходим к проверке
#    напрямую.
if [ ! -t 0 ]; then
    json=$(cat)
    command=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read() or '{}'); print(d.get('tool_input',{}).get('command',''))" <<<"$json" 2>/dev/null || echo "")
    # Hook срабатывает на любой Bash; нас интересует только git commit.
    if [[ ! "$command" =~ git[[:space:]]+commit ]]; then
        exit 0
    fi
fi

# 2. Без staged migrations — пропускаем (быстрый путь для всех остальных
#    коммитов).
if ! git diff --cached --name-only --diff-filter=ACMR 2>/dev/null \
        | grep -q "^services/catalog/alembic/versions/.*\.py$"; then
    exit 0
fi

# 3. Считаем количество heads. alembic heads — статическая операция,
#    читает только файлы в versions/, к БД не подключается.
ROOT=$(git rev-parse --show-toplevel)
heads_output=$(cd "$ROOT/services/catalog" && \
    uv run --package boardgames-catalog alembic heads 2>&1 || true)

# Если alembic не отработал — не блокируем (см. толерантность выше).
if [ -z "$heads_output" ]; then
    exit 0
fi

heads_count=$(echo "$heads_output" | grep -c "(head)" || true)

if [ "${heads_count:-0}" -gt 1 ]; then
    {
        echo ""
        echo "❌ Обнаружено несколько alembic heads (${heads_count}):"
        echo ""
        echo "$heads_output" | sed 's/^/    /'
        echo ""
        echo "Это значит, что в services/catalog/alembic/versions/ две"
        echo "конкурирующие миграции с одинаковым down_revision. При"
        echo "alembic upgrade head будет ошибка."
        echo ""
        echo "Как починить — docs/parallel-agents.md §8.2."
    } >&2
    exit 1
fi

exit 0
