"""Provider-agnostic слой источников данных каталога.

Сервис актуализации работает в две фазы:
  1. Detection — скрапим источник, складываем items в `source_scrape_runs` /
     `source_scrape_items`. Staging (`dicefest_raw_games` и т.п.) при этом
     НЕ трогается. Получаем diff: сколько новых, сколько изменилось.
  2. Apply — оператор смотрит diff в UI и решает, что переносить в staging.

Цель пакета — единый интерфейс под будущие источники (BGA, Dicebreaker,
Wikidata-bulk). DicefestSourceScraper уже работает; новые провайдеры
реализуют тот же протокол `SourceScraper` и регистрируются в `REGISTRY`.
"""
from catalog.sources.base import (
    REGISTRY,
    ScraperParams,
    SourceItemPayload,
    SourceScraper,
    get_scraper,
)
from catalog.sources.dicefest import DicefestSourceScraper

# Регистрируем известные провайдеры. Строки `provider` совпадают с теми, что
# хранятся в БД (`source_scrape_runs.provider`, `match_profiles.provider`,
# `import_promotion_log.provider`).
REGISTRY[DicefestSourceScraper.provider] = DicefestSourceScraper

__all__ = [
    "REGISTRY",
    "ScraperParams",
    "SourceItemPayload",
    "SourceScraper",
    "get_scraper",
    "DicefestSourceScraper",
]
