"""Pure-функции парсинга BGG XML.

Без сети, без БД — на вход строка XML, на выход dataclass из `models.py`.
Тестируются на статических фикстурах в `tests/fixtures/bgg_*.xml`.

Особенности BGG XML:
- `<items><item id type><name type="primary|alternate" value/>...</item></items>`
- Designers / publishers / categories / mechanics — все через единый
  `<link type="boardgame{designer|publisher|category|mechanic}" value/>`.
- `/thing` отдаёт `<statistics><ratings><average value/><bayesaverage value/>`.
- `/search` отдаёт минимум полей — только name и yearpublished.
"""
from __future__ import annotations

from collections.abc import Callable
from xml.etree import ElementTree as ET

from catalog.parsers.bgg.models import (
    BggFamily,
    BggGame,
    BggGeeklistItem,
    BggGeeklistMeta,
    BggHotnessItem,
    BggSearchHit,
)


def _int_attr(elem: ET.Element | None, attr: str = "value") -> int | None:
    """Безопасный извлекатель int-атрибута: None при отсутствии или невалидном значении."""
    if elem is None:
        return None
    val = elem.attrib.get(attr)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _float_attr(elem: ET.Element | None, attr: str = "value") -> float | None:
    if elem is None:
        return None
    val = elem.attrib.get(attr)
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def parse_geeklist_xml(xml_text: str) -> tuple[BggGeeklistMeta, list[BggGeeklistItem]]:
    """Парсит ответ BGG XML API `/xmlapi2/geeklist/{id}`.

    Формат ответа:
        <geeklist id="367126" termsofuse="...">
          <postdate>...</postdate>
          <numitems>50</numitems>
          <username>BGG_Admin</username>
          <title>BGG Top 50 Most Played - October 2025</title>
          <description>...</description>
          <item id="..." objecttype="thing" subtype="boardgame"
                objectid="123" objectname="Catan" username="..." ...>
            <body>Куратор-комментарий</body>
          </item>
          ...
        </geeklist>

    Возвращает (meta, items). rank в items — позиция в списке (1-based) по
    порядку appearance: для curated-топов это и есть искомый ранг.

    Не-`thing`/не-`boardgame` items пропускаются (BGG GeekList может содержать
    rpg/videogame/person — нам нужны только настольные игры).
    """
    root = ET.fromstring(xml_text)
    if root.tag != "geeklist":
        raise ValueError(f"ожидался <geeklist>, получен <{root.tag}>")

    geeklist_id = int(root.attrib.get("id", "0"))

    def _text(tag: str) -> str | None:
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else None

    item_count_str = _text("numitems")
    try:
        item_count = int(item_count_str) if item_count_str else 0
    except ValueError:
        item_count = 0

    meta = BggGeeklistMeta(
        geeklist_id=geeklist_id,
        title=_text("title"),
        description=_text("description"),
        username=_text("username"),
        item_count=item_count,
    )

    items: list[BggGeeklistItem] = []
    rank = 0
    for item in root.findall("item"):
        # Фильтруем не-boardgame позиции. BGG GeekList может смешивать типы.
        if item.attrib.get("objecttype") != "thing":
            continue
        if item.attrib.get("subtype") not in (None, "boardgame", "boardgameexpansion"):
            continue
        try:
            bgg_id = int(item.attrib["objectid"])
        except (KeyError, ValueError):
            continue
        name = item.attrib.get("objectname") or ""
        if not name:
            continue
        body_el = item.find("body")
        body = body_el.text.strip() if body_el is not None and body_el.text else None
        rank += 1
        items.append(BggGeeklistItem(rank=rank, bgg_id=bgg_id, name=name, body=body))

    return meta, items


