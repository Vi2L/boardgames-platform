#!/usr/bin/env bash
# Backup и restore Postgres catalog'а через pg_dump/pg_restore.
#
# Использование:
#   bin/backup-catalog.sh                       # создать backup, оставить 10 последних
#   bin/backup-catalog.sh --keep 30             # хранить 30 backups вместо 10
#   bin/backup-catalog.sh --list                # показать все backup'ы
#   bin/backup-catalog.sh --restore <file>      # восстановить БД из файла
#   bin/backup-catalog.sh --restore latest      # восстановить из самого свежего
#
# Файлы хранятся в `.scratch/backups/catalog_YYYYMMDD_HHMMSS.dump` — папка
# в `.gitignore`, не утечёт в репо. Формат — pg_dump custom (-Fc), сжатый,
# поддерживает parallel restore.
#
# Регулярный backup можно повесить на cron хоста:
#   0 3 * * *  cd /Users/vitaliy/Projects/boardgames-platform && bin/backup-catalog.sh

set -e

# cron на macOS стартует с минимальным PATH=/usr/bin:/bin, и `docker` в нём
# не находится (он в /usr/local/bin на Intel или /opt/homebrew/bin на Apple
# Silicon). Расширяем PATH в начале — пусть скрипт работает одинаково и из
# терминала, и из cron.
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
BACKUP_DIR="$ROOT/.scratch/backups"
KEEP=10
CONTAINER=bg-postgres
DB_USER=catalog
DB_NAME=catalog

# --- args parsing ---
case "${1:-}" in
    --list)
        echo "Backups в $BACKUP_DIR:"
        ls -lhS "$BACKUP_DIR"/catalog_*.dump 2>/dev/null || echo "  (пусто)"
        exit 0
        ;;

    --restore)
        FILE="${2:-}"
        if [ -z "$FILE" ]; then
            echo "usage: bin/backup-catalog.sh --restore <file|latest>" >&2
            exit 1
        fi
        if [ "$FILE" = "latest" ]; then
            FILE=$(ls -1t "$BACKUP_DIR"/catalog_*.dump 2>/dev/null | head -1 || true)
            if [ -z "$FILE" ]; then
                echo "Нет backup'ов в $BACKUP_DIR" >&2
                exit 1
            fi
            echo "Использую самый свежий: $FILE"
        fi
        if [ ! -f "$FILE" ]; then
            echo "Файл не найден: $FILE" >&2
            exit 1
        fi

        echo "⚠  Восстанавливаю БД '$DB_NAME' из $FILE — это пересоздаст все таблицы."
        read -p "Продолжить? [y/N] " -n 1 -r REPLY
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Отменено."
            exit 0
        fi

        docker cp "$FILE" "$CONTAINER:/tmp/restore.dump"
        docker exec "$CONTAINER" pg_restore \
            --clean --if-exists --no-owner \
            -U "$DB_USER" -d "$DB_NAME" \
            /tmp/restore.dump
        docker exec "$CONTAINER" rm /tmp/restore.dump
        # catalog держит connection pool с prepared statements старой схемы
        docker compose restart catalog 2>&1 | tail -3
        echo "✓ Restore завершён"
        exit 0
        ;;

    --keep)
        if [ -z "${2:-}" ]; then
            echo "usage: bin/backup-catalog.sh --keep <N>" >&2
            exit 1
        fi
        KEEP="$2"
        ;;

    --help|-h)
        sed -n '2,16p' "$0" | sed 's/^# //;s/^#//'
        exit 0
        ;;

    "")
        : # обычный backup-режим, идём дальше
        ;;

    *)
        echo "Неизвестный флаг: $1" >&2
        echo "См. bin/backup-catalog.sh --help" >&2
        exit 1
        ;;
esac

# --- backup mode ---
mkdir -p "$BACKUP_DIR"

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Контейнер $CONTAINER не запущен. Поднимите его: docker compose --profile minimal up -d" >&2
    exit 1
fi

TS=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/catalog_${TS}.dump"

echo "Создаю $BACKUP_FILE..."
docker exec "$CONTAINER" pg_dump \
    -U "$DB_USER" -d "$DB_NAME" \
    -Fc --no-owner \
    -f /tmp/dump.tmp
docker cp "$CONTAINER:/tmp/dump.tmp" "$BACKUP_FILE"
docker exec "$CONTAINER" rm /tmp/dump.tmp

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "✓ Создан $BACKUP_FILE ($SIZE)"

# --- ротация ---
ALL=$(ls -1t "$BACKUP_DIR"/catalog_*.dump 2>/dev/null || true)
if [ -n "$ALL" ]; then
    COUNT=$(echo "$ALL" | wc -l | tr -d ' ')
    if [ "$COUNT" -gt "$KEEP" ]; then
        TO_REMOVE=$((COUNT - KEEP))
        echo "Ротация: оставляю $KEEP свежих, удаляю $TO_REMOVE старых"
        echo "$ALL" | tail -n +"$((KEEP + 1))" | xargs rm -v
    fi
fi

echo ""
echo "Все backup'ы:"
ls -lh "$BACKUP_DIR"/ 2>/dev/null
