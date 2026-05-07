"""Промоушен сырых данных из staging-таблиц в canonical БД.

Двухстадийная схема обогащения catalog'а:

  Стадия 1 (импорт)    : парсер пишет в `<provider>_raw_games` (staging).
  Стадия 2 (промоушен) : оператор через UI выбирает кандидата canonical Game,
                         action=link → добавляется alias + satellite-запись;
                         action=create → создаётся новая Game.
                         Каждое действие → строка в `import_promotion_log`
                         для отката.

Сейчас в проекте один источник — dicefest (см. promotion.dicefest). Когда
появится BGA/dicebreaker, добавим promotion.bga и т.д. — каждый со своей
satellite-таблицей и тонкостями matching'а, но общим API контрактом
PromotionCandidate / promote() / revert().
"""
