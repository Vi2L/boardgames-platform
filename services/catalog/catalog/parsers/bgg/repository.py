"""Репозиторий BGG: формирование slug'ов и (на этапе 2) async-upsert в БД.

На текущем этапе — только slug-генератор. Upsert живёт в legacy-функции
`routers/imports.py:_upsert_game_from_bgg`; перенести её сюда — задача
этапа 2 плана (вместе с записью в satellite-таблицу `game_bgg`).
"""
from __future__ import annotations

import re


def slug_from_title(title: str, bgg_id: int) -> str:
    r"""Генерируем slug из английского названия + bgg_id (на случай коллизий).

    Slug должен подходить под regex `^[a-z0-9][a-z0-9\-]*$` (см. `GameCreate.slug`).
    Кириллица и прочие не-ASCII — превращаются в дефис, в худшем случае
    останется только bgg_id-фоллбэк (`game-822`).
    """
    base = title.lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    if not base or not base[0].isalnum():
        base = f"game-{bgg_id}"
    return f"{base}-{bgg_id}"
