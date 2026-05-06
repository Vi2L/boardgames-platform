from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import ParsedProduct, StoreInfo


@dataclass
class ParserMetrics:
    """Метрики последнего вызова parser.search() — заполняются самим парсером.

    Сервис читает их через `parser.last_metrics` и передаёт в `db.log_parser()`.
    Все поля Optional, чтобы парсер мог отрапортовать только то, что измеряет
    (например, у CrowdGames нет enrich-этапа — `enrich_ms` будет None).
    """
    search_ms: int | None = None
    enrich_ms: int | None = None
    http_requests: int = 0
    result_after_enrich: int = 0


class StoreParser(ABC):
    """Базовый класс для всех парсеров магазинов.

    Чтобы добавить новый магазин:
    1. Создать модуль в parsers/stores/<slug>.py
    2. Унаследоваться от StoreParser
    3. Задать атрибут store: StoreInfo
    4. Реализовать метод search() — возвращает list[ParsedProduct]
       и устанавливает self.last_metrics для аналитики dashboard'а
    5. Зарегистрировать экземпляр в parsers/api.py:lifespan()

    Контракт метрик (опционально, но желательно):
    - В начале search() сбросить self._http_counter = 0 и self.last_metrics = None
    - Передать `event_hooks={"request": [self._count_request]}` в httpx.AsyncClient
      (метод _count_request есть в этом классе)
    - Замерить `time.monotonic()` вокруг search-запроса → search_ms
    - Замерить вокруг asyncio.gather(*enrich) → enrich_ms (если enrich есть)
    - В конце установить self.last_metrics = ParserMetrics(...)
    """

    store: StoreInfo

    def __init__(self) -> None:
        self.last_metrics: ParserMetrics | None = None
        self._http_counter: int = 0

    async def _count_request(self, request) -> None:
        """httpx event hook для подсчёта HTTP-вызовов внутри search()."""
        self._http_counter += 1

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        """Найти товары по запросу.

        Должен вернуть пустой список при отсутствии результатов.
        При сетевой или парсинговой ошибке — поднять исключение
        (PriceService поймает его и запишет в SearchResult.errors).
        """
        ...
