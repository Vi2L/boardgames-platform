"""Подсистема парсеров каталога настольных игр.

В отличие от `services/parsers/` (там парсятся офферы магазинов с ценами),
здесь живут парсеры **метаданных** игр: BGG, Wikidata, в перспективе Tesera.
Они наполняют canonical-таблицу `games` и satellite-таблицы (`game_bgg`,
`game_wikidata`, ...).

Каждый источник лежит в своей подпапке (`parsers/<source>/`) и состоит из:
- `client.py`     — тонкий httpx-клиент с rate-limit и retry-логикой
- `parser.py`     — pure-функции парсинга XML/JSON ответов
- `models.py`     — dataclasses для распарсенных данных
- `repository.py` — async upsert в SQLAlchemy (Game / Game<Source> / GameAlias)
- `service.py`    — оркестратор: search / enrich_one / enrich_batch / seed_full

Старый `catalog/importers/<source>.py` сохраняется как re-export shim
для обратной совместимости — `routers/imports.py` и `scripts/import_*` с ним
работают без изменений до плановой миграции.
"""
