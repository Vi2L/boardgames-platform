"""Репозиторий BGG: запись BGG-данных в canonical Game + satellite GameBgg.

Стратегия записи (см. план этапа 2 в `~/.claude/plans/modular-knitting-sloth.md`):

- `games` — каноническая запись. Используем COALESCE-логику: при INSERT
  заливаем все поля; при UPDATE сохраняем то, что уже было непустым (не
  затираем ручные правки оператора). source: csv-ranks → bgg при первом
  enrich'е через xml-api, потом не понижается.

- `game_bgg` — satellite: полностью переписываем при каждом enrich'е, BGG
  здесь источник истины. fetched_at используется для resume-state в
  `enrich_batch` (пропускаем игры, обогащённые недавно).

- `game_aliases` — для каждого alternate name из BGG `INSERT ON CONFLICT
  DO NOTHING` по `uq_alias_per_game`. source='bgg', language='en',
  verified=False — alternate names в BGG преимущественно англоязычные.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.models import Game, GameAlias, GameBgg
from catalog.parsers.bgg.models import BggGame


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def upsert_bgg_data(session: AsyncSession, bgg: BggGame) -> int:
    """Идемпотентный upsert одной BGG-игры. Возвращает `game_id`.

    1. **games** — INSERT or UPDATE по `bgg_id` (UNIQUE). На UPDATE используем
       COALESCE: новое значение применяется только если текущее пусто.
       Так не теряются ручные правки оператора.

    2. **game_bgg** — UPSERT по `game_id` (PK). Полностью перезаписываем
       поля из XML-API (BGG здесь авторитетный источник). `source='xml-api'`,
       `fetched_at=now()`. raw на этапе 2 пустой dict; этап 3 (full seed)
       начнёт заполнять полным XML-blob'ом для аудита.

    3. **game_aliases** — для каждого alternate name `INSERT ON CONFLICT DO
       NOTHING` (на `uq_alias_per_game`). Безопасно для повторных прогонов:
       новый alias добавится, существующий пропустится.

    Не коммитит: caller управляет транзакцией. Это позволяет `enrich_batch`
    делать commit раз в N игр, экономя WAL.
    """
    games_t = Game.__table__
    bgg_t = GameBgg.__table__
    alias_t = GameAlias.__table__

    # ── 1. games ──────────────────────────────────────────────────────────
    # При INSERT (новая игра) — заполняем всё. При UPDATE — сохраняем не-NULL.
    games_insert = pg_insert(games_t).values(
        slug=slug_from_title(bgg.title, bgg.bgg_id),
        title=bgg.title,
        year=bgg.year,
        designers=bgg.designers or None,
        publishers=bgg.publishers or None,
        players_min=bgg.players_min,
        players_max=bgg.players_max,
        age_min=bgg.age_min,
        playtime_min=bgg.playtime_min,
        playtime_max=bgg.playtime_max,
        bgg_id=bgg.bgg_id,
        cover_url=bgg.cover_url,
        description=bgg.description,
        source="bgg",
        status="published",
    )
    excluded = games_insert.excluded
    games_stmt = games_insert.on_conflict_do_update(
        index_elements=["bgg_id"],
        set_={
            # title всегда обновляется — это primary name из BGG, может
            # измениться при ребрендинге. У нас alias-таблица сохранит старое
            # как историю.
            "title": excluded.title,
            "year": func.coalesce(games_t.c.year, excluded.year),
            "designers": func.coalesce(games_t.c.designers, excluded.designers),
            "publishers": func.coalesce(games_t.c.publishers, excluded.publishers),
            "players_min": func.coalesce(games_t.c.players_min, excluded.players_min),
            "players_max": func.coalesce(games_t.c.players_max, excluded.players_max),
            "age_min": func.coalesce(games_t.c.age_min, excluded.age_min),
            "playtime_min": func.coalesce(games_t.c.playtime_min, excluded.playtime_min),
            "playtime_max": func.coalesce(games_t.c.playtime_max, excluded.playtime_max),
            "cover_url": func.coalesce(games_t.c.cover_url, excluded.cover_url),
            "description": func.coalesce(games_t.c.description, excluded.description),
            # source: 'bgg-ranks' → 'bgg' при первом xml-enrich; после уже
            # 'bgg', не «понижается». Реализуем так: новое значение применяется
            # только если текущее = 'bgg-ranks' или 'auto-from-parsers' (слабые
            # источники). Иначе оставляем (manual / merged / уже bgg).
            "source": case(
                (games_t.c.source.in_(["bgg-ranks", "auto-from-parsers"]), excluded.source),
                else_=games_t.c.source,
            ),
            "updated_at": _utcnow(),
        },
    ).returning(games_t.c.id)

    game_id = (await session.execute(games_stmt)).scalar_one()

    # ── 2. game_bgg (satellite) ──────────────────────────────────────────
    # Полная перезапись XML-полей. ranks (rank/bayes_average/...) НЕ
    # трогаются — их источник CSV-выгрузка, она уже была применена через
    # `import_bgg_ranks.py` и обновляется отдельным процессом.
    bgg_insert = pg_insert(bgg_t).values(
        game_id=game_id,
        bgg_id=bgg.bgg_id,
        description=bgg.description,
        designers=bgg.designers or None,
        publishers=bgg.publishers or None,
        mechanics=bgg.mechanics or None,
        categories=bgg.categories or None,
        min_players=bgg.players_min,
        max_players=bgg.players_max,
        min_age=bgg.age_min,
        playtime_min=bgg.playtime_min,
        playtime_max=bgg.playtime_max,
        image_url=bgg.cover_url,
        thumbnail_url=bgg.thumbnail_url,
        raw={},
        source="xml-api",
        fetched_at=_utcnow(),
    )
    bgg_excluded = bgg_insert.excluded
    bgg_stmt = bgg_insert.on_conflict_do_update(
        index_elements=["game_id"],
        set_={
            "description": bgg_excluded.description,
            "designers": bgg_excluded.designers,
            "publishers": bgg_excluded.publishers,
            "mechanics": bgg_excluded.mechanics,
            "categories": bgg_excluded.categories,
            "min_players": bgg_excluded.min_players,
            "max_players": bgg_excluded.max_players,
            "min_age": bgg_excluded.min_age,
            "playtime_min": bgg_excluded.playtime_min,
            "playtime_max": bgg_excluded.playtime_max,
            "image_url": bgg_excluded.image_url,
            "thumbnail_url": bgg_excluded.thumbnail_url,
            # raw на этапе 2 не пишем — пустой dict уже стоит. На этапе 3
            # сюда пойдёт полный XML payload для аудита.
            "source": "xml-api",  # не понижаем обратно до csv-ranks
            "fetched_at": _utcnow(),
        },
    )
    await session.execute(bgg_stmt)

    # ── 3. game_aliases ──────────────────────────────────────────────────
    # ON CONFLICT DO NOTHING — повторный прогон не плодит дубли. Уникальный
    # ключ по (game_id, alias_norm), где alias_norm — generated column.
    for alias in bgg.aliases:
        await session.execute(
            pg_insert(alias_t)
            .values(
                game_id=game_id,
                alias=alias,
                source="bgg",
                language="en",
                verified=False,
            )
            .on_conflict_do_nothing(constraint="uq_alias_per_game")
        )

    return game_id
