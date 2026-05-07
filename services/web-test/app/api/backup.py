"""Backup каталога через bin/backup-catalog.sh.

Запускает существующий shell-скрипт (`pg_dump` внутри контейнера bg-postgres)
из FastAPI как subprocess и возвращает информацию о созданном файле.

Подводный камень: скрипт делает `docker exec bg-postgres pg_dump`, поэтому
для работы эндпоинта нужно, чтобы у процесса web-test был доступ к Docker
демону. На хосте (uvicorn --reload) — работает из коробки. В Docker-варианте
web-test по умолчанию доступа к docker socket нет — endpoint вернёт 500.
Лечится монтированием `/var/run/docker.sock` в `docker-compose.yml`, но это
сознательно не делается без явного запроса (повышение привилегий).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/catalog", tags=["catalog-backup"])


def _resolve_repo_root() -> Path:
    """Поднимаемся вверх по дереву пока не найдём `bin/backup-catalog.sh`.

    Так робастнее, чем хардкод `parents[3]` — если файл переедет, ошибка
    станет явной (и легко чинится через env override).
    """
    override = os.getenv("BOARDGAMES_REPO_ROOT")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "bin" / "backup-catalog.sh").exists():
            return parent
    # fallback — будет ясно по сообщению
    return here.parents[4]


REPO_ROOT = _resolve_repo_root()
SCRIPT = REPO_ROOT / "bin" / "backup-catalog.sh"
BACKUP_DIR = REPO_ROOT / ".scratch" / "backups"


def _file_info(path: Path) -> dict:
    st = path.stat()
    # mtime как ISO-8601 в UTC — фронт сам выберет локаль для отображения
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    return {
        "name": path.name,
        "size_bytes": st.st_size,
        "modified_at": mtime,
    }


@router.post("/backup")
async def create_backup() -> dict:
    """Запустить pg_dump через bin/backup-catalog.sh.

    Backup занимает несколько секунд для каталога ~162K игр, поэтому
    держим клиента на проводе и возвращаем результат синхронно. Таймаут
    10 минут — pg_dump custom format на большом каталоге всё равно укладывается.
    """
    if not SCRIPT.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Скрипт не найден: {SCRIPT}. Установите BOARDGAMES_REPO_ROOT.",
        )

    proc = await asyncio.create_subprocess_exec(
        "bash",
        str(SCRIPT),
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail="Backup превысил 10-минутный таймаут") from e

    stdout = stdout_b.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        # Самая частая причина — bg-postgres не запущен или нет доступа к docker.
        raise HTTPException(
            status_code=500,
            detail=f"backup-catalog.sh exit={proc.returncode}\n{stdout[-2000:]}",
        )

    # Берём самый свежий файл в каталоге — скрипт создаёт catalog_<TS>.dump
    dumps = sorted(BACKUP_DIR.glob("catalog_*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dumps:
        raise HTTPException(
            status_code=500,
            detail=f"Backup завершился ok, но файл не найден в {BACKUP_DIR}",
        )
    latest = dumps[0]
    return {
        "status": "ok",
        "file": _file_info(latest),
        "log_tail": stdout[-1000:],
    }


@router.get("/backups")
async def list_backups() -> dict:
    """Список существующих backup'ов (новые сверху)."""
    if not BACKUP_DIR.exists():
        return {"items": [], "dir": str(BACKUP_DIR)}
    items = [
        _file_info(p)
        for p in sorted(
            BACKUP_DIR.glob("catalog_*.dump"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    ]
    return {"items": items, "dir": str(BACKUP_DIR)}
