"""Канонический хеш payload'а + diff полей.

content_hash используется detection-логикой как «отпечаток» карточки. Если
он совпадает с тем, что хранится в staging — карточка не менялась, можно
скипать. Иначе — пересчитываем field_diffs для UI.

Канонизация важна:
  * sort_keys=True — порядок ключей в dict не должен влиять на хеш.
  * исключаем шумящие поля (raw_html, fetched_at, source_listing).
  * списки внешних ссылок сортируем по url, чтобы перестановка не считалась
    изменением.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Поля payload'а, которые не должны участвовать в content_hash. raw_html
# тяжёлый и может различаться по timestamp'ам (например, токены сессии),
# fetched_at тривиально меняется при каждом скрапе.
_HASH_EXCLUDE_KEYS: frozenset[str] = frozenset(
    {"raw_html", "fetched_at", "source_listing"},
)

# Поля, которые имеет смысл показывать в UI как diff. raw_html и `raw`
# (сырой дамп для аудита) — слишком большие/шумные.
_DIFF_EXCLUDE_KEYS: frozenset[str] = frozenset(
    {"raw_html", "raw", "fetched_at", "source_listing"},
)


def _canonicalize(value: Any) -> Any:
    """Привести значение к каноническому виду для стабильного хеша.

    Ключевая хитрость — отсортировать списки словарей по 'url' (если есть),
    иначе по json-репрезентации. Парсер dicefest может возвращать ссылки в
    разном порядке от запуска к запуску — мы не хотим считать это
    изменением.
    """
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in value.items() if k not in _HASH_EXCLUDE_KEYS}
    if isinstance(value, list):
        # Если все элементы — dict с 'url', сортируем по нему. Иначе — по
        # json-репрезентации (детерминированно, без падения на не-сравнимых).
        canonical = [_canonicalize(item) for item in value]
        try:
            if canonical and all(isinstance(x, dict) for x in canonical):
                key_field = "url" if all("url" in x for x in canonical) else None
                if key_field:
                    return sorted(canonical, key=lambda x: x.get(key_field) or "")
            return sorted(
                canonical, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False),
            )
        except TypeError:
            # На случай экзотических типов — возвращаем как есть.
            return canonical
    return value


def compute_content_hash(payload: dict[str, Any]) -> str:
    """sha256 (hex, 64 символа) от канонического представления payload'а."""
    canonical = _canonicalize(payload)
    encoded = json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_field_diffs(
    prev: dict[str, Any] | None, curr: dict[str, Any],
) -> dict[str, dict[str, Any]] | None:
    """Вернуть `{field: {before, after}}` или None, если ничего не изменилось.

    `prev=None` интерпретируется как «записи раньше не было». В этом случае
    возвращаем None — это change_type='new', и весь payload и так показывается
    в UI без diff'а.

    Для list/dict сравнение делается по канонической форме — переставленные
    элементы списка не считаются изменением (в синхронизации с content_hash).
    """
    if prev is None:
        return None

    diffs: dict[str, dict[str, Any]] = {}
    keys = (set(prev) | set(curr)) - _DIFF_EXCLUDE_KEYS
    for k in sorted(keys):
        before = prev.get(k)
        after = curr.get(k)
        if _canonicalize(before) == _canonicalize(after):
            continue
        diffs[k] = {"before": before, "after": after}
    return diffs or None
