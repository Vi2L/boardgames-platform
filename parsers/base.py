from abc import ABC, abstractmethod

from .models import ParsedProduct, StoreInfo


class StoreParser(ABC):
    """Базовый класс для всех парсеров магазинов.

    Чтобы добавить новый магазин:
    1. Создать модуль в parsers/stores/<slug>.py
    2. Унаследоваться от StoreParser
    3. Задать атрибут store: StoreInfo
    4. Реализовать метод search()
    5. Зарегистрировать экземпляр в PriceService.__init__()
    """

    store: StoreInfo

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[ParsedProduct]:
        """Найти товары по запросу.

        Должен вернуть пустой список при отсутствии результатов.
        При сетевой или парсинговой ошибке — поднять исключение
        (PriceService поймает его и запишет в SearchResult.errors).
        """
        ...
