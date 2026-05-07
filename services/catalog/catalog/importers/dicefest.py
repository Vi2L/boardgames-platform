"""Парсер dicefest.ru — каталог-календарь релизов настольных игр в РФ.

Сайт на Bitrix CMS, серверный рендер. Sitemap.xml содержит только основные
страницы (/, /contacts, /premium, /profile) — игр в нём НЕТ. Поэтому собираем
slug'и обходом фильтров по годам (?year=2024|2025|2026) и парсим каждую карточку
через BeautifulSoup.

Структура карточки `/game/{slug}/`:
- <h2> — title (первый text node, остальное — UI-болтовня lazy-load).
- description pairs (`game-popup-description__title` → `__text`):
    "Издательство:" → publisher
    "Статус игры:" → release_status (+ data-status code)
    "Предзаказ:" → строка вида "пока не знаем когда :)" / "2 половина 2026"
    "Старт продаж:" → аналогично
- features (`game-popup-feature__icon--{kind}` + `__text`):
    players: "2-4 игрока"
    clock: "20-40 мин"
- background-image: url(/upload/iblock/...) — обложка (первое уникальное
  значение).
- Текст после "Описание от издателя:" — описание.

Двухстадийность: пишем ТОЛЬКО в dicefest_raw_games. Промоушен в canonical
games — отдельный процесс (PR-2).
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.db import get_engine
from catalog.importers._log_buffer import LogBuffer
from catalog.models import DicefestRawGame, ImportJob

logger = logging.getLogger(__name__)

BASE_URL = "https://dicefest.ru"
USER_AGENT = (
    "boardgames-platform/0.1 (catalog importer; "
    "+https://github.com/Vi2L/boardgames-platform)"
)
RATE_LIMIT_SEC = 1.0
RATE_LIMIT_JITTER_SEC = 0.3
RETRY_BACKOFFS = (2.0, 4.0, 8.0, 16.0)  # на 429/5xx
RAW_FRESH_DAYS = 7  # пропускаем slug, скачанный за последние N дней (resume)


# Маппинг русских месяцев → 1..12 для парсинга строк типа "2 половина 2026" /
# "Январь 2026". "1/2 половина" мы пишем как 1/7 (середина периода).
MONTH_RU = {
    "январь": 1, "января": 1,
    "февраль": 2, "февраля": 2,
    "март": 3, "марта": 3,
    "апрель": 4, "апреля": 4,
    "май": 5, "мая": 5,
    "июнь": 6, "июня": 6,
    "июль": 7, "июля": 7,
    "август": 8, "августа": 8,
    "сентябрь": 9, "сентября": 9,
    "октябрь": 10, "октября": 10,
    "ноябрь": 11, "ноября": 11,
    "декабрь": 12, "декабря": 12,
}

UNKNOWN_DATE_MARKERS = (
    "пока не знаем",
    "не знаем",
    "уточняется",
)


# ─── DTO ─────────────────────────────────────────────────────────────────────


@dataclass
class DicefestGame:
    """Распарсенная карточка с dicefest.

    raw_html и raw отдаются «как есть» в staging — позволяет перепарсить
    при изменении селекторов БЕЗ повторного запроса к сайту.
    """

    slug: str
    page_url: str
    title_ru: str | None = None
    title_en: str | None = None
    publisher: str | None = None
    release_year: int | None = None
    release_month: int | None = None
    release_status: str | None = None       # data-status code (machine-readable)
    description: str | None = None
    cover_url: str | None = None
    raw_html: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ─── Pure parsers (тестируются на фикстурах без сети) ────────────────────────


def parse_card_html(html: str, slug: str) -> DicefestGame:
    """Распарсить HTML карточки игры. Возвращает DicefestGame со всеми
    полями, которые удалось вытащить (несуществующие — None).

    Никогда не бросает исключение из-за отсутствующих полей: dicefest
    может ре-вёрстать сайт, мы хотим деградировать gracefully и сохранить
    в staging хоть что-то.
    """
    soup = BeautifulSoup(html, "html.parser")
    page_url = f"{BASE_URL}/game/{slug}/"
    raw: dict[str, Any] = {}

    # ── title: первый text node в <h2>, остальное — UI lazy-load ──
    title_ru: str | None = None
    h2 = soup.find("h2")
    if h2:
        # find first NavigableString child (без recursing)
        for child in h2.children:
            if isinstance(child, str):
                t = child.strip()
                if t:
                    title_ru = t
                    break

    # ── description pairs (Издательство, Статус игры, Предзаказ, Старт продаж) ──
    pairs: dict[str, dict[str, str | None]] = {}
    for title_p in soup.find_all("p", class_="game-popup-description__title"):
        # Сосед — следующий <p> с классом game-popup-description__text.
        next_p = title_p.find_next_sibling("p")
        if not next_p or "game-popup-description__text" not in (next_p.get("class") or []):
            continue
        label = title_p.get_text(strip=True).rstrip(":").strip()
        value = next_p.get_text(separator=" ", strip=True)
        data_status = next_p.get("data-status")
        pairs[label] = {"value": value, "data_status": data_status}
    raw["description_pairs"] = pairs

    publisher = pairs.get("Издательство", {}).get("value") or None
    release_status_text = pairs.get("Статус игры", {}).get("value") or None
    release_status_code = pairs.get("Статус игры", {}).get("data_status") or None
    # Стратегия выбора даты: "Старт продаж" — финальная (релиз). Если она
    # известна — берём её. Иначе fallback на "Предзаказ" (он наступает раньше,
    # но даёт хоть какой-то ориентир по году).
    sales_text = pairs.get("Старт продаж", {}).get("value") or None
    preorder_text = pairs.get("Предзаказ", {}).get("value") or None
    sales_y, sales_m = _parse_release_date(sales_text)
    if sales_y is not None:
        release_year, release_month = sales_y, sales_m
        release_text = sales_text
    else:
        release_year, release_month = _parse_release_date(preorder_text)
        release_text = preorder_text or sales_text

    # ── features (players / clock / link) ──
    features: dict[str, str] = {}
    for icon_div in soup.find_all("div", class_=re.compile(r"game-popup-feature__icon--")):
        # Тип feature берём из суффикса класса --{kind}
        kind = None
        for cls in icon_div.get("class", []):
            if cls.startswith("game-popup-feature__icon--"):
                kind = cls.removeprefix("game-popup-feature__icon--")
                break
        if not kind:
            continue
        # Текст — соседний div game-popup-feature__text, ищем в общем родителе.
        parent = icon_div.parent or soup
        text_div = parent.find("div", class_="game-popup-feature__text")
        if text_div:
            features[kind] = text_div.get_text(separator=" ", strip=True)
    raw["features"] = features

    # ── cover: первый /upload/iblock/ из background-image url(...) ──
    cover_url: str | None = None
    cover_match = re.search(
        r"background-image:\s*url\(['\"]?(/upload/iblock/[^'\")]+)",
        html,
    )
    if cover_match:
        cover_url = BASE_URL + cover_match.group(1)

    # ── description: текст после "Описание от издателя:" ──
    description: str | None = None
    desc_marker = soup.find(string=re.compile(r"Описание от издателя"))
    if desc_marker:
        # Берём контейнер-родитель и его текст после маркера.
        container = desc_marker.parent
        # Поднимаемся к ближайшему div, чтобы захватить все <p> описания.
        while container is not None and container.name != "div":
            container = container.parent
        if container:
            full_text = container.get_text(separator="\n", strip=True)
            # Берём всё после "Описание от издателя:"
            idx = full_text.find("Описание от издателя:")
            if idx >= 0:
                description = full_text[idx + len("Описание от издателя:"):].strip() or None

    return DicefestGame(
        slug=slug,
        page_url=page_url,
        title_ru=title_ru,
        title_en=None,  # на текущей вёрстке dicefest не нашли отдельного title_en
        publisher=publisher,
        release_year=release_year,
        release_month=release_month,
        release_status=release_status_code or release_status_text,
        description=description,
        cover_url=cover_url,
        raw_html=html,
        raw={
            **raw,
            "release_text": release_text,
            "release_status_text": release_status_text,
        },
    )


def _parse_release_date(text: str | None) -> tuple[int | None, int | None]:
    """Извлечь (year, month) из строк вида:
      "Январь 2026"      → (2026, 1)
      "Декабрь 2025"     → (2025, 12)
      "2 половина 2026"  → (2026, 7)   (середина 2-й половины)
      "1 половина 2026"  → (2026, 1)
      "1 квартал 2026"   → (2026, 2)   (середина квартала)
      "2026"             → (2026, None)
      "пока не знаем когда :)" → (None, None)
    """
    if not text:
        return None, None
    low = text.lower()
    if any(marker in low for marker in UNKNOWN_DATE_MARKERS):
        return None, None
    year_m = re.search(r"\b(20\d{2})\b", text)
    year = int(year_m.group(1)) if year_m else None

    # Месяц по слову.
    month: int | None = None
    for word, num in MONTH_RU.items():
        if word in low:
            month = num
            break

    # "N половина" → 1 или 7
    if month is None:
        half_m = re.search(r"([12])\s*половин", low)
        if half_m:
            month = 1 if half_m.group(1) == "1" else 7

    # "N квартал" → 2/5/8/11 (середина квартала)
    if month is None:
        q_m = re.search(r"([1-4])\s*кварт", low)
        if q_m:
            quarter = int(q_m.group(1))
            month = (quarter - 1) * 3 + 2

    return year, month


def parse_listing_html(html: str) -> list[str]:
    """Извлечь slug'и игр из HTML листинга (главная или ?year=...).

    Вёрстка: ссылки `<a href="/game/{slug}/">`. Дедупликация — set().
    """
    return sorted(set(re.findall(r"/game/([a-zA-Z0-9_-]+)/?", html)))


# ─── I/O (httpx, тестируется через MockTransport) ────────────────────────────


async def fetch_with_retry(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET с экспоненциальным backoff на 429/5xx (паттерн из bgg.py:27)."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0.0, *RETRY_BACKOFFS]):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code in (429,) or resp.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"transient {resp.status_code}", request=resp.request, response=resp,
                )
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as e:
            last_exc = e
            continue
    assert last_exc is not None
    raise last_exc


async def fetch_listing(
    client: httpx.AsyncClient, year: int | None = None,
) -> tuple[list[str], str]:
    """Получить slug'и из листинга. year=None → главная (показывает текущий
    активный год по умолчанию). Возвращает (slugs, source_listing_label).
    """
    if year is None:
        url = f"{BASE_URL}/"
        label = "homepage"
    else:
        url = f"{BASE_URL}/?year={year}"
        label = f"year={year}"
    resp = await fetch_with_retry(client, url)
    return parse_listing_html(resp.text), label


async def collect_all_slugs(
    client: httpx.AsyncClient,
    only_year: int | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Собрать все слуги. Возвращает (sorted slugs, {slug: source_listing}).

    Если only_year задан — только тот год. Иначе — обход 2024/2025/2026 +
    homepage (на случай, если что-то висит вне годов).
    """
    slug_to_source: dict[str, str] = {}
    if only_year is not None:
        slugs, source = await fetch_listing(client, year=only_year)
        for s in slugs:
            slug_to_source[s] = source
        return sorted(slug_to_source), slug_to_source

    for year in (2024, 2025, 2026):
        try:
            slugs, source = await fetch_listing(client, year=year)
        except httpx.HTTPError as e:
            logger.warning("dicefest listing year=%d failed: %s", year, e)
            continue
        for s in slugs:
            slug_to_source.setdefault(s, source)
        # Вежливый паузой между листингами.
        await asyncio.sleep(RATE_LIMIT_SEC + random.uniform(0, RATE_LIMIT_JITTER_SEC))
    return sorted(slug_to_source), slug_to_source


