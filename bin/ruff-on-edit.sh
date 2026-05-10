#!/usr/bin/env bash
# PostToolUse hook: запускает ruff check + format после редактирования .py файлов.
#
# Срабатывает на Edit и Write. Читает stdin JSON {"tool_input": {"file_path": "..."}}
# и применяет ruff только к Python-файлам. Ошибки ruff не блокируют работу
# (exit 0 всегда) — хук информирует, но не прерывает.
#
# Зачем: ruff настроен (line-length=100, F/E/W/I), но без хука нарушения молча
# накапливаются. Хук заменяет ручной `uv run ruff check --fix` после каждого edit.

set -euo pipefail

# Нет stdin (ручной запуск) — выходим
[ ! -t 0 ] || exit 0

json=$(cat)
file_path=$(python3 -c "
import json, sys
d = json.loads(sys.stdin.read() or '{}')
print(d.get('tool_input', {}).get('file_path', ''))
" <<<"$json" 2>/dev/null || echo "")

# Обрабатываем только .py файлы
[[ "$file_path" == *.py ]] || exit 0

# Файл должен реально существовать
[ -f "$file_path" ] || exit 0

# ruff check --fix: автоисправление lint-нарушений (imports, whitespace, etc.)
uv run ruff check --fix "$file_path" 2>/dev/null || true

# ruff format: форматирование (аналог black, но быстрее)
uv run ruff format "$file_path" 2>/dev/null || true

exit 0
