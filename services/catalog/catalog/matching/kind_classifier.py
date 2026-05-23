"""Rule-based классификация «kind» оффера по тексту title (CAT-17.1).

Цель: предсказать `predicted_kind` ('base'|'expansion'|'promo'|'accessory') ещё
ДО эмбеддинга в T2, чтобы передать в `vec_search_top_k(kind_filter=...)`. Это
экономит embed-вызовы и улучшает precision: «Каркассон Король и Разбойник»
ищется только среди expansion'ов, не путается с базой.

API:
  - `classify_kind(title)` — синхронная функция, возвращает `str | None`.
    `None` означает «не уверен, скорее всего base» (caller передаёт None в
    `tier_2_vector(kind_filter=None)` — без фильтра, как раньше).

Использует только regex по lower'нутому title — без БД, без ML. Это
дешёвая heuristic, не претендует на 100% precision. Ошибочные случаи
исправляет LLM-арбитр T3 (он видит match_kind в кандидатах).
"""
from __future__ import annotations

import re


# Promo маркеры — самые специфичные, проверяем первыми
# (промо часто И expansion одновременно, но точнее всего — promo).
_PROMO_RE = re.compile(
    r'\b('
    r'промо|'
    r'promo|'
    r'мини[-\s]*доп(?:олнение)?|'
    r'мини[-\s]*расширение|'
    r'мини[-\s]*наб(?:ор)?|'
    r'набор\s+промо|'
    r'промо[-\s]*наб(?:ор)?'
    r')\b',
    re.IGNORECASE,
)


# Accessory маркеры
_ACCESSORY_RE = re.compile(
    r'\b('
    r'органайзер|'
    r'organizer|'
    r'inserts?|'
    r'вставка\s+(?:для|органайзер)|'
    r'card[-\s]*sleeves?|'
    r'протекторы(?:\s+для\s+карт)?|'
    r'кубики|'
    r'dice(?:\s+set|\s+tower)?|'
    r'(?:доп\.|дополнительн(?:ые|ый))\s+(?:карты|кубики|жетоны)|'
    r'replacement\s+(?:cards?|tokens?|tiles?)'
    r')\b',
    re.IGNORECASE,
)


# Expansion маркеры — самый широкий класс.
# Каждый alternation имеет свои \b, потому что после `exp.` нет word-boundary
# (точка → конец строки, оба non-word). Trailing `\b` для всей группы
# не работает в таких кейсах.
_EXPANSION_RE = re.compile(
    r'(?:'
    r'\bдополнение\b'
    r'|\bexpansion\b'
    r'|\bexp\.'             # без trailing \b — `.` non-word
    r'|\bextension\b'
    r'|\bаддон\b'
    r'|\badd[-\s]*on\b'
    r'|\bbig\s+box\b'
    r'|\bделюкс[-\s]*наб(?:ор)?\b'
    r'|\bdeluxe\s+(?:edition|set)\b'
    r'|\bextension\s+(?:pack|set)\b'
    r')',
    re.IGNORECASE,
)


def classify_kind(title: str) -> str | None:
    """Возвращает predicted kind по тексту title.

    Логика:
      1. Promo проверяется первым (часто перекрывается с expansion в тексте).
      2. Accessory — органайзеры, кубики, sleeves.
      3. Expansion — самый широкий класс.
      4. Если ничего не подошло — None (caller обычно передаёт None или 'base').

    Не возвращает 'base' явно — отсутствие маркеров не доказывает что это
    база (title может быть просто чистым «Каркассон Замки» — это expansion,
    но без слова «дополнение»). Caller должен решать сам.

    Примеры:
        classify_kind("Каркассон")                          → None
        classify_kind("Каркассон: дополнение Замки")        → 'expansion'
        classify_kind("Колонизаторы: промо-набор")          → 'promo'
        classify_kind("Органайзер для Брасс")               → 'accessory'
        classify_kind("Wingspan: European Expansion")       → 'expansion'
        classify_kind("Catan Big Box")                      → 'expansion'
    """
    if not title:
        return None
    low = title.lower()
    if _PROMO_RE.search(low):
        return 'promo'
    if _ACCESSORY_RE.search(low):
        return 'accessory'
    if _EXPANSION_RE.search(low):
        return 'expansion'
    return None