async def fetch_card(client: httpx.AsyncClient, slug: str) -> str:
    """Скачать HTML карточки игры по slug."""
    url = f"{BASE_URL}/game/{slug}/"
    resp = await fetch_with_retry(client, url)
    return resp.text


# ─── DB upsert ───────────────────────────────────────────────────────────────


async def upsert_dicefest_raw(
    session: AsyncSession, game: DicefestGame, source_listing: str | None,
) -> int:
    """ON CONFLICT (slug) DO UPDATE — re-run обновляет ту же запись.

    promotion-поля (status / promoted_at / promoted_to_game_id / notes) НЕ
    трогаем при обновлении: оператор мог уже что-то промоушить, а парсер
    просто освежил сырые данные.
    """
    stmt = (
        pg_insert(DicefestRawGame.__table__)
        .values(
            slug=game.slug,
            page_url=game.page_url,
            title_ru=game.title_ru,
            title_en=game.title_en,
            publisher=game.publisher,
            release_year=game.release_year,
            release_month=game.release_month,
            release_status=game.release_status,
            description=game.description,
            cover_url=game.cover_url,
            raw_html=game.raw_html,
            raw=game.raw,
            source_listing=source_listing,
            fetched_at=datetime.now(timezone.utc),
        )
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["slug"],
        set_={
            "page_url": stmt.excluded.page_url,
            "title_ru": stmt.excluded.title_ru,
            "title_en": stmt.excluded.title_en,
            "publisher": stmt.excluded.publisher,
            "release_year": stmt.excluded.release_year,
            "release_month": stmt.excluded.release_month,
            "release_status": stmt.excluded.release_status,
            "description": stmt.excluded.description,
            "cover_url": stmt.excluded.cover_url,
            "raw_html": stmt.excluded.raw_html,
            "raw": stmt.excluded.raw,
            "source_listing": stmt.excluded.source_listing,
            "fetched_at": stmt.excluded.fetched_at,
        },
    ).returning(DicefestRawGame.id)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def get_existing_fresh_slugs(
    session: AsyncSession, slugs: list[str], fresher_than: timedelta,
) -> set[str]:
    """Slug'и, скачанные не раньше now() - fresher_than. Используется для
    пропуска уже скачанных при resume после падения."""
    if not slugs:
        return set()
    threshold = datetime.now(timezone.utc) - fresher_than
    stmt = select(DicefestRawGame.slug).where(
        DicefestRawGame.slug.in_(slugs),
        DicefestRawGame.fetched_at >= threshold,
    )
    result = await session.execute(stmt)
    return set(result.scalars().all())