def parse_hot_xml(xml_text: str) -> list[BggHotnessItem]:
    """Парсит ответ BGG XML API `/hot?type=boardgame`.

    Формат ответа:
        <items termsofuse="...">
          <item rank="1" id="224517">
            <thumbnail value="//cf.geekdo-images.com/..."/>
            <name value="Brass: Birmingham"/>
            <yearpublished value="2018"/>
          </item>
          ...
        </items>

    Отличается от /thing: поля — атрибуты дочерних элементов (не самого <item>).
    """
    root = ET.fromstring(xml_text)
    items: list[BggHotnessItem] = []
    for item in root.findall("item"):
        try:
            bgg_id = int(item.attrib["id"])
            rank = int(item.attrib["rank"])
        except (KeyError, ValueError):
            continue

        name_el = item.find("name")
        name = name_el.attrib.get("value", "") if name_el is not None else ""
        if not name:
            continue

        thumb_el = item.find("thumbnail")
        thumbnail_url: str | None = None
        if thumb_el is not None:
            raw = thumb_el.attrib.get("value", "")
            # BGG возвращает protocol-relative URL: //cf.geekdo-images.com/...
            thumbnail_url = f"https:{raw}" if raw.startswith("//") else raw or None

        items.append(
            BggHotnessItem(
                rank=rank,
                bgg_id=bgg_id,
                name=name,
                year=_int_attr(item.find("yearpublished")),
                thumbnail_url=thumbnail_url,
            )
        )
    return items


# ── BGG <poll> helpers (CAT-6) ────────────────────────────────────────────────
#
# В /thing встречается три poll'а: suggested_numplayers (per-count breakdown),
# suggested_playerage (winning возраст из голосов), language_dependence (1..5).
# Структура `<result>` плоская в age/lang и вложенная в numplayers — поэтому
# numplayers идёт собственным парсером, остальные через общий `_poll_winner`.


def _age_transform(value: str) -> int | None:
    """`"21 and up"` → 21; `"8"` → 8; мусор → None.

    BGG отдаёт верхний bucket текстом "21 and up" — обрабатываем как минимальный
    возраст bucket'а. Прочие нечисловые значения BGG не отдаёт, но безопасно
    игнорируем.
    """
    if not value:
        return None
    first_word = value.strip().split()[0]
    try:
        return int(first_word)
    except ValueError:
        return None


def _lang_level_transform(elem: ET.Element) -> int | None:
    """Извлекает 1..5 из `<result level="N" value="..."/>`.

    BGG language_dependence хранит уровень в атрибуте `level`; `value` — это
    описательная фраза («Some necessary text...»). Если `level` отсутствует —
    пробуем распарсить `value` как число (на случай изменения формата).
    """
    level = elem.attrib.get("level")
    if level is not None:
        try:
            return int(level)
        except ValueError:
            return None
    val = elem.attrib.get("value", "")
    try:
        return int(val)
    except ValueError:
        return None


def _poll_winner(
    results: list[ET.Element],
    value_extractor: Callable[[ET.Element], int | None],
) -> int | None:
    """Возвращает значение с максимальным `numvotes`. Tie → min из tied values.

    Пустой список / нулевые голоса → None. Tie-break через `min()` — более
    «консервативная» рекомендация: при равенстве выбираем меньший возраст и
    меньший уровень language-dependence.
    """
    best_votes = 0
    winners: list[int] = []
    for elem in results:
        try:
            votes = int(elem.attrib.get("numvotes", "0"))
        except ValueError:
            votes = 0
        if votes <= 0:
            continue
        value = value_extractor(elem)
        if value is None:
            continue
        if votes > best_votes:
            best_votes = votes
            winners = [value]
        elif votes == best_votes:
            winners.append(value)
    if not winners:
        return None
    return min(winners)


def _parse_numplayers_poll(item: ET.Element) -> dict[str, dict[str, int]] | None:
    """Распарсивает `<poll name="suggested_numplayers">` в raw-подсчёты per count.

    Возвращает `{"2": {"best": 100, "recommended": 200, "not_recommended": 50}, "6+": {...}}`.
    Ключи — строки (включая bucket "6+"). Значения — числа голосов.
    `None` если poll пустой (totalvotes=0) или отсутствует.
    """
    poll = item.find("poll[@name='suggested_numplayers']")
    if poll is None:
        return None
    try:
        total = int(poll.attrib.get("totalvotes", "0"))
    except ValueError:
        total = 0
    if total <= 0:
        return None

    out: dict[str, dict[str, int]] = {}
    # Маппим BGG-метки value="Best" → ключи в нашем JSONB. snake_case в Python,
    # человеко-читаемые подписи BGG отбрасываем.
    label_map = {
        "Best": "best",
        "Recommended": "recommended",
        "Not Recommended": "not_recommended",
    }
    for results in poll.findall("results"):
        np = results.attrib.get("numplayers")
        if not np:
            continue
        counts = {"best": 0, "recommended": 0, "not_recommended": 0}
        for r in results.findall("result"):
            key = label_map.get(r.attrib.get("value", ""))
            if key is None:
                continue
            try:
                counts[key] = int(r.attrib.get("numvotes", "0"))
            except ValueError:
                pass
        out[np] = counts
    return out or None


