"""Промоушен dicefest_raw_games → canonical games + game_dicefest.

Workflow (raw.status state machine):
   new → promoted | skipped | rejected
   skipped/rejected → new   (через revert)
   promoted → new           (через revert; alias+satellite удаляются)

Идемпотентность от двойного клика — через optimistic UPDATE с RETURNING:
  UPDATE dicefest_raw_games SET status='promoted' WHERE id=:rid AND status='new'
  RETURNING id  → если 0 строк, значит конкурент уже сделал → 409.

Revert проверяет:
  - log не уже reverted (log.reverted_at IS NULL).
  - games.status != 'merged' (если merged — отказ с понятным сообщением,
    оператор должен решить какой target использовать).
  - alias и satellite ещё существуют (если кто-то удалил руками — отказ).
  - НЕ трогаем offers.game_id — explicit contract: revert убирает только
    мост alias↔dicefest, оффер'ы остаются прикреплёнными.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.models import (
    DicefestRawGame,
    Game,
    GameAlias,
    GameDicefest,
    ImportPromotionLog,
)

PROVIDER = "dicefest"
DEFAULT_THRESHOLD = 0.5
MIN_THRESHOLD = 0.0  # для UI: «показать всех» — любой допустим
DEFAULT_LIMIT = 5

PromoAction = Literal["link", "create", "skip", "reject"]


# ─── Match candidates ────────────────────────────────────────────────────────


async def match_candidates(
    session: AsyncSession,
    raw_id: int,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    limit: int = DEFAULT_LIMIT,
) -> tuple[DicefestRawGame, list[dict]]:
    """Кандидаты-canonical-Game для raw-записи, отсортированные по score DESC.

    pg_trgm поверх title_norm games + alias_norm game_aliases (используя те
    же индексы, что matcher.py:94-133). Кандидаты возвращаются с score
    ≥threshold, дополнительно помечаются `has_satellite_for_provider` (уже
    привязан другой dicefest-страницей) и `year_diff` (разница годов с raw).

    Если raw не имеет ни title_ru, ни title_en — возвращаем пустой список
    (нечего матчить).
    """
    raw = await session.get(DicefestRawGame, raw_id)
    if raw is None:
        raise HTTPException(404, detail=f"raw_id={raw_id} not found")

    queries = [t for t in (raw.title_ru, raw.title_en) if t]
    if not queries:
        return raw, []

    # CTE объединяет матчи по двум источникам (title + aliases) для каждого
    # из max-2 query-строк (title_ru/title_en). Берём MAX(score) per game.
    sql = text(
        """
        WITH q AS (
            SELECT unnest(CAST(:queries AS text[])) AS norm
        ),
        from_title AS (
            SELECT g.id AS game_id,
                   g.title AS title,
                   g.year AS year,
                   GREATEST(
                       similarity(g.title_norm, lower(immutable_unaccent(q.norm))),
                       0
                   ) AS score,
                   'title'::text AS via,
                   g.title AS matched_text
            FROM games g, q
            WHERE g.title_norm % lower(immutable_unaccent(q.norm))
              AND (g.status IS NULL OR g.status != 'merged')
        ),
        from_alias AS (
            SELECT a.game_id,
                   g.title AS title,
                   g.year AS year,
                   similarity(a.alias_norm, lower(immutable_unaccent(q.norm))) AS score,
                   ('alias_' || COALESCE(a.language, 'unknown'))::text AS via,
                   a.alias AS matched_text
            FROM game_aliases a
            JOIN games g ON g.id = a.game_id
            CROSS JOIN q
            WHERE a.alias_norm % lower(immutable_unaccent(q.norm))
              AND (g.status IS NULL OR g.status != 'merged')
        ),
        all_matches AS (
            SELECT * FROM from_title
            UNION ALL
            SELECT * FROM from_alias
        ),
        per_game AS (
            SELECT game_id,
                   MAX(score) AS score,
                   (ARRAY_AGG(via ORDER BY score DESC))[1] AS via,
                   (ARRAY_AGG(matched_text ORDER BY score DESC))[1] AS matched_text,
                   (ARRAY_AGG(title ORDER BY score DESC))[1] AS title,
                   (ARRAY_AGG(year ORDER BY score DESC))[1] AS year
            FROM all_matches
            WHERE score >= :threshold
            GROUP BY game_id
        )
        SELECT pg.game_id, pg.score, pg.via, pg.matched_text, pg.title, pg.year,
               EXISTS(SELECT 1 FROM game_dicefest gd WHERE gd.game_id = pg.game_id)
                   AS has_satellite_for_provider
        FROM per_game pg
        ORDER BY pg.score DESC, pg.game_id
        LIMIT :limit
        """
    ).bindparams(queries=queries, threshold=threshold, limit=limit)
    rows = (await session.execute(sql)).mappings().all()

    # Подгружаем aliases для каждого кандидата (для контекста в UI: какие у
    # canonical игры локализации). N+1 не страшно: limit≤10.
    candidates: list[dict] = []
    for r in rows:
        aliases = (
            await session.execute(
                select(GameAlias).where(GameAlias.game_id == r["game_id"])
            )
        ).scalars().all()
        # year_diff УБРАН в PR-4: release_year/_month относились к РФ-релизу,
        # а не к оригинальному году издания (как в games.year). Сравнение давало
        # ложно-тревожные warning'и. Если позже извлечём год оригинала из
        # external_links (BGG) — вернём.
        year_diff: int | None = None
        candidates.append(
            {
                "game_id": r["game_id"],
                "title": r["title"],
                "year": r["year"],
                "score": float(r["score"]),
                "via": r["via"],
                "matched_text": r["matched_text"],
                "aliases": list(aliases),
                "has_satellite_for_provider": bool(r["has_satellite_for_provider"]),
                "year_diff": year_diff,
            }
        )
    return raw, candidates


# ─── Promote ─────────────────────────────────────────────────────────────────


async def promote(
    session: AsyncSession,
    raw_id: int,
    *,
    action: PromoAction,
    target_game_id: int | None = None,
    notes: str | None = None,
    performed_by: str = "operator",
) -> dict:
    """Транзакционно: переводит raw в новое состояние + создаёт alias/satellite/game,
    пишет audit-строку в import_promotion_log.

    Все действия атомарны — один commit в конце. При ошибке — rollback.
    Идемпотентность через UPDATE ... WHERE status='new' RETURNING (двойной
    клик на UI получит 409).
    """
    if action == "link" and target_game_id is None:
        raise HTTPException(400, detail="link требует target_game_id")
    if action not in ("link", "create", "skip", "reject"):
        raise HTTPException(400, detail=f"unknown action: {action}")

    # 1) Атомарно переводим raw из 'new' в новое состояние. Если 0 строк —
    #    кто-то уже сделал.
    new_status = {
        "link": "promoted",
        "create": "promoted",
        "skip": "skipped",
        "reject": "rejected",
    }[action]

    res = await session.execute(
        update(DicefestRawGame)
        .where(DicefestRawGame.id == raw_id, DicefestRawGame.status == "new")
        .values(
            status=new_status,
            promoted_at=datetime.now(timezone.utc) if action in ("link", "create") else None,
            notes=notes,
        )
        .returning(DicefestRawGame.id)
    )
    if res.scalar_one_or_none() is None:
        # Либо нет такой записи, либо статус уже не 'new'
        raw = await session.get(DicefestRawGame, raw_id)
        if raw is None:
            raise HTTPException(404, detail=f"raw_id={raw_id} not found")
        raise HTTPException(
            409,
            detail=f"raw {raw_id} уже в статусе '{raw.status}', промоушен невозможен",
        )

    # Перечитываем с актуальными значениями.
    raw = await session.get(DicefestRawGame, raw_id)
    assert raw is not None

    game_id: int | None = None
    alias_id: int | None = None
    satellite_id: int | None = None

    if action == "link":
        # Проверяем, что target game существует и не merged.
        target = await session.get(Game, target_game_id)
        if target is None:
            raise HTTPException(404, detail=f"target_game_id={target_game_id} not found")
        if target.status == "merged":
            raise HTTPException(
                409,
                detail=f"game {target_game_id} merged — выберите target из meta.merged_into",
            )
        game_id = target_game_id
        alias_id, satellite_id = await _attach_dicefest_data(
            session, raw, game_id=game_id,
        )
        # Денормализуем dicefest-данные в games (миграция 0006). Заполняем
        # только пустые поля — не перезатираем то, что уже было задано
        # вручную или другим источником.
        _denormalize_dicefest_into_game(target, raw)

    elif action == "create":
        # Создаём новую canonical Game со slug-префиксом.
        canonical_slug = f"dicefest-{raw.slug}"
        new_title = raw.title_ru or raw.title_en or raw.slug
        # year оставляем None — release_year раньше парсился из РФ-релиза
        # (не оригинал). Корректный год игры подтянет последующее обогащение
        # через wikidata/BGG.
        # Поля локализации (ru_publisher / preorder_price / dicefest_id /
        # is_localized_ru / nastolio_id / bgg_id / tesera_id из external_links)
        # денормализуем сразу из raw — миграция 0006.
        game = Game(
            slug=canonical_slug,
            title=new_title,
            source="dicefest",
            status="active",
        )
        _denormalize_dicefest_into_game(game, raw)
        session.add(game)
        await session.flush()       # получаем game.id без commit'а
        game_id = game.id
        alias_id, satellite_id = await _attach_dicefest_data(
            session, raw, game_id=game_id,
        )

    # action == 'skip' / 'reject' — только статус меняется, никаких alias/satellite.

    # 2) Денормализованную ссылку обновляем у raw для удобства.
    if game_id is not None:
        raw.promoted_to_game_id = game_id

    # 3) Audit log
    log = ImportPromotionLog(
        provider=PROVIDER,
        raw_id=raw_id,
        action=action,
        game_id=game_id,
        alias_id=alias_id,
        satellite_created=(satellite_id is not None),
        performed_by=performed_by,
        notes=notes,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)

    return {
        "raw_id": raw_id,
        "log_id": log.id,
        "game_id": game_id,
        "alias_id": alias_id,
        "satellite_id": satellite_id,
        "status": new_status,
    }


def _denormalize_dicefest_into_game(game: Game, raw: DicefestRawGame) -> None:
    """Копирует dicefest-данные в денормализованные колонки `games` (миграция 0006).

    Заполняем только пустые поля — это позволяет:
      - не перезатирать ручные правки оператора;
      - при повторном промоушене после revert восстанавливать прежнее состояние;
      - при `link` к существующей игре дополнять, а не подменять.

    Поведение для каждого поля:
      ru_publisher / preorder_price — из raw.publisher / raw.preorder_price.
      dicefest_id — всегда обновляем на raw.id (текущая активная связь).
      is_localized_ru — выставляется True, если есть publisher или title_ru.
      nastolio_id — из raw.external_links[kind='nastolio'] (slug или url).
      bgg_id / tesera_id — из external_links, ТОЛЬКО если у игры ещё пусто
        (не перебиваем существующие ID; uniqueness проверять при ALTER не
        нужно — UNIQUE-индекс БД отвергнет дубль на коммите).
    """
    if game.ru_publisher is None and raw.publisher:
        game.ru_publisher = raw.publisher
    if game.preorder_price is None and raw.preorder_price is not None:
        game.preorder_price = raw.preorder_price
    # dicefest_id — текущая активная связь, обновляем безусловно. Старая
    # связь была сброшена в revert (если был), либо это первый промоушен.
    game.dicefest_id = raw.id
    if raw.publisher or raw.title_ru:
        game.is_localized_ru = True

    # external_links — массив dict'ов: [{kind, url, label, external_id?}].
    # Перебираем один раз, выдёргиваем nastolio/bgg/tesera id.
    for link in raw.external_links or []:
        kind = (link.get("kind") or "").lower() if isinstance(link, dict) else ""
        if not kind:
            continue
        ext_id = link.get("external_id")
        url = link.get("url")
        if kind == "nastolio" and game.nastolio_id is None:
            # external_id парсится не всегда; URL — гарантированный fallback.
            game.nastolio_id = ext_id or url
        elif kind == "bgg" and game.bgg_id is None and ext_id:
            try:
                game.bgg_id = int(ext_id)
            except (ValueError, TypeError):
                # Кривой external_id из dicefest — игнорируем, не падаем.
                pass
        elif kind == "tesera" and game.tesera_id is None and ext_id:
            try:
                game.tesera_id = int(ext_id)
            except (ValueError, TypeError):
                pass


async def _attach_dicefest_data(
    session: AsyncSession, raw: DicefestRawGame, *, game_id: int,
) -> tuple[int | None, int | None]:
    """Создаёт alias source='dicefest' (если ещё нет) + satellite game_dicefest.

    alias.alias = raw.title_ru, language='ru' (основная локализация dicefest).
    satellite — 1:1 с raw, но с привязкой к canonical game_id.
    """
    alias_id: int | None = None
    if raw.title_ru:
        # Проверяем существующий alias по `alias_norm` (lower+unaccent), а не
        # по сырому `alias` — иначе пропускаем дубликат если ru-локализация
        # уже добавлена другим источником (wikidata/manual) с другим регистром.
        # UNIQUE constraint `uq_alias_per_game (game_id, alias_norm)` иначе даст
        # IntegrityError при INSERT.
        existing_alias = (
            await session.execute(
                text(
                    "SELECT id FROM game_aliases "
                    "WHERE game_id = :gid "
                    "  AND alias_norm = lower(immutable_unaccent(:alias)) "
                    "LIMIT 1"
                ).bindparams(gid=game_id, alias=raw.title_ru)
            )
        ).scalar_one_or_none()
        if existing_alias is None:
            alias = GameAlias(
                game_id=game_id,
                alias=raw.title_ru,
                source=PROVIDER,
                language="ru",
                verified=True,  # промоушен — это ручное подтверждение
            )
            session.add(alias)
            await session.flush()
            alias_id = alias.id
        else:
            # Alias уже существует (возможно от другого source) — переиспользуем,
            # не создавая дубль.
            alias_id = int(existing_alias)

    # Satellite. UNIQUE(game_id, slug) защищает от дублей.
    existing_sat = (
        await session.execute(
            select(GameDicefest).where(GameDicefest.slug == raw.slug)
        )
    ).scalar_one_or_none()
    if existing_sat is not None:
        # Уже есть satellite — это означает, что raw был промоушен раньше,
        # потом revert'нут (satellite удалён), но теперь повторно. Создадим
        # заново, удалив старый.
        await session.delete(existing_sat)
        await session.flush()

    satellite = GameDicefest(
        game_id=game_id,
        raw_id=raw.id,
        slug=raw.slug,
        title_ru=raw.title_ru,
        title_en=raw.title_en,
        publisher=raw.publisher,
        release_status=raw.release_status,
        description=raw.description,
        cover_url=raw.cover_url,
        page_url=raw.page_url,
        preorder_price=raw.preorder_price,
        external_links=raw.external_links or [],
        raw=raw.raw,
        fetched_at=raw.fetched_at,
    )
    session.add(satellite)
    await session.flush()
    return alias_id, satellite.id


# ─── Revert ──────────────────────────────────────────────────────────────────


async def revert(
    session: AsyncSession,
    log_id: int,
    *,
    performed_by: str = "operator",
    notes: str | None = None,
) -> dict:
    """Откатывает действие promote.

    link/create → удаляет alias и satellite (если они ещё на месте).
                  Для action='create' пытается также удалить game, но ТОЛЬКО
                  если у неё нет offers и нет других promotion-логов.
    skip/reject → возвращает raw в 'new'.

    Не трогает offers.game_id — оператор разбирается отдельно.
    """
    log = await session.get(ImportPromotionLog, log_id)
    if log is None:
        raise HTTPException(404, detail=f"log_id={log_id} not found")
    if log.reverted_at is not None:
        raise HTTPException(409, detail=f"log {log_id} уже reverted at {log.reverted_at}")
    if log.action == "revert":
        raise HTTPException(400, detail="нельзя revert revert-action")

    raw = await session.get(DicefestRawGame, log.raw_id)
    if raw is None:
        raise HTTPException(404, detail=f"raw_id={log.raw_id} disappeared")

    # Защита от расхождений с merge: если game была сliянa, оператор должен
    # сам решить как откатывать.
    if log.game_id is not None:
        game = await session.get(Game, log.game_id)
        if game is not None and game.status == "merged":
            raise HTTPException(
                409,
                detail=(
                    f"game {log.game_id} была merged — состояние расходится "
                    f"с журналом, выполните revert вручную"
                ),
            )

    if log.action in ("link", "create"):
        # 1) Удалить alias (если он ещё ровно тот, что в логе)
        if log.alias_id is not None:
            alias = await session.get(GameAlias, log.alias_id)
            if alias is not None:
                await session.delete(alias)

        # 2) Удалить satellite по slug (PK satellite — id, но в логе мы его
        #    не сохраняли; используем slug, который уникален).
        sat = (
            await session.execute(
                select(GameDicefest).where(GameDicefest.slug == raw.slug)
            )
        ).scalar_one_or_none()
        if sat is not None:
            await session.delete(sat)

        # 2b) Сбрасываем dicefest_id у game — связь разорвана. Остальные
        # денормализованные поля (ru_publisher / preorder_price / nastolio_id
        # / bgg_id / tesera_id / is_localized_ru) НЕ трогаем: оператор мог
        # их исправить вручную, и они полезны независимо от dicefest. Тот же
        # принцип, что для offers.game_id (см. docstring модуля).
        if log.game_id is not None:
            game = await session.get(Game, log.game_id)
            if game is not None and game.dicefest_id == raw.id:
                game.dicefest_id = None

        # 3) Если action='create' — пытаемся удалить game, но осторожно.
        if log.action == "create" and log.game_id is not None:
            # Проверяем: нет других promotion-логов на эту game и нет offers.
            other_logs = (
                await session.execute(
                    select(ImportPromotionLog).where(
                        ImportPromotionLog.game_id == log.game_id,
                        ImportPromotionLog.id != log.id,
                        ImportPromotionLog.action.in_(("link", "create")),
                        ImportPromotionLog.reverted_at.is_(None),
                    )
                )
            ).scalars().all()
            offers_count = (
                await session.execute(
                    text("SELECT count(*) FROM offers WHERE game_id = :gid").bindparams(
                        gid=log.game_id,
                    )
                )
            ).scalar_one()
            if not other_logs and not offers_count:
                game = await session.get(Game, log.game_id)
                if game is not None:
                    await session.delete(game)
            # иначе — game остаётся, но без alias/satellite (всё равно безопасно).

    # 4) Возвращаем raw в 'new'
    raw.status = "new"
    raw.promoted_at = None
    raw.promoted_to_game_id = None

    # 5) Помечаем log как reverted + создаём отдельную revert-запись
    now = datetime.now(timezone.utc)
    log.reverted_at = now
    log.reverted_by = performed_by

    revert_log = ImportPromotionLog(
        provider=PROVIDER,
        raw_id=log.raw_id,
        action="revert",
        game_id=log.game_id,
        performed_by=performed_by,
        notes=notes or f"revert of log #{log_id}",
    )
    session.add(revert_log)
    await session.commit()
    await session.refresh(revert_log)

    return {
        "raw_id": log.raw_id,
        "revert_log_id": revert_log.id,
        "original_log_id": log.id,
        "status_after_revert": raw.status,
    }


# ─── Batch auto-link (PR-5) ───────────────────────────────────────────────────

# Сколько preview-строк отдаём в `items` ответе. Полный список skipped — в
# `skipped[]`, чтобы UI мог показать аккуратно. items=top-50 не дублируется
# в skipped (skipped содержит ТОЛЬКО пропущенные).
_BATCH_PREVIEW_LIMIT = 50


async def batch_auto_link(
    session: AsyncSession,
    *,
    threshold: float = 0.95,
    max_items: int = 100,
    dry_run: bool = True,
    skip_with_satellite: bool = True,
    performed_by: str = "operator-batch",
) -> dict:
    """Авто-link raw → canonical Game для уверенных совпадений (PR-5).

    Алгоритм:
      1. SELECT raw WHERE status='new' ORDER BY id LIMIT max_items.
      2. Для каждой raw: match_candidates(threshold=threshold, limit=1).
      3. Если top-1 score ≥ threshold:
         - skip_with_satellite=True и has_satellite_for_provider → skip
         - dry_run=True: добавляем в items (без записи в БД)
         - dry_run=False: promote(action='link', notes='auto-batch threshold=…')
      4. Иначе → skipped[reason='low_score' | 'no_candidates'].

    Возвращает dict, который сериализуется в BatchLinkResult (см. schemas.py).
    """
    if not (0.0 <= threshold <= 1.0):
        raise HTTPException(400, detail="threshold должен быть в [0, 1]")
    if max_items <= 0:
        raise HTTPException(400, detail="max_items должен быть > 0")

    # 1) Берём пачку raw в статусе new.
    raw_ids = (
        await session.execute(
            select(DicefestRawGame.id)
            .where(DicefestRawGame.status == "new")
            .order_by(DicefestRawGame.id)
            .limit(max_items)
        )
    ).scalars().all()

    items: list[dict] = []          # preview топ-N для UI
    skipped: list[dict] = []
    linked = 0
    would_link = 0
    notes = f"auto-batch threshold={threshold:.2f}"

    for rid in raw_ids:
        # match_candidates сам читает raw из БД и возвращает топ-1.
        raw, cands = await match_candidates(
            session, rid, threshold=threshold, limit=1,
        )
        if not cands:
            skipped.append({
                "raw_id": rid, "slug": raw.slug,
                "reason": "no_candidates", "top_score": None,
            })
            continue
        top = cands[0]
        if top["score"] < threshold:
            # Не должно случаться — match_candidates уже фильтрует по threshold,
            # но защищаемся явно (на случай float rounding edge).
            skipped.append({
                "raw_id": rid, "slug": raw.slug,
                "reason": "low_score", "top_score": float(top["score"]),
            })
            continue
        if skip_with_satellite and top["has_satellite_for_provider"]:
            skipped.append({
                "raw_id": rid, "slug": raw.slug,
                "reason": "already_linked", "top_score": float(top["score"]),
            })
            continue

        # Кандидат подходит. В preview включаем ВСЕ (до limit) — оператору
        # удобно видеть, что batch нашёл.
        if len(items) < _BATCH_PREVIEW_LIMIT:
            items.append({
                "raw_id": rid,
                "slug": raw.slug,
                "raw_title": raw.title_ru or raw.title_en,
                "game_id": top["game_id"],
                "game_title": top["title"],
                "score": float(top["score"]),
                "via": top["via"],
            })

        if dry_run:
            would_link += 1
            continue

        try:
            await promote(
                session, rid,
                action="link",
                target_game_id=top["game_id"],
                notes=notes,
                performed_by=performed_by,
            )
            linked += 1
        except HTTPException as e:
            # Идемпотентность: если raw перешёл из 'new' между нашим SELECT
            # и UPDATE — promote вернёт 409. Это норма при гонке, добавляем в
            # skipped с понятным reason.
            skipped.append({
                "raw_id": rid, "slug": raw.slug,
                "reason": f"promote_failed:{e.status_code}",
                "top_score": float(top["score"]),
            })

    return {
        "scanned": len(raw_ids),
        "linked": linked,
        "would_link": would_link,
        "skipped": skipped,
        "items": items,
        "dry_run": dry_run,
    }
