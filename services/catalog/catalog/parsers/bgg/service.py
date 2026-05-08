"""Оркестратор BGG: связывает client + parser + repository в high-level операции.

На текущем этапе:
- `search_games(query, limit)` — поиск по запросу.

На этапе 2 добавятся:
- `enrich_one(bgg_id)` — fetch + parse + upsert одной игры.
- `enrich_batch(rank_le=N, batch_size=20)` — batch-обогащение топ-N.
"""
from __future__ import annotations

from catalog.parsers.bgg.client import BggClient
from catalog.parsers.bgg.models import BggSearchHit
from catalog.parsers.bgg.parser import parse_search_xml


async def search_games(
    query: str,
    *,
    limit: int = 20,
    exact: bool = False,
    client: BggClient | None = None,
) -> list[BggSearchHit]:
    """Поиск игр по запросу через BGG `/search`.

    BGG не поддерживает параметр limit на стороне API — отдаёт всё,
    что нашёл. Усечение делаем сами.

    `client=None` → создаём свой `BggClient` на одну операцию. Для
    сценария «много поисков подряд» (batch enrich на этапе 2) лучше
    передавать готовый client снаружи, чтобы переиспользовать TCP/TLS.
    """
    own_client = client is None
    if client is None:
        client = BggClient()
    try:
        if own_client:
            await client.__aenter__()
        xml_text = await client.search(query, exact=exact)
    finally:
        if own_client:
            await client.__aexit__(None, None, None)

    hits = parse_search_xml(xml_text)
    if limit > 0:
        hits = hits[:limit]
    return hits
