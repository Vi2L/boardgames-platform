"""Title pre-processing pipeline для матчинга названий настольных игр.

Применяется ДО `normalize_title()` — чтобы pg_trgm T1 и Tier 0 cache lookup
работали на «чистом» тексте. Решает типичные случаи WB/Avito/Ozon:

  «Hobby World Настольная игра Каркассон базовая версия»  → «Каркассон»
  «GaGa Games: Колонизаторы (2-е изд.)»                    → «Колонизаторы»
  «Каркассон Арт. 12345»                                   → «Каркассон»
  «КАРКАССОН — настольная игра (Hobby World, 2023)»        → «КАРКАССОН»

Архитектура:
  - `TitlePipeline` — иммутабельный value object, держит список префиксов.
  - `process(title)` — синхронная, без БД. Применяет все шаги.
  - `load_pipeline(session)` — async, читает префиксы из БД и кеширует на
    `_CACHE_TTL_SEC` секунд в module-level переменной.

Кеш сделан простым TTL'ом без блокировок: гонки между fastapi-request'ами
безвредны (две одинаковые загрузки префиксов вместо одной — ок), но они
крайне маловероятны при TTL 5 мин.

Пайплайн (порядок важен):
  1. strip_publisher_prefix — из таблицы `match_publisher_prefixes`
  2. strip_marketing_words — «Настольная игра», «Н/И», «Подарочное издание»
  3. strip_edition_marker — «2-е изд», «2е издание», «expansion», «дополнение»
  4. strip_artikul — «Арт. 12345», «Артикул XX-YY»
  5. strip_year — «(2023)», «[2024]» в конце
  6. normalize_punctuation — типографские тире → пробел
  7. strip — финальная чистка пробелов и пунктуации по краям

Не делает lower/unaccent — это задача `normalize_title()` после пайплайна.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


# Module-level кеш: (loaded_at, sorted_prefixes_tuple).
# tuple — иммутабельный, безопасно делиться между потоками без копирования.
_CACHE: tuple[float, tuple[str, ...]] | None = None
_CACHE_TTL_SEC = 300  # 5 минут


# Маркетинговые слова — «настольная игра», «н/и», «подарочное издание» и т.п.
# Все на русском, потому что EN-магазины (BGG) такого мусора не присылают.
_MARKETING_RE = re.compile(
    r'\b('
    r'настольная\s+игра(?:\s+для\s+(?:взрослых|детей|всей\s+семьи))?|'
    r'наст\.\s*игра|'
    r'н\s*/\s*и|'
    r'подарочн(?:ое|ая|ый|ой)\s+(?:издание|версия|набор|вариант)|'
    r'делюкс(?:\s+(?:версия|издание))?|'
    r'премиум(?:\s+(?:версия|издание))?|'
    r'эксклюзив(?:\s+(?:версия|издание))?|'
    r'коллекционн(?:ое|ая)\s+(?:издание|версия)|'
    r'юбилейн(?:ое|ая)\s+(?:издание|версия)'
    r')\b',
    re.IGNORECASE,
)


# Edition markers — «2-е изд», «2е изд», «второе издание», «5th edition»,
# «новое издание», «base set», «big box».
_EDITION_RE = re.compile(
    r'(?:'
    # «(2-е изд.)», «2-е изд», «5-я редакция»
    r'\(?\s*\d{1,2}[-\s]*[еэйая]\s*(?:изд(?:ание|\.)?|редакц(?:ия|\.)?|версия)\s*\)?|'
    # Порядковые числительные словом: «первое издание», «второе издание»,
    # «третья редакция». Кейс из реального WB/Avito: «Великий западный путь
    # второе издание с допом». Окончания: -ое (ср.р.), -ая (ж.р.), -ый/ий
    # (м.р.), -ье/ья (для «третье/третья»).
    r'\(?\s*(?:перв|втор|трет|четвёрт|четверт|пят|шест|седьм|восьм|девят|десят)'
    r'(?:ое|ая|ый|ий|ье|ья)\s+(?:изд(?:ание|\.)?|редакц(?:ия|\.)?|версия)\s*\)?|'
    # «2nd edition», «5th ed.»
    r'\(?\s*\d{1,2}(?:st|nd|rd|th)?\s*edition\b\)?|'
    r'\(?\s*\d{1,2}(?:st|nd|rd|th)?\s*ed\.\s*\)?|'
    # «новое издание», «обновлённое издание», «расширенное издание»
    r'\(?\s*(?:новое|расширенное|обновлённое|обновленное)\s+издание\s*\)?|'
    # «(базовая версия)», «базовый набор», «basic set», «base game»
    r'\(?\s*базов(?:ая\s+версия|ый\s+набор|ое\s+издание)\s*\)?|'
    r'\b(?:base|basic)\s+(?:set|game)\b|'
    # «big box», «complete edition»
    r'\bbig\s+box\b|\bcomplete\s+edition\b'
    r')',
    re.IGNORECASE,
)


# Артикулы магазинов — «Арт. 12345», «Артикул XX-YY», «art.B1234».
_ARTIKUL_RE = re.compile(
    r'\bарт(?:икул)?\.?\s*[№#:.]?\s*[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-]*\b',
    re.IGNORECASE,
)


# Год в скобках в конце title: «(2023)», «[2024]». Без скобок не трогаем —
# год может быть частью названия игры («1984»). Диапазон 1980-2029 покрывает
# реальный возраст бордгеймов в каталоге.
_YEAR_RE = re.compile(
    r'[\(\[]\s*(?:19[89]\d|20[0-2]\d)\s*[\)\]]',
)


# Типографские тире и длинные дефисы → обычный пробел. Решает кейс
# «Hobby World — Каркассон» где `—` не дробится strip_publisher_prefix'ом.
_PUNCT_NORM_RE = re.compile(r'[—–]')
_MULTI_SPACE_RE = re.compile(r'\s+')


@dataclass(frozen=True)
class TitlePipeline:
    """Snapshot конфигурации пайплайна.

    Иммутабельность — потокобезопасность из коробки. Создавать через
    `load_pipeline()`, не напрямую (важно: prefixes должны быть отсортированы
    по длине DESC для greedy matching).
    """

    prefixes: tuple[str, ...]

    def process(self, title: str) -> str:
        """Применяет все 7 шагов пайплайна. Чистая функция, без БД."""
        s = title
        # 1. Publisher prefix (greedy, по самому длинному)
        s = strip_publisher_prefix(s, self.prefixes)
        # 2. Marketing words → пробел (чтобы не схлопывать соседние токены)
        s = _MARKETING_RE.sub(' ', s)
        # 3. Edition markers
        s = _EDITION_RE.sub(' ', s)
        # 4. Артикулы
        s = _ARTIKUL_RE.sub(' ', s)
        # 5. Год в скобках на конце
        s = _YEAR_RE.sub(' ', s)
        # 6. Типографские тире → пробел
        s = _PUNCT_NORM_RE.sub(' ', s)
        # 7. Схлопываем пробелы и срезаем пунктуацию по краям
        s = _MULTI_SPACE_RE.sub(' ', s).strip(' :;,.-_|')
        return s


def strip_publisher_prefix(
    title: str, prefixes: tuple[str, ...] | list[str]
) -> str:
    """Удаляет самый длинный подходящий префикс из начала title.

    Сравнение case-insensitive. После префикса срезаются разделители: пробел,
    `:`, `-`, `—`, `–`, `|`, `;`, `.`. Если ни один префикс не подошёл —
    возвращает исходный title без изменений.

    Префиксы ожидаются уже отсортированными по длине DESC (greedy first match
    самой длинной строки). Это даёт правильное поведение, если в БД есть
    «Hobby World» и «Hobby World -»: длинный matches'нется раньше, и не
    оставит висящего разделителя.
    """
    if not title:
        return title
    low = title.lower()
    for prefix in prefixes:
        pl = prefix.lower()
        if low.startswith(pl):
            rest = title[len(prefix):]
            return rest.lstrip(' :-—–|;._')
    return title


async def load_pipeline(
    session: AsyncSession, *, force_reload: bool = False
) -> TitlePipeline:
    """Загружает активные publisher prefixes из БД и кеширует на 5 минут.

    При первом вызове или после `force_reload=True` — SELECT из
    `match_publisher_prefixes` WHERE `is_active=TRUE`. Сортировка по длине
    DESC для greedy matching (длинные префиксы matches'аются первыми).

    Без force_reload и при свежем кеше — возвращает существующий
    TitlePipeline мгновенно (без SQL).
    """
    global _CACHE
    now = time.monotonic()
    if not force_reload and _CACHE is not None:
        loaded_at, prefixes = _CACHE
        if now - loaded_at < _CACHE_TTL_SEC:
            return TitlePipeline(prefixes=prefixes)

    # Lazy-import: позволяет импортировать сам модуль (для тестов process())
    # даже если ORM-модель ещё не существует в момент импорта (например,
    # при первичной инициализации alembic-миграции).
    from catalog.models import MatchPublisherPrefix

    rows = (
        await session.execute(
            select(MatchPublisherPrefix.prefix)
            .where(MatchPublisherPrefix.is_active.is_(True))
            .order_by(func.length(MatchPublisherPrefix.prefix).desc())
        )
    ).scalars().all()

    prefixes = tuple(rows)
    _CACHE = (now, prefixes)
    return TitlePipeline(prefixes=prefixes)


def reset_cache() -> None:
    """Сбрасывает module-level кеш.

    Используется в:
      - тестах (между сценариями, чтобы стейл-кеш не влиял);
      - endpoint'е `POST /matching/pipeline/reload` (после CRUD prefixes).
    """
    global _CACHE
    _CACHE = None