def _parse_age_poll(item: ET.Element) -> int | None:
    """Возвращает рекомендованный возраст: winning value из `suggested_playerage`.

    `"21 and up"` → 21; tie → min; totalvotes=0 → None.
    """
    poll = item.find("poll[@name='suggested_playerage']")
    if poll is None:
        return None
    try:
        total = int(poll.attrib.get("totalvotes", "0"))
    except ValueError:
        total = 0
    if total <= 0:
        return None
    results = poll.findall("results/result")
    return _poll_winner(
        results,
        lambda elem: _age_transform(elem.attrib.get("value", "")),
    )


def _parse_lang_dependence_poll(item: ET.Element) -> int | None:
    """Возвращает winning level (1..5) из `<poll name="language_dependence">`.

    Tie → min (консервативный выбор «меньше зависимости»). totalvotes=0 → None.
    """
    poll = item.find("poll[@name='language_dependence']")
    if poll is None:
        return None
    try:
        total = int(poll.attrib.get("totalvotes", "0"))
    except ValueError:
        total = 0
    if total <= 0:
        return None
    results = poll.findall("results/result")
    return _poll_winner(results, _lang_level_transform)


# ── /thing parser ─────────────────────────────────────────────────────────────


def parse_thing_xml(xml_text: str) -> BggGame | None:
    """Парсит ответ BGG XML API на запрос `/thing?id=<bgg_id>&stats=1`.

    Возвращает None, если игры с таким id нет (BGG отдаёт пустой `<items/>`).
    """
    root = ET.fromstring(xml_text)
    item = root.find("item")
    if item is None:
        return None

    bgg_id = int(item.attrib["id"])

    # Имена: одно primary + N alternate.
    primary_name = ""
    aliases: list[str] = []
    for name_el in item.findall("name"):
        if name_el.attrib.get("type") == "primary":
            primary_name = name_el.attrib.get("value", "")
        else:
            alt = name_el.attrib.get("value")
            if alt:
                aliases.append(alt)

    # Линки: designers / publishers / categories / mechanics / families — через `<link type=...>`.
    designers: list[str] = []
    publishers: list[str] = []
    categories: list[str] = []
    mechanics: list[str] = []
    families: list[tuple[int, str]] = []  # CAT-8: (family_id, family_name)
    for link in item.findall("link"):
        ltype = link.attrib.get("type")
        value = link.attrib.get("value", "")
        if ltype == "boardgamedesigner":
            designers.append(value)
        elif ltype == "boardgamepublisher":
            publishers.append(value)
        elif ltype == "boardgamecategory":
            categories.append(value)
        elif ltype == "boardgamemechanic":
            mechanics.append(value)
        elif ltype == "boardgamefamily":
            # `id` атрибут = bgg_family_id (целое), `value` = название семьи
            # («Series: Catan», «Components: Cards», и т.п.). Игнорируем
            # «битые» записи без id (защита от malformed XML).
            try:
                family_id = int(link.attrib.get("id", ""))
            except (ValueError, TypeError):
                continue
            families.append((family_id, value))

    description = None
    desc_el = item.find("description")
    if desc_el is not None and desc_el.text:
        description = desc_el.text

    image_el = item.find("image")
    thumb_el = item.find("thumbnail")

    # Статистика — внутри `<statistics><ratings>...`. Расширенные метрики
    # (users_rated, average_weight, num_weights) приходят при &stats=1 — флаг
    # включён в `BggClient.fetch_thing` по умолчанию.
    stats = item.find("statistics/ratings")
    rating_avg = _float_attr(stats.find("average") if stats is not None else None)
    rating_bayes = _float_attr(stats.find("bayesaverage") if stats is not None else None)
    users_rated = _int_attr(stats.find("usersrated") if stats is not None else None)
    average_weight = _float_attr(stats.find("averageweight") if stats is not None else None)
    num_weights = _int_attr(stats.find("numweights") if stats is not None else None)

    return BggGame(
        bgg_id=bgg_id,
        title=primary_name,
        aliases=aliases,
        year=_int_attr(item.find("yearpublished")),
        description=description,
        cover_url=image_el.text if image_el is not None and image_el.text else None,
        thumbnail_url=thumb_el.text if thumb_el is not None and thumb_el.text else None,
        designers=designers,
        publishers=publishers,
        players_min=_int_attr(item.find("minplayers")),
        players_max=_int_attr(item.find("maxplayers")),
        playtime_min=_int_attr(item.find("minplaytime")),
        playtime_max=_int_attr(item.find("maxplaytime")),
        age_min=_int_attr(item.find("minage")),
        categories=categories,
        mechanics=mechanics,
        rating_avg=rating_avg,
        rating_bayes=rating_bayes,
        users_rated=users_rated,
        average_weight=average_weight,
        num_weights=num_weights,
        recommended_players=_parse_numplayers_poll(item),
        recommended_age=_parse_age_poll(item),
        language_dependence=_parse_lang_dependence_poll(item),
        families=families,
    )


