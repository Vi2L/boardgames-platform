"""CRUD-эндпоинты для канонических Game и их алиасов.

GET /games — листинг + поиск через pg_trgm (`title_norm % :q`) или ILIKE.
GET /games/{id} — карточка с алиасами.
POST /games — ручное создание.
PATCH /games/{id} — частичное обновление, обновляет updated_at.
POST /games/{id}/aliases — добавить альтернативное написание.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, select, text
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
    GameChildOut,
    GameChildrenOut,
    GameCreate,
    GameDetailOut,
    GameListOut,
    GameMergeRequest,
    GameMergeResult,
    GameOffersOut,
    GameOut,
    GamePatch,
    GameWikidataOut,
    OfferOut,
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
        # Композитный ранжир, чтобы оригинал/база шла раньше переизданий
        # и дополнений. Иерархия score'ов:
        #   exact-match  4.0  — title_norm == :q
        #   prefix       3.0  — title_norm LIKE 'q%'
        #   substring    2.0  — title_norm LIKE '%q%'
        #   fuzzy       <1.0  — pg_trgm similarity
        # Берём GREATEST из title-score и max(alias-score) для этой игры —
        # это исправляет кейс, когда canonical-title английский, а
        # ru-локализация (Wikidata-alias) совпадает с запросом. Раньше
        # такие игры (#231 'Carcassonne') получали низкую fuzzy и тонули.
        #
        # Tiebreakers внутри одного score-bucket'а: kind='base' выше
        # допов/промо, parent_game_id IS NULL выше детей, короткий title
        # ('Каркассон' < 'Каркассон: Колесо фортуны'), id ASC (оригиналы
        # с маленькими id выше переизданий).
        #
        # Sub-SELECT на game_aliases выполняется только для уже-
        # отфильтрованных WHERE строк (≤limit), не на полных 162K games.
        # Параметры :q3/:qlike3 не пересекаются с WHERE (:q/:qlike) и
        # ORDER BY в других местах — это страхует от случаев, когда
        # SQLAlchemy объединит bindparams.
        stmt = stmt.order_by(
            text(
                "GREATEST("
                "  CASE "
                "    WHEN title_norm = lower(immutable_unaccent(:q3)) THEN 4.0 "
                "    WHEN title_norm LIKE lower(immutable_unaccent(:qlike3)) || '%' ESCAPE '\\' THEN 3.0 "
                "    WHEN title_norm LIKE '%' || lower(immutable_unaccent(:qlike3)) || '%' ESCAPE '\\' THEN 2.0 "
                "    ELSE similarity(title_norm, lower(immutable_unaccent(:q3))) "
                "  END, "
                "  COALESCE(("
                "    SELECT MAX(CASE "
                "      WHEN ga.alias_norm = lower(immutable_unaccent(:q3)) THEN 4.0 "
                "      WHEN ga.alias_norm LIKE lower(immutable_unaccent(:qlike3)) || '%' ESCAPE '\\' THEN 3.0 "
                "      WHEN ga.alias_norm LIKE '%' || lower(immutable_unaccent(:qlike3)) || '%' ESCAPE '\\' THEN 2.0 "
                "      ELSE similarity(ga.alias_norm, lower(immutable_unaccent(:q3))) "
                "    END) "
                "    FROM game_aliases ga WHERE ga.game_id = games.id"
                "  ), 0.0)"
                ") DESC, "
                "(CASE WHEN kind = 'base' THEN 0 ELSE 1 END) ASC, "
                "(CASE WHEN parent_game_id IS NULL THEN 0 ELSE 1 END) ASC, "
                "LENGTH(title) ASC, "
                "id ASC"
            ).bindparams(q3=q, qlike3=q_like),
        )
    else:
        stmt = stmt.order_by(Game.id.desc())
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    # title_ru — лучший alias с language='ru'. Один доп. SELECT с DISTINCT ON
    # (per game_id) по приоритету источников: verified+manual → dicefest →
    # wikidata → остальные. PG-only (DISTINCT ON), но catalog и так Postgres.
    ru_titles: dict[int, str] = {}
    if items:
        game_ids = [g.id for g in items]
        priority = case(
            (and_(GameAlias.source == "manual", GameAlias.verified.is_(True)), 1),
            (GameAlias.source == "dicefest", 2),
            (GameAlias.source == "wikidata", 3),
            else_=4,
        )
        ru_stmt = (
            select(GameAlias.game_id, GameAlias.alias)
            .where(GameAlias.language == "ru", GameAlias.game_id.in_(game_ids))
            # DISTINCT ON в PG берёт первую строку группы по ORDER BY,
            # ключ группы — первый аргумент distinct() и ведущий ORDER BY.
            .order_by(GameAlias.game_id, priority, GameAlias.id)
            .distinct(GameAlias.game_id)
        )
        ru_titles = dict((await session.execute(ru_stmt)).all())

    out_items: list[GameOut] = []
    for g in items:
        out = GameOut.model_validate(g)
        out.title_ru = ru_titles.get(g.id)
        out_items.append(out)
    return GameListOut(
        items=out_items, total=total, limit=limit, offset=offset,
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
    base = GameOut.model_validate(game)
    # Те же приоритеты, что и в list_games — но здесь aliases уже подгружены
    # через selectinload, так что считаем в Python без доп. запроса.
    base.title_ru = _pick_ru_title(game.aliases)
    return GameDetailOut(
        **base.model_dump(),
        aliases=[GameAliasOut.model_validate(a) for a in game.aliases],
        bgg=GameBggOut.model_validate(game.bgg) if game.bgg else None,
        wikidata=GameWikidataOut.model_validate(game.wikidata) if game.wikidata else None,
    )


def _pick_ru_title(aliases: list[GameAlias]) -> str | None:
    """Лучший alias-ru — то же ранжирование, что и DISTINCT ON в list_games.

    1) manual + verified=true, 2) dicefest, 3) wikidata, 4) остальные.
    При ничье — самый ранний (по id), это детерминированно и совпадает с SQL.
    """
    def rank(a: GameAlias) -> tuple[int, int]:
        if a.source == "manual" and a.verified:
            p = 1
        elif a.source == "dicefest":
            p = 2
        elif a.source == "wikidata":
            p = 3
        else:
            p = 4
        return (p, a.id)

    ru = [a for a in aliases if a.language == "ru"]
    if not ru:
        return None
    return min(ru, key=rank).alias


@router.get(
    "/{game_id}/offers",
    response_model=GameOffersOut,
    dependencies=[Depends(require_scope("read"))],
)
async def list_game_offers(
    game_id: int, session: AsyncSession = Depends(get_session),
) -> GameOffersOut:
    """Все offers с этой game_id — для drawer-таба «Offers».

    Сортировка: store_slug ASC, last_price ASC NULLS LAST. Без пагинации:
    у одной игры не бывает >>20 предложений, лимит лишний.
    """
    # Проверяем, что игра существует — иначе 404, не пустой список
    # (помогает отличить «нет offers» от «нет такой игры»).
    g = await session.get(Game, game_id)
    if g is None:
        raise HTTPException(status_code=404, detail="game not found")
    stmt = (
        select(Offer)
        .where(Offer.game_id == game_id)
        .order_by(
            Offer.store_slug.asc(),
            Offer.last_price.asc().nulls_last(),
        )
    )
    items = (await session.execute(stmt)).scalars().all()
    return GameOffersOut(
        game_id=game_id,
        items=[OfferOut.model_validate(o) for o in items],
        total=len(items),
    )


@router.get(
    "/{game_id}/children",
    response_model=GameChildrenOut,
    dependencies=[Depends(require_scope("read"))],
)
async def list_game_children(
    game_id: int, session: AsyncSession = Depends(get_session),
) -> GameChildrenOut:
    """Игры, у которых parent_game_id = текущая (миграция 0006).

    Сортировка: kind (по приоритету: expansion → promo → accessory →
    остальное), потом title. CASE-выражение даёт стабильный порядок,
    не зависящий от alphabet'а строк kind.
    """
    g = await session.get(Game, game_id)
    if g is None:
        raise HTTPException(status_code=404, detail="game not found")
    stmt = (
        select(Game)
        .where(Game.parent_game_id == game_id)
        .order_by(
            text(
                "CASE kind "
                "WHEN 'expansion' THEN 1 "
                "WHEN 'promo' THEN 2 "
                "WHEN 'accessory' THEN 3 "
                "ELSE 4 END"
            ),
            Game.title.asc(),
        )
    )
    items = (await session.execute(stmt)).scalars().all()
    return GameChildrenOut(
        parent_game_id=game_id,
        items=[GameChildOut.model_validate(c) for c in items],
        total=len(items),
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
