"""Морфологическая нормализация русских названий через pymorphy3.

Закрывает кейс «Каркассона» (родительный падеж) vs «Каркассон» — pg_trgm
similarity на этих формах ~0.73, ниже T1 порога 0.92. После лемматизации
обе формы → «каркассон», score = 1.0.

API:
  - `lemmatize_ru(text)` — синхронная функция. Кириллические токены →
    нормальная форма; латиница/цифры/символы — без изменений (нижний регистр).
  - `get_analyzer()` — singleton MorphAnalyzer (тяжёлый, ~30МБ словарей).

Используется:
  - в `tier_1_trgm` для query-time лемматизации (`lemmatize_ru(title_clean)`);
  - в backfill-скрипте `backfill_title_lemma.py` для заполнения `games.title_lemma`;
  - в импортёрах BGG/Wikidata при upsert'е games (чтобы новые игры сразу
    имели `title_lemma`).

pymorphy3 — это форк pymorphy2 для Python 3.12+, MIT, активно поддерживается.
Альтернатива (mystem3) — медленнее на coldstart и требует separate binary;
для нашего объёма (162K игр + query-time на каждый ingest) — overkill.
"""
from __future__ import annotations

from functools import lru_cache


# Кириллический диапазон Unicode. Включает большие буквы, маленькие, ё, Ё.
# Используется для определения «русского» токена — лемматизировать только их.
_CYRILLIC_RANGES = (
    ('Ѐ', 'ӿ'),  # основная кириллица
    ('Ԁ', 'ԯ'),  # кириллица расширенная
)


def _is_cyrillic_token(token: str) -> bool:
    """Все символы токена — кириллица? Пустой токен → False."""
    if not token:
        return False
    for ch in token:
        if not any(start <= ch <= end for start, end in _CYRILLIC_RANGES):
            # Допускаем цифры внутри слова («2-е» уже не cyrillic-only после
            # разбиения по пробелам — но «-е» как отдельный токен → cyrillic).
            return False
    return True


@lru_cache(maxsize=1)
def get_analyzer():
    """Возвращает singleton MorphAnalyzer.

    Lazy-import pymorphy3 — словари ~30МБ грузятся при первом вызове (~2 сек).
    `@lru_cache(maxsize=1)` — один инстанс на процесс. Thread-safe для чтения
    (MorphAnalyzer.parse() — readonly после инициализации).
    """
    import pymorphy3  # lazy import — не тратим память пока не нужно

    return pymorphy3.MorphAnalyzer()


def has_cyrillic(text: str) -> bool:
    """True если в тексте есть хотя бы один кириллический символ.

    Проверяет оба диапазона: основная кириллица (`Ѐ–ӿ`) и расширенная
    (`Ԁ–ԯ`). Используется caller'ами как дешёвая heuristic «стоит ли вообще
    запускать лемматизацию» — для чисто латинских title (Wingspan, Catan)
    pymorphy3 бесполезен, и подгружать словари не нужно.
    """
    if not text:
        return False
    for ch in text:
        if any(start <= ch <= end for start, end in _CYRILLIC_RANGES):
            return True
    return False


def lemmatize_ru(text: str) -> str:
    """Лемматизирует русские токены, остальные оставляет в lowercase.

    Разбивает text по пробелам, для каждого токена:
      - кириллический → `MorphAnalyzer.parse(token)[0].normal_form` (lowercase);
      - иначе → `token.lower()`.

    Не делает unaccent — это работа `normalize_title()` после лемматизации.
    Если pymorphy3 не установлен — поднимает ImportError при первом вызове;
    caller обычно использует `safe_lemmatize_ru()` для graceful degradation.

    Примеры:
        lemmatize_ru("Каркассона")              → "каркассон"
        lemmatize_ru("Колонизаторы Catan")      → "колонизатор catan"
        lemmatize_ru("Hobby World 2023")        → "hobby world 2023"
        lemmatize_ru("")                         → ""
    """
    if not text:
        return ""
    analyzer = get_analyzer()
    tokens = text.split()
    result: list[str] = []
    for token in tokens:
        if _is_cyrillic_token(token):
            # parse() возвращает list[Parse], отсортированный по score DESC.
            # Берём наиболее вероятный разбор. Для имён собственных
            # («Каркассон» — несклоняемое в pymorphy3, тэг 'NOUN,inan,masc,Geox')
            # normal_form вернёт ту же форму.
            parsed = analyzer.parse(token)
            if parsed:
                result.append(parsed[0].normal_form)
            else:
                result.append(token.lower())
        else:
            result.append(token.lower())
    return " ".join(result)


def safe_lemmatize_ru(text: str) -> str | None:
    """Graceful обёртка над `lemmatize_ru`: возвращает None при отказе.

    pymorphy3 — обязательная зависимость catalog, но lazy-import + загрузка
    словарей при первом вызове могут упасть в нестандартном окружении
    (тестовый контейнер без словарей, конфликт версий). Caller использует
    None как «не передавать lemma_q в SQL» — pipeline продолжит работать
    без морфологии.

    Также возвращает None для:
      - пустых строк (нечего лемматизировать)
      - текстов без кириллицы (`Wingspan`, `Catan`) — pymorphy3 для них
        бесполезен, экономим вызов словарного analyzer'а.
    """
    if not text:
        return None
    if not has_cyrillic(text):
        return None
    try:
        return lemmatize_ru(text)
    except Exception:  # noqa: BLE001 — graceful: pymorphy3 / dictionaries / etc.
        import logging
        logging.getLogger(__name__).warning(
            "lemmatize_ru failed for text %r, fallback no-lemma", text,
        )
        return None