def parse_search_xml(xml_text: str) -> list[BggSearchHit]:
    """Парсит ответ BGG XML API на запрос `/search?query=<q>&type=boardgame`.

    Формат ответа:
        <items total="N">
          <item type="boardgame" id="822">
            <name type="primary" value="Carcassonne"/>
            <yearpublished value="2000"/>
          </item>
          ...
        </items>

    Пустой результат → пустой список (не None — search не имеет
    «нет такого id», только «ничего не нашлось»).

    Фильтруем по `type='boardgame'` на всякий случай — если bgg вдруг
    отдаст boardgameaccessory без `&type=boardgame`-фильтра, мы не
    поломаемся, просто пропустим лишнее.
    """
    root = ET.fromstring(xml_text)
    hits: list[BggSearchHit] = []
    for item in root.findall("item"):
        if item.attrib.get("type") != "boardgame":
            continue
        try:
            bgg_id = int(item.attrib["id"])
        except (KeyError, ValueError):
            continue

        # primary name — обязательно. Без него позиция бесполезна.
        title = ""
        for name_el in item.findall("name"):
            if name_el.attrib.get("type") == "primary":
                title = name_el.attrib.get("value", "")
                break
        if not title:
            continue

        hits.append(
            BggSearchHit(
                bgg_id=bgg_id,
                title=title,
                year=_int_attr(item.find("yearpublished")),
            )
        )
    return hits


def parse_family_xml(xml_text: str) -> BggFamily | None:
    """CAT-8: парсит `/xmlapi2/family/{id}` → BggFamily со списком thing-id членов.

    Формат:
        <items>
          <item type="boardgamefamily" id="20137">
            <name type="primary" value="Series: Carcassonne"/>
            <description>...</description>
            <link type="boardgamefamily" id="822" value="Carcassonne" inbound="true"/>
            ...
          </item>
        </items>

    `inbound="true"` означает «эта игра входит в эту семью» — то, что нам нужно.
    Возвращает None при пустом ответе (family-id не существует).
    """
    root = ET.fromstring(xml_text)
    item = root.find("item")
    if item is None or item.attrib.get("type") != "boardgamefamily":
        return None
    try:
        family_id = int(item.attrib["id"])
    except (KeyError, ValueError):
        return None

    name = ""
    for name_el in item.findall("name"):
        if name_el.attrib.get("type") == "primary":
            name = name_el.attrib.get("value", "")
            break

    description: str | None = None
    desc_el = item.find("description")
    if desc_el is not None and desc_el.text:
        description = desc_el.text

    members: list[int] = []
    for link in item.findall("link"):
        # Только inbound="true" — это связь «игра → семья», обратная связь
        # «семья → жанр» сюда тоже попадёт без фильтра, что нам не нужно.
        if link.attrib.get("inbound") != "true":
            continue
        try:
            members.append(int(link.attrib.get("id", "")))
        except (TypeError, ValueError):
            continue

    return BggFamily(
        bgg_family_id=family_id,
        name=name,
        description=description,
        members=members,
    )