# ─── Background job ──────────────────────────────────────────────────────────


async def _run_dicefest_import_job(job_id: int, payload: dict[str, Any]) -> None:
    """Фоновая задача — обходит dicefest, заполняет staging.

    Запускается через asyncio.create_task() из роутера, как `_run_bgg_import_job`
    в routers/imports.py:106. Своя сессия, чтобы не блокировать HTTP-handler.

    Прогресс/лог пишутся через LogBuffer (батчами раз в ~20 строк или 2с) —
    polling-frontend читает их через GET /import/jobs/{id}.
    """
    started = datetime.now(timezone.utc)
    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as session:
        # mark running
        job = await session.get(ImportJob, job_id)
        if job is None:
            logger.error("dicefest job %d not found", job_id)
            return
        job.status = "running"
        job.started_at = started
        await session.commit()

        buf = LogBuffer(session, job_id=job_id)
        try:
            buf.set_progress(phase="collecting", current=0, total=0, current_title=None)
            buf.log("Сбор списка slug'ов из листингов dicefest…")
            await buf.flush()

            async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
            ) as client:
                slugs, slug_to_source = await collect_all_slugs(
                    client, only_year=payload.get("only_year"),
                )
                if max_items := payload.get("max_items"):
                    slugs = slugs[:max_items]

                total = len(slugs)
                buf.set_progress(phase="parsing", current=0, total=total)
                buf.log(f"Найдено {total} slug'ов; начинаю парсинг карточек.")
                await buf.flush()

                # Resume: пропускаем уже скачанные за последние RAW_FRESH_DAYS.
                fresh_set = await get_existing_fresh_slugs(
                    session, slugs, timedelta(days=RAW_FRESH_DAYS),
                )
                if fresh_set:
                    buf.log(
                        f"Пропускаю {len(fresh_set)} уже скачанных за {RAW_FRESH_DAYS} дн.",
                    )

                for i, slug in enumerate(slugs):
                    buf.set_progress(current=i, current_title=slug)
                    if slug in fresh_set:
                        buf.log(f"[{i + 1}/{total}] {slug} — skip (fresh)")
                        await buf.maybe_flush()
                        continue
                    try:
                        html = await fetch_card(client, slug)
                        game = parse_card_html(html, slug)
                        await upsert_dicefest_raw(
                            session, game, source_listing=slug_to_source.get(slug),
                        )
                        title = (game.title_ru or "")[:80]
                        buf.log(f"[{i + 1}/{total}] {slug} — ok ({title})")
                        imported.append({"slug": slug, "title_ru": game.title_ru})
                    except Exception as e:  # noqa: BLE001 — батч идёт дальше
                        msg = f"{type(e).__name__}: {e}"
                        buf.log(f"[{i + 1}/{total}] {slug} — ERROR: {msg}")
                        errors.append({"slug": slug, "error": msg})
                    await buf.maybe_flush()
                    # Вежливый rate-limit к сайту.
                    await asyncio.sleep(
                        RATE_LIMIT_SEC + random.uniform(0, RATE_LIMIT_JITTER_SEC),
                    )

                # Финальный progress
                buf.set_progress(phase="done", current=total, current_title=None)

            # final state
            job = await session.get(ImportJob, job_id)
            assert job is not None
            job.status = "done"
            job.finished_at = datetime.now(timezone.utc)
            job.result = {
                "imported": imported,
                "errors": errors,
                "total_slugs": total,
                "skipped_fresh": len(fresh_set),
            }
            await session.commit()
            buf.log(
                f"Готово. Записано {len(imported)}, ошибок {len(errors)}, "
                f"skip {len(fresh_set)}.",
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("dicefest import job %d failed", job_id)
            job = await session.get(ImportJob, job_id)
            if job is not None:
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc)
                job.error = f"{type(e).__name__}: {e}"
                job.result = {"imported": imported, "errors": errors}
                await session.commit()
            buf.log(f"FATAL: {type(e).__name__}: {e}")
        finally:
            await buf.flush()
