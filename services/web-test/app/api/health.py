"""Health-check для фронта.

Возвращает не только своё состояние («приложение поднято»), но и проверяет
доступность вышестоящего parsers API. Это нужно для индикатора в сайдбаре —
без него пользователь видит «всё ОК» при работающем фронте, но получает
ошибку только в момент реального запроса.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_parsers_client
from app.parsers_client import ParsersClient

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    client: Annotated[ParsersClient, Depends(get_parsers_client)],
) -> dict:
    """Проверка здоровья портала и подключения к parsers.

    Не падает 5xx даже если parsers недоступен — мы хотим, чтобы фронт
    мог получить статус и показать плашку «parsers down», а не пустой экран.
    """
    info: dict = {"app": "ok", "parsers_url": client.base_url}
    try:
        # /stores на стороне parsers возвращает кешированный список — самый
        # дешёвый запрос для пинга. Network-IO здесь оправдан: мы хотим знать,
        # реально ли можно достучаться, а не просто иметь URL в конфиге.
        await client.get_stores()
        info["parsers_api"] = "ok"
    except Exception as exc:  # noqa: BLE001 — намеренно ловим всё для health
        info["parsers_api"] = "unreachable"
        info["error"] = str(exc)
    return info
