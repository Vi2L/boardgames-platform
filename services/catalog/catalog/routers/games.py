"""CRUD-эндпоинты для канонических Game и их алиасов.

GET /games — листинг + поиск через pg_trgm (`title_norm % :q`) или ILIKE.
GET /games/{id} — карточка с алиасами.
POST /games — ручное создание.
PATCH /games/{id} — частичное обновление, обновляет updated_at.
POST /games/{id}/aliases — добавить альтернативное написание.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from catalog.auth import require_scope
from catalog.db import get_session
from catalog.models import Game, GameAlias, Offer
from catalog.schemas import (
    AliasCreate,
    AliasPatch,
    GameAliasOut,
    GameBggOut,
    GameCreate,
    GameDetailOut,
    GameListOut,
    GameMergeRequest,
    GameMergeResult,
    GameOut,
    GamePatch,
    GameWikidataOut,
)
from sqlalchemy import update

router = APIRouter(prefix="/games", tags=["games"])


@router.get(
    "", response_model=GameListOut, dependencies=[Depends(require_scope("read"))]
)
async def list_games(
    q: str | None = Query(None, description="fuzzy-search по title (pg_trgm)"),
    designer: str | None = Query(None),
    year: int | None = Query(None),
    status_: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> GameListOut:
    stmt = select(Game)

    # Экранирование LIKE-wildcards: % и _ в пользовательском запросе
    # должны трактоваться как литералы, а не паттерн. ESCAPE '\' в SQL.
    # Считаем один раз, переиспользуем в WHERE и ORDER BY.
    q_like = (
        q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if q
        else None
    )

    if q:
        # Гибрид substring (ILIKE) + fuzzy (pg_trgm %).
        # Зачем substring: на коротких запросах (4-5 символов, например "Azul")
        # pg_trgm % с дефолтным similarity_threshold=0.3 отсекает релевантные
        # результаты вроде "Azul Mini" или "Azul: Summer Pavilion" — слишком
        # мало общих триграмм. ILIKE гарантирует, что всё, что содержит
        # подстроку, попадёт в выдачу. Fuzzy остаётся для опечаток
        # ("каркасон" → "Каркассон").
        # Производительность: GIN gin_trgm_ops индексы, созданные миграцией
        # 0001 (ix_games_title_norm_trgm, ix_game_aliases_alias_norm_trgm),
        # ускоряют и `LIKE '%x%'`, и оператор `%` (см. pg_trgm docs).
        stmt = stmt.where(
            text(
                "(title_norm LIKE '%' || lower(immutable_unaccent(:qlike)) || '%' ESCAPE '\\' "
                " OR title_norm % lower(immutable_unaccent(:q)) "
                " OR EXISTS (SELECT 1 FROM game_aliases ga "
                "  WHERE ga.game_id = games.id "
                "    AND (ga.alias_norm LIKE '%' || lower(immutable_unaccent(:qlike)) || '%' ESCAPE '\\' "
                "         OR ga.alias_norm % lower(immutable_unaccent(:q)))))"
            ).bindparams(q=q, qlike=q_like)
        )
    if designer:
        # ANY(:val) = ANY(designers) — включает GIN-индекс по array, если он есть.
        # Пока индекса нет, но для небольшого каталога это не критично.
        stmt = stmt.where(text(":d = ANY(designers)").bindparams(d=designer))
    if year is not None:
        stmt = stmt.where(Game.year == year)
    if status_:
        stmt = stmt.where(Game.status == status_)

    # Считаем total ДО pagination'а.
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    if q:
        # Сортировка: точные substring-matches (score=1.0) первыми, потом
        # fuzzy-кандидаты по убыванию pg_trgm similarity, потом по id.
        # Имена параметров не пересекаются с WHERE, чтобы не зависеть от того,
        # как SQLAlchemy объединяет bindparams в финальном SQL.
        stmt = stmt.order_by(
            text(
                "(CASE WHEN title_norm LIKE '%' || lower(immutable_unaccent(:qlike2)) || '%' ESCAPE '\\' "
                "      THEN 1.0 "
                "      ELSE similarity(title_norm, lower(immutable_unaccent(:q2))) END) DESC"
            ).bindparams(q2=q, qlike2=q_like),
            Game.id.desc(),
        )
    else:
        stmt = stmt.order_by(Game.id.desc())
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    items = result.scalars().all()
    return GameListOut(
        items=[GameOut.model_validate(g) for g in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{game_id}",
    response_model=GameDetailOut,
    dependencies=[Depends(require_scope("read"))],
)
async def get_game(
    game_id: int, session: AsyncSession = Depends(get_session)
) -> GameDetailOut:
    # selectinload подтягивает связанные satellite-таблицы одним SELECT WHERE IN
    # вместо N+1. Ленивые .bgg / .wikidata определены в catalog.models.Game.
    stmt = (
        select(Game)
        .where(Game.id == game_id)
        .options(
            selectinload(Game.aliases),
            selectinload(Game.bgg),
            selectinload(Game.wikidata),
        )
    )
    game = (await session.execute(stmt)).scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    return GameDetailOut(
        **GameOut.model_validate(game).model_dump(),
        aliases=[GameAliasOut.model_validate(a) for a in game.aliases],
        bgg=GameBggOut.model_validate(game.bgg) if game.bgg else None,
        wikidata=GameWikidataOut.model_validate(game.wikidata) if game.wikidata else None,
    )


@router.post(
    "",
    response_model=GameOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("admin"))],
)
async def create_game(
    payload: GameCreate, session: AsyncSession = Depends(get_session)
) -> GameOut:
    game = Game(**payload.model_dump())
    session.add(game)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        # Уникальность нарушена: slug / bgg_id / tesera_id.
        raise HTTPException(status_code=409, detail=f"duplicate: {e.orig}") from e
    await session.refresh(game)
    return GameOut.model_validate(game)


@router.patch(
    "/{game_id}",
    response_model=GameOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def patch_game(
    game_id: int,
    payload: GamePatch,
    session: AsyncSession = Depends(get_session),
) -> GameOut:
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    # exclude_unset=True — обновляем только присланные поля.
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(game, k, v)
    await session.commit()
    await session.refresh(game)
    return GameOut.model_validate(game)


@router.post(
    "/merge",
    response_model=GameMergeResult,
    dependencies=[Depends(require_scope("admin"))],
)
async def merge_games(
    payload: GameMergeRequest,
    session: AsyncSession = Depends(get_session),
) -> GameMergeResult:
    """Объединение source → target.

    Поток:
      1. Все offers source переходят на target (FK update).
      2. Aliases source переезжают на target. Дубликаты по
         uq_alias_per_game (game_id + alias_norm) пропускаются —
         их count возвращается в aliases_skipped_dup.
      3. source.status='merged' + source.meta.merged_into=target_id.

    Без удаления source — карточка остаётся для истории и для трассировки
    (когда-то auto-match мог сослаться на source.id, нужна возможность
    отследить).
    """
    if payload.source_id == payload.target_id:
        raise HTTPException(status_code=400, detail="source_id == target_id")

    source = (await session.execute(
        select(Game).where(Game.id == payload.source_id)
    )).scalar_one_or_none()
    target = (await session.execute(
        select(Game).where(Game.id == payload.target_id)
    )).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail=f"source #{payload.source_id} not found")
    if target is None:
        raise HTTPException(status_code=404, detail=f"target #{payload.target_id} not found")
    if source.status == "merged":
        raise HTTPException(status_code=409, detail="source уже merged")

    # 1. Offers — простой UPDATE, обходит ON CONFLICT (offers уникальны по
    # store_slug+external_id, не по game_id).
    offers_res = await session.execute(
        update(Offer).where(Offer.game_id == payload.source_id)
                     .values(game_id=payload.target_id)
    )
    offers_moved = offers_res.rowcount or 0

    # 2. Aliases — забираем те, которых ещё нет в target (по alias_norm).
    src_aliases = (await session.execute(
        select(GameAlias).where(GameAlias.game_id == payload.source_id)
    )).scalars().all()

    # alias_norm у target
    tgt_norms = set((await session.execute(
        select(GameAlias.alias_norm).where(GameAlias.game_id == payload.target_id)
    )).scalars().all())

    moved = 0
    skipped = 0
    for a in src_aliases:
        if a.alias_norm in tgt_norms:
            await session.delete(a)
            skipped += 1
        else:
            a.game_id = payload.target_id
            tgt_norms.add(a.alias_norm)
            moved += 1

    # 3. Помечаем source. meta — JSONB, аккуратно мерджим.
    meta = dict(source.meta or {})
    meta["merged_into"] = payload.target_id
    source.meta = meta
    source.status = "merged"

    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"conflict: {e.orig}") from e

    return GameMergeResult(
        source_id=payload.source_id,
        target_id=payload.target_id,
        offers_moved=offers_moved,
        aliases_moved=moved,
        aliases_skipped_dup=skipped,
    )


@router.post(
    "/{game_id}/aliases",
    response_model=GameAliasOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("admin"))],
)
async def add_alias(
    game_id: int,
    payload: AliasCreate,
    session: AsyncSession = Depends(get_session),
) -> GameAliasOut:
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    alias = GameAlias(
        game_id=game_id,
        alias=payload.alias,
        source=payload.source,
        language=payload.language,
        verified=payload.verified,
    )
    session.add(alias)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        # uq_alias_per_game — алиас уже есть.
        raise HTTPException(status_code=409, detail="alias already exists") from e
    await session.refresh(alias)
    return GameAliasOut.model_validate(alias)


@router.patch(
    "/{game_id}/aliases/{alias_id}",
    response_model=GameAliasOut,
    dependencies=[Depends(require_scope("admin"))],
)
async def patch_alias(
    game_id: int,
    alias_id: int,
    payload: AliasPatch,
    session: AsyncSession = Depends(get_session),
) -> GameAliasOut:
    """Редактирование алиаса.

    Главный сценарий: проставить verified=true ручным алиасам после ревью,
    либо уточнить language ('en' → 'ru-RU' и т.п.).
    """
    alias = (await session.execute(
        select(GameAlias).where(
            GameAlias.id == alias_id, GameAlias.game_id == game_id,
        )
    )).scalar_one_or_none()
    if alias is None:
        raise HTTPException(status_code=404, detail="alias not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(alias, k, v)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"conflict: {e.orig}") from e
    await session.refresh(alias)
    return GameAliasOut.model_validate(alias)


@router.delete(
    "/{game_id}/aliases/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_alias(
    game_id: int,
    alias_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Удаление алиаса.

    Удаление manual-алиаса оставляет пробел в локализации, удаление
    auto-match — может вернуть оффер в очередь матчинга при следующем
    ingest'е, потому что title_raw_norm перестанет % matchить.
    """
    alias = (await session.execute(
        select(GameAlias).where(
            GameAlias.id == alias_id, GameAlias.game_id == game_id,
        )
    )).scalar_one_or_none()
    if alias is None:
        raise HTTPException(status_code=404, detail="alias not found")
    await session.delete(alias)
    await session.commit()
    return None
