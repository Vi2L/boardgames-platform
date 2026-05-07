"""Клиент Wikidata: SPARQL bulk-lookup + entity-API + парсер payload'а.

Адаптация ~/Projects/board_game_db/app/wikidata.py под async-стек catalog'а.

Алгоритм (см. plan):
1. `find_entities_by_bgg_ids(bgg_ids)` — один SPARQL `VALUES`-запрос на
   партию bgg_id. Возвращает dict bgg_id → list[Q-id].
2. `fetch_entity(qid)` — GET /Special:EntityData/{Q}.json. CDN-кеш Wikidata.
3. `parse_entity(payload, qid, languages)` — pure-функция: вытаскивает
   labels/aliases/descriptions для нужных языков. Тестируется без сети.

Rate-limit: token-bucket sleep между запросами (Wikidata best practice 1 req/s).
Retry: 5 попыток с экспоненциальным backoff на 429/5xx; учитываем `Retry-After`.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"
ENTITY_BASE = "https://www.wikidata.org/wiki/Special:EntityData"
RETRYABLE = {429, 500, 502, 503, 504}


class WikidataError(RuntimeError):
    pass


@dataclass
class WikidataEntity:
    """Распарсенная игра из entity-API. Готова для upsert в game_wikidata."""

    entity_id: str
    found: bool
    labels: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, list[str]] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    bgg_ids: list[str] = field(default_factory=list)
    matched_entities: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def parse_entity(
    payload: dict[str, Any],
    entity_id: str,
    matched_entities: list[str],
    languages: list[str],
) -> WikidataEntity:
    """Парсит ответ /Special:EntityData/{Q}.json для конкретного entity_id.

    Pure-функция — никакой сети. Тестируется фикстурой.
    """
    entity = payload.get("entities", {}).get(entity_id)
    if not isinstance(entity, dict):
        raise WikidataError(f"entity {entity_id} not in payload")

    labels = _by_language(entity.get("labels", {}), languages)
    aliases = _aliases_by_language(entity.get("aliases", {}), languages)
    descriptions = _by_language(entity.get("descriptions", {}), languages)
    bgg_ids = _claim_strings(entity, "P2339")

    return WikidataEntity(
        entity_id=entity_id,
        found=True,
        labels=labels,
        aliases=aliases,
        descriptions=descriptions,
        bgg_ids=bgg_ids,
        matched_entities=matched_entities,
        raw={
            "title": entity.get("title"),
            "pageid": entity.get("pageid"),
            "modified": entity.get("modified"),
        },
    )


def _by_language(raw: object, languages: list[str]) -> dict[str, str]:
    """Wikidata labels/descriptions: {lang: {language, value}}. Берём только value."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for lang in languages:
        node = raw.get(lang)
        if isinstance(node, dict) and isinstance(node.get("value"), str):
            out[lang] = node["value"]
    return out


def _aliases_by_language(raw: object, languages: list[str]) -> dict[str, list[str]]:
    """Aliases: {lang: [{language, value}, ...]}. Возвращаем только values."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for lang in languages:
        items = raw.get(lang, [])
        values: list[str] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("value"), str):
                    values.append(item["value"])
        if values:
            out[lang] = values
    return out


def _claim_strings(entity: dict[str, Any], property_id: str) -> list[str]:
    """Достаём string-значения claim'а (например, все P2339 = bgg_ids)."""
    claims = entity.get("claims", {}).get(property_id, [])
    out: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, str):
            out.append(v)
    return out


def _entity_sort_key(qid: str) -> int:
    m = re.fullmatch(r"Q(\d+)", qid)
    return int(m.group(1)) if m else 10**12


class WikidataClient:
    """Async-клиент с rate-limit + retry."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limit_seconds: float = 1.0,
        max_retries: int = 5,
    ) -> None:
        self._client = client
        self._rate = rate_limit_seconds
        self._max_retries = max_retries
        self._next_request_at = 0.0  # monotonic-time
        self._lock = asyncio.Lock()

    async def _throttle(self) -> None:
        """Ждём пока пройдёт rate_limit_seconds с прошлого запроса."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = self._next_request_at - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_request_at = max(now, self._next_request_at) + self._rate

    async def _get_json(
        self, url: str, params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            await self._throttle()
            try:
                resp = await self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last = exc
                await self._sleep_backoff(attempt, None)
                continue

            if resp.status_code in RETRYABLE:
                last = WikidataError(f"retryable {resp.status_code}")
                await self._sleep_backoff(attempt, resp)
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise WikidataError(
                    f"Wikidata {resp.status_code}: {resp.text[:200]}"
                ) from exc
            try:
                return resp.json()
            except ValueError as exc:
                raise WikidataError("invalid JSON") from exc
        raise WikidataError(f"failed after {self._max_retries} retries: {last}")

    async def _sleep_backoff(
        self, attempt: int, resp: httpx.Response | None
    ) -> None:
        if attempt >= self._max_retries:
            return
        retry_after = resp.headers.get("Retry-After") if resp else None
        if retry_after and retry_after.isdigit():
            sleep = min(60.0, float(retry_after))
        else:
            sleep = min(30.0, 2 ** (attempt - 1))
        logger.warning("wikidata retry attempt=%d sleep=%.1fs", attempt, sleep)
        await asyncio.sleep(sleep)

    async def find_entities_by_bgg_ids(
        self, bgg_ids: list[int]
    ) -> dict[int, list[str]]:
        """Bulk SPARQL: bgg_ids → {bgg_id: [Q-id, ...]}.

        Один HTTP-запрос на партию (типично 50-100 ID за раз).
        Wikidata SPARQL endpoint имеет ограничение по длине запроса (~256K),
        партии до 100 умещаются с большим запасом.
        """
        if not bgg_ids:
            return {}
        values = " ".join(f'"{i}"' for i in bgg_ids)
        query = f"""
        SELECT ?bgg ?item WHERE {{
          VALUES ?bgg {{ {values} }} .
          ?item wdt:P2339 ?bgg .
        }}
        """
        payload = await self._get_json(
            SPARQL_URL,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        out: dict[int, list[str]] = {}
        for binding in payload.get("results", {}).get("bindings", []):
            bgg_str = binding.get("bgg", {}).get("value", "")
            item_uri = binding.get("item", {}).get("value", "")
            if not bgg_str.isdigit():
                continue
            qid = item_uri.rstrip("/").rsplit("/", 1)[-1]
            if not qid.startswith("Q"):
                continue
            out.setdefault(int(bgg_str), []).append(qid)
        # Стабильный порядок Q-id (по числу) — для воспроизводимости.
        for k in out:
            out[k] = sorted(set(out[k]), key=_entity_sort_key)
        return out

    async def fetch_entity(
        self, qid: str, languages: list[str], matched: list[str]
    ) -> WikidataEntity:
        url = f"{ENTITY_BASE}/{qid}.json"
        payload = await self._get_json(url)
        return parse_entity(payload, qid, matched, languages)
