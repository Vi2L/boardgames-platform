"""Алгоритм сопоставления и diff для snapshot-ов поиска.

Стабильный ключ:
  sku → slug:normalized_title:age_min:players → slug:product_id

Без `external_id` (см. parsers-wishlist.md п. 1) ключ нестабилен между
разными прогонами, если `id` пересоздаётся: используем sku как первый
выбор, потом seo-стабильный fallback по нормализованному названию +
демографии (players, age_min); в крайнем случае — slug:id.

diff_snapshots(a, b) сопоставляет по ключу и сравнивает whitelist полей.
Поля: price_rub, image_url[_hd], description, players, age_min, playtime,
rules_url, extra. extra сравниваем целиком как сериализованный JSON
(stable sort), чтобы изменение порядка ключей не считалось диффом.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

# Поля для diff. Если поле невидимо в UI и не влияет на пользовательскую
# трактовку — сюда не добавлять (например, fetched_at не diff'аем,
# иначе каждый refresh давал бы Δ).
DIFF_FIELDS: tuple[str, ...] = (
    "price_rub", "title", "image_url", "image_url_hd", "description",
    "players", "age_min", "playtime", "rules_url", "url", "extra",
)


_NON_ALNUM = re.compile(r"[^\w\s]+", flags=re.UNICODE)


def _normalize_title(title: str) -> str:
    """lower-case + удалить пунктуацию + сжать пробелы."""
    s = title.lower()
    s = _NON_ALNUM.sub(" ", s)
    return " ".join(s.split())


def product_key(product: dict[str, Any]) -> str:
    """Возвращает стабильный ключ для сопоставления в diff.

    Порядок предпочтений:
      1. sku из extra (HobbyGames почти всегда, GaGa часто) — самый стабильный;
      2. slug:normalized_title:age_min:players — устойчиво при пересоздании id;
      3. slug:id — fallback, ок если БД не пересоздавалась между snapshot-ами.
    """
    slug = product.get("store_slug") or "?"
    extra = product.get("extra") or {}

    sku = extra.get("sku") if isinstance(extra, dict) else None
    if isinstance(sku, str) and sku.strip():
        return f"{slug}:sku:{sku.strip()}"

    title = product.get("title") or ""
    age_min = product.get("age_min")
    players = product.get("players") or ""
    if title:
        return f"{slug}:title:{_normalize_title(title)}:{age_min or ''}:{players}"

    pid = product.get("id")
    return f"{slug}:id:{pid}"


def _stable_json(value: Any) -> str:
    """Сериализация с сортировкой ключей — для устойчивого сравнения dict-полей."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _values_equal(a: Any, b: Any) -> bool:
    """Эквивалентность значений: dict/list сравниваем через стабильную JSON-сериализацию."""
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return _stable_json(a) == _stable_json(b)
    return a == b


def _classify_change(field: str, av: Any, bv: Any) -> str:
    """Категория изменения — для UI-фильтров и бейджей.

      - 'lost'      — значение было, стало null/empty (регрессия парсера);
      - 'gained'    — наоборот, поле появилось (улучшение);
      - 'price'     — изменилась цена;
      - 'raw'       — изменился ключ внутри extra (raw_json парсера);
      - 'field'     — обычное изменение значения.
    """
    if field == "price_rub":
        return "price"
    if field.startswith("extra."):
        return "raw"
    a_empty = av is None or av == "" or av == [] or av == {}
    b_empty = bv is None or bv == "" or bv == [] or bv == {}
    if a_empty and not b_empty:
        return "gained"
    if b_empty and not a_empty:
        return "lost"
    return "field"


def diff_products(a: dict[str, Any], b: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Возвращает {field: {a, b, [delta_pct], category}} для всех изменённых полей.

    `extra` разбирается покустно: вместо одного entry 'extra' собираем
    отдельные `extra.gallery`, `extra.sku`, `extra.dimensions`, ... — это
    даёт UI-у точный diff и категорию 'raw'.
    """
    changes: dict[str, dict[str, Any]] = {}
    for field in DIFF_FIELDS:
        av = a.get(field)
        bv = b.get(field)

        # extra: разбиваем по ключам, чтобы UI видел gallery vs sku vs dimensions
        # как отдельные изменения, а не одно «extra изменилось целиком».
        if field == "extra":
            ad = av if isinstance(av, dict) else {}
            bd = bv if isinstance(bv, dict) else {}
            for k in sorted(set(ad) | set(bd)):
                if not _values_equal(ad.get(k), bd.get(k)):
                    sub = f"extra.{k}"
                    changes[sub] = {
                        "a": ad.get(k),
                        "b": bd.get(k),
                        "category": _classify_change(sub, ad.get(k), bd.get(k)),
                    }
            continue

        if not _values_equal(av, bv):
            entry: dict[str, Any] = {
                "a": av,
                "b": bv,
                "category": _classify_change(field, av, bv),
            }
            if field == "price_rub" and isinstance(av, (int, float)) and isinstance(bv, (int, float)) and av:
                entry["delta_pct"] = round((bv - av) / av * 100, 2)
            changes[field] = entry
    return changes


def diff_snapshots(
    products_a: Iterable[dict[str, Any]],
    products_b: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Сравнивает два snapshot-а товаров.

    Возвращает структуру:
        {
          "summary": {"a_count", "b_count", "added", "removed", "changed"},
          "products": [
             {"key", "status": "added"|"removed"|"changed"|"same",
              "fields"?: {...}, "a"?: dict, "b"?: dict}
          ]
        }
    """
    a_map = {product_key(p): p for p in products_a}
    b_map = {product_key(p): p for p in products_b}

    keys = sorted(set(a_map) | set(b_map))
    items: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0, "same": 0}

    for k in keys:
        a = a_map.get(k)
        b = b_map.get(k)
        if a is None and b is not None:
            items.append({"key": k, "status": "added", "b": b})
            counts["added"] += 1
        elif b is None and a is not None:
            items.append({"key": k, "status": "removed", "a": a})
            counts["removed"] += 1
        elif a is not None and b is not None:
            fields = diff_products(a, b)
            if fields:
                items.append({"key": k, "status": "changed", "a": a, "b": b, "fields": fields})
                counts["changed"] += 1
            else:
                # «same» в выдаче не показываем (фронт фильтрует), но считаем
                counts["same"] += 1

    # Подсчёт категорий для верхней сводки UI: сколько товаров с
    # потерянным полем, сколько с raw-изменением и т.п.
    cat_counts = {"price": 0, "lost": 0, "gained": 0, "raw": 0, "field": 0}
    for it in items:
        if it.get("status") != "changed":
            continue
        cats_in_item = set()
        for f in (it.get("fields") or {}).values():
            if isinstance(f, dict) and f.get("category"):
                cats_in_item.add(f["category"])
        for c in cats_in_item:
            cat_counts[c] = cat_counts.get(c, 0) + 1

    return {
        "summary": {
            "a_count": len(a_map),
            "b_count": len(b_map),
            **counts,
            "categories": cat_counts,
        },
        "products": items,
    }
