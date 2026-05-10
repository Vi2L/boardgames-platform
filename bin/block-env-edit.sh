#!/usr/bin/env bash
# PreToolUse guard: блокирует прямое редактирование .env через Edit/Write.
#
# .env содержит пароли PostgreSQL, API-ключи и другие секреты.
# Прямая запись через Claude Code инструменты — потенциальная потеря секретов
# (перезапись, случайный commit). Для изменения шаблона используйте .env.example.
#
# Толерантность: если не удалось распарсить stdin — пропускаем (не блокируем).

set -euo pipefail

# Нет stdin (ручной запуск) — выходим
[ ! -t 0 ] || exit 0

json=$(cat)
file_path=$(python3 -c "
import json, sys
d = json.loads(sys.stdin.read() or '{}')
print(d.get('tool_input', {}).get('file_path', ''))
" <<<"$json" 2>/dev/null || echo "")

# Проверяем: файл заканчивается на .env (не .env.example, не .env.local и т.п.)
if [[ "$file_path" == *.env && "$file_path" != *.env.* ]]; then
    echo "" >&2
    echo "❌ Редактирование .env заблокировано." >&2
    echo "" >&2
    echo "   .env содержит секреты (пароли БД, API-ключи)." >&2
    echo "   Для изменения шаблона переменных используйте .env.example" >&2
    echo "   Для изменения значений — отредактируйте .env вручную в терминале." >&2
    echo "" >&2
    exit 1
fi

exit 0
