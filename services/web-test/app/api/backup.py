"""Backup каталога через сетевой pg_dump.

Запускает `pg_dump` как subprocess внутри web-test контейнера и подключается
к postgres напрямую по сети `bg` (postgres:5432). Никакого docker socket'а
и shell-обёрток не нужно — credentials берутся из стандартных PG*
переменных, файл пишется в `BACKUP_DIR` (по умолчанию `/backups`,
смонтировано как bind на `<repo>/.scratch/backups`).

На хосте без `BACKUP_DIR` (uvicorn для отладки) — фолбэк на
`<repo>/.scratch/backups`. Если на маке нет `pg_dump` в PATH —
endpoint вернёт 500 с явным сообщением; для повседневной работы
канонический путь — Docker.

CLI-аналог: `bin/backup-catalog.sh` (через `docker exec`) — оставлен для
restore-сценариев, которые из UI намеренно не выставляем.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/catalog", tags=["catalog-backup"])

# Сколько свежих дампов хранить — то же, что в bin/backup-catalog.sh.
KEEP = 10
# 10 минут — pg_dump custom format на каталоге ~162K игр укладывается в ~10 сек,
# но запас нужен на случай долгих транзакций / большого роста БД.
TIMEOUT_S = 600


def _backup_dir() -> Path | None:
    """Куда писать дамп.

    1) Явный override через `BACKUP_DIR` (Docker → `/backups`).
    2) Иначе — поднимаемся вверх по дереву пока не найдём маркер репо
       (`bin/backup-catalog.sh`) и используем `<repo>/.scratch/backups`.
       Это покрывает host-uvicorn-режим без необходимости env override'а.
    """
    if env := os.getenv("BACKUP_DIR"):
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "bin" / "backup-catalog.sh").exists():
            return parent / ".scratch" / "backups"
    return None


def _file_info(path: Path) -> dict:
    st = path.stat()
    return {
        "name": path.name,
        "size_bytes": st.st_size,
        "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }


def _rotate(target_dir: Path) -> int:
    """Оставляем KEEP свежих дампов, остальные удаляем. Возвращаем сколько удалено."""
    dumps = sorted(
        target_dir.glob("catalog_*.dump"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in dumps[KEEP:]:
        old.unlink(missing_ok=True)
        removed += 1
    return removed


@router.post("/backup")
async def create_backup() -> dict:
    target_dir = _backup_dir()
    if target_dir is None:
        raise HTTPException(
            status_code=500,
            detail="BACKUP_DIR не задан и репо не найдено по маркеру bin/backup-catalog.sh.",
        )
    target_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = target_dir / f"catalog_{ts}.dump"

    # PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE — стандартные env'ы libpq;
    # их читает сам pg_dump, флаги передавать не нужно. Это намеренно: так
    # тот же контейнер можно навести на любой postgres сменой переменной.
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            "-Fc",            # custom format — сжатый, поддерживает parallel restore
            "--no-owner",     # не привязываемся к роли владельца — переносимо
            "-f",
            str(out),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as e:
        # postgresql-client не установлен (редкий случай host-режима без psql)
        raise HTTPException(
            status_code=500,
            detail=(
                "pg_dump не найден в PATH. В Docker-режиме — пересоберите "
                "образ web-test (postgresql-client ставится в Dockerfile). "
                "На хосте — установите libpq/postgres-client."
            ),
        ) from e

    try:
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        out.unlink(missing_ok=True)
        raise HTTPException(
            status_code=504, detail=f"pg_dump превысил таймаут {TIMEOUT_S}s",
        ) from e

    if proc.returncode != 0:
        # Если pg_dump упал — не оставляем мусорный 0-байтный файл
        out.unlink(missing_ok=True)
        log_tail = stdout_b.decode("utf-8", errors="replace")[-2000:]
        raise HTTPException(
            status_code=500,
            detail=f"pg_dump exit={proc.returncode}\n{log_tail}",
        )

    rotated = _rotate(target_dir)
    return {
        "status": "ok",
        "file": _file_info(out),
        "rotated": rotated,  # сколько старых дампов удалено по политике KEEP=10
    }


@router.get("/backups")
async def list_backups() -> dict:
    """Список существующих backup'ов (новые сверху)."""
    target_dir = _backup_dir()
    if target_dir is None or not target_dir.exists():
        return {"items": [], "dir": str(target_dir) if target_dir else None}
    items = [
        _file_info(p)
        for p in sorted(
            target_dir.glob("catalog_*.dump"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    ]
    return {"items": items, "dir": str(target_dir)}
