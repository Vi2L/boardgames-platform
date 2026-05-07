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
from catalog.models import Game, GameAlias
from catalog.schemas import (
    AliasCreate,
    GameAliasOut,
    GameBggOut,
    GameCreate,
    GameDetailOut,
    GameListOut,
    GameOut,
    GamePatch,
    GameWikidataOut,
)

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

    if q:
        # Fuzzy-search по двум источникам: canonical title и game_aliases.
        # Это критично для ru-запросов: title в games хранится на исходном
        # языке (часто en), русские локализации сидят в game_aliases (source=
        # 'wikidata' / 'manual'). Оба условия используют GIN pg_trgm индексы.
        stmt = stmt.where(
            text(
                "(title_norm % lower(immutable_unaccent(:q)) "
                " OR EXISTS (SELECT 1 FROM game_aliases ga "
                "  WHERE ga.game_id = games.id "
                "    AND ga.alias_norm % lower(immutable_unaccent(:q))))"
            ).bindparams(q=q)
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

    stmt = stmt.order_by(Game.id.desc()).limit(limit).offset(offset)
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
    alias = GameAlias(game_id=game_id, alias=payload.alias, source=payload.source)
    session.add(alias)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        # uq_alias_per_game — алиас уже есть.
        raise HTTPException(status_code=409, detail="alias already exists") from e
    await session.refresh(alias)
    return GameAliasOut.model_validate(alias)
