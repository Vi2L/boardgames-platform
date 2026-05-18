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
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.models import (
    BggFamily,
    BggFamilyMember,
    Game,
    GameAlias,
    GameBgg,
)
from catalog.parsers.bgg.models import BggFamily as BggFamilyDC, BggGame


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


async def upsert_bgg_data(
    session: AsyncSession,
    bgg: BggGame,
    xml_text: str = "",
) -> int:
    """Идемпотентный upsert одной BGG-игры. Возвращает `game_id`.

    1. **games** — INSERT or UPDATE по `bgg_id` (UNIQUE). На UPDATE используем
       COALESCE: новое значение применяется только если текущее пусто.
       Так не теряются ручные правки оператора.

    2. **game_bgg** — UPSERT по `game_id` (PK). Полная перезапись XML-полей —
       BGG здесь источник истины. Сюда же входят `bayes_average`/`average`/
       `users_rated` (CAT-5: XML свежее CSV, который запаздывает на неделю).
       CSV-only поля (`rank`, `is_expansion`, `subtype_ranks`) НЕ
       перезаписываются — они приходят из ежемесячной выгрузки ranks.csv.

       `raw` (CAT-7) хранит `{"parsed": <asdict(BggGame)>, "xml": <raw item XML>}`
       для аудита и re-парсинга без повторных запросов к BGG. `xml_text=""` —
       fallback для legacy-вызовов через `routers/imports.py`, где сырой XML
       не пробрасывается.

       `bgg_stats_updated_at` — timestamp последнего XML-обогащения. Отдельно
       от `fetched_at`, чтобы CSV-импорт мог обновлять `fetched_at` (если
       захочет) без сбрасывания признака «обогащено через XML».

       `source='xml-api'` — флаг XML-территории; CSV больше не понижает его
       обратно до `csv-ranks` (см. `import_bgg_ranks.py` — `source` исключён
       из ON CONFLICT set_).

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
    # XML — источник истины для всех динамических метрик (CAT-5) + расширенных
    # полей (CAT-6) + raw blob (CAT-7). НЕ перезаписываются только CSV-only
    # поля: `rank`, `is_expansion`, `subtype_ranks` — они приходят из ежемесячной
    # boardgames_ranks.csv через import_bgg_ranks.
    now = _utcnow()
    raw_blob = {"parsed": asdict(bgg), "xml": xml_text}
    bgg_insert = pg_insert(bgg_t).values(
        game_id=game_id,
        bgg_id=bgg.bgg_id,
        # CSV-метрики, которые XML тоже отдаёт — после CAT-5 XML их перезаписывает.
        bayes_average=bgg.rating_bayes,
        average=bgg.rating_avg,
        users_rated=bgg.users_rated,
        # XML-only поля каталога (этап 2).
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
        # Расширенная статистика (CAT-5) — только в XML, CSV их не знает.
        average_weight=bgg.average_weight,
        num_weights=bgg.num_weights,
        # Polls (CAT-6).
        recommended_players=bgg.recommended_players,
        recommended_age=bgg.recommended_age,
        language_dependence=bgg.language_dependence,
        # Аудит (CAT-7).
        raw=raw_blob,
        bgg_stats_updated_at=now,
        source="xml-api",
        fetched_at=now,
    )
    bgg_excluded = bgg_insert.excluded
    bgg_stmt = bgg_insert.on_conflict_do_update(
        index_elements=["game_id"],
        set_={
            "bayes_average": bgg_excluded.bayes_average,
            "average": bgg_excluded.average,
            "users_rated": bgg_excluded.users_rated,
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
            "average_weight": bgg_excluded.average_weight,
            "num_weights": bgg_excluded.num_weights,
            "recommended_players": bgg_excluded.recommended_players,
            "recommended_age": bgg_excluded.recommended_age,
            "language_dependence": bgg_excluded.language_dependence,
            "raw": bgg_excluded.raw,
            "bgg_stats_updated_at": bgg_excluded.bgg_stats_updated_at,
            "source": "xml-api",  # не понижаем обратно до csv-ranks
            "fetched_at": bgg_excluded.fetched_at,
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

    # ── 4. bgg_families + bgg_family_members (CAT-8) ─────────────────────
    # Для каждой `boardgamefamily` связки из /thing:
    #   - upsert семьи (если впервые — только id+name, description=NULL,
    #     fetched_at=now: scheduler-job bgg_family_refresh потом обновит description).
    #   - upsert membership (family_id, bgg_id) → game_id.
    # Это даёт UI «другие игры серии» сразу после первого enrich'а, даже до
    # того, как scheduler-job обойдёт семью.
    await _upsert_families_from_thing(session, game_id, bgg)

    return game_id


async def _upsert_families_from_thing(
    session: AsyncSession,
    game_id: int,
    bgg: BggGame,
) -> None:
    """Сохраняет связки игры с её BGG-семьями (`bgg.families: list[(family_id, name)]`).

    Семья создаётся «облегчённо» — без description (его привезёт scheduler-job
    `bgg_family_refresh` через отдельный `/family/{id}` вызов). Если семья уже
    есть — обновляем только name (на случай переименования куратором BGG),
    description/raw оставляем как есть.

    Membership upsert'ится `INSERT ... ON CONFLICT DO UPDATE SET game_id =
    EXCLUDED.game_id`: если связка уже была (например, попала из refresh'а
    до thing-enrich'а с пустым game_id), теперь подставляется реальный game_id.
    """
    families_t = BggFamily.__table__
    members_t = BggFamilyMember.__table__
    if not bgg.families:
        return

    for family_id, family_name in bgg.families:
        # Upsert семьи (минимальный — id+name). description/members привезёт
        # scheduler-job через separate `/family/{id}` запрос.
        fam_stmt = pg_insert(families_t).values(
            bgg_family_id=family_id,
            name=family_name,
            description=None,
            raw={},
        )
        fam_stmt = fam_stmt.on_conflict_do_update(
            constraint="uq_bgg_families_bgg_id",
            set_={"name": fam_stmt.excluded.name},
        )
        await session.execute(fam_stmt)

        # Резолвим bgg_families.id (autoincrement) — UPSERT не возвращает его
        # надёжно через RETURNING на ON CONFLICT, поэтому отдельный SELECT.
        # На малом числе семей за вызов (обычно <10) — приемлемо; для batch
        # можно будет агрегировать в один IN-SELECT, но сейчас YAGNI.
        from sqlalchemy import select as sa_select
        family_row = (
            await session.execute(
                sa_select(BggFamily.id).where(BggFamily.bgg_family_id == family_id)
            )
        ).scalar_one()

        # Upsert membership.
        mem_stmt = pg_insert(members_t).values(
            family_id=family_row,
            bgg_id=bgg.bgg_id,
            game_id=game_id,
        )
        mem_stmt = mem_stmt.on_conflict_do_update(
            index_elements=["family_id", "bgg_id"],
            set_={"game_id": mem_stmt.excluded.game_id},
        )
        await session.execute(mem_stmt)


async def upsert_family(
    session: AsyncSession,
    family: BggFamilyDC,
) -> int:
    """CAT-8: upsert BGG-семьи целиком (с description + members).

    Используется `bgg_family_refresh` scheduler-job'ом — он тянет
    `/xmlapi2/family/{id}` и пишет все members сюда.

    Members без `game_id` — bgg_id ещё не в catalog (cascade `enrich_one`
    подтянет их или они уже есть, тогда JOIN в reading-API заполнит UI).

    Возвращает `bgg_families.id` (autoincrement PK). Не коммитит сессию.
    """
    families_t = BggFamily.__table__
    members_t = BggFamilyMember.__table__

    fam_stmt = pg_insert(families_t).values(
        bgg_family_id=family.bgg_family_id,
        name=family.name,
        description=family.description,
        raw={"members_count": len(family.members)},
        fetched_at=_utcnow(),
    )
    fam_stmt = fam_stmt.on_conflict_do_update(
        constraint="uq_bgg_families_bgg_id",
        set_={
            "name": fam_stmt.excluded.name,
            "description": fam_stmt.excluded.description,
            "raw": fam_stmt.excluded.raw,
            "fetched_at": fam_stmt.excluded.fetched_at,
        },
    )
    await session.execute(fam_stmt)

    from sqlalchemy import select as sa_select
    family_row_id = (
        await session.execute(
            sa_select(BggFamily.id).where(
                BggFamily.bgg_family_id == family.bgg_family_id
            )
        )
    ).scalar_one()

    # Резолвим game_id для каждого bgg_id одним SELECT IN.
    game_by_bgg: dict[int, int] = {}
    if family.members:
        rows = (
            await session.execute(
                sa_select(Game.bgg_id, Game.id).where(Game.bgg_id.in_(family.members))
            )
        ).all()
        game_by_bgg = {row[0]: row[1] for row in rows}

    # Upsert каждого membership. ON CONFLICT — обновляем game_id ТОЛЬКО если
    # в БД сейчас NULL (COALESCE). Иначе weekly refresh потерял бы уже-связанные
    # member→game связки в момент когда `Game.bgg_id`-IN не нашёл их (например,
    # игра удалена/смерджена, а её bgg_id перенесён на target).
    for member_bgg_id in family.members:
        new_game_id = game_by_bgg.get(member_bgg_id)
        mem_stmt = pg_insert(members_t).values(
            family_id=family_row_id,
            bgg_id=member_bgg_id,
            game_id=new_game_id,
        )
        mem_stmt = mem_stmt.on_conflict_do_update(
            index_elements=["family_id", "bgg_id"],
            set_={
                "game_id": func.coalesce(
                    members_t.c.game_id,  # текущее значение в БД
                    mem_stmt.excluded.game_id,  # новое — только если текущее NULL
                ),
            },
        )
        await session.execute(mem_stmt)

    return family_row_id
