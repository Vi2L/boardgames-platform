#!/usr/bin/env bash
# Запускает pytest для всех сервисов последовательно, каждый в отдельном
# процессе. Это обходит pytest collision'ы (одноимённые `tests.conftest`
# в нескольких services/*).
#
# Использование:
#   bin/test-all.sh             # запустить все
#   bin/test-all.sh -v          # с verbose
#   bin/test-all.sh -k "auth"   # фильтр по имени
#
# Возвращает ненулевой код, если хоть один сервис упал.

set -e
cd "$(dirname "$0")/.."

ROOT="$(pwd)"
FAILED=()

for SERVICE in catalog parsers web-test; do
    echo ""
    echo "==================================================================="
    echo "  Тесты services/$SERVICE"
    echo "==================================================================="
    if (cd "$ROOT/services/$SERVICE" && uv run pytest "$@"); then
        echo "✓ services/$SERVICE — passed"
    else
        echo "✗ services/$SERVICE — FAILED"
        FAILED+=("$SERVICE")
    fi
done

echo ""
echo "==================================================================="
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "  Итого: все 3 сервиса прошли тесты"
    exit 0
else
    echo "  Итого: упали ${#FAILED[@]} из 3 — ${FAILED[*]}"
    exit 1
fi
