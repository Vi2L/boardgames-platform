# DEPRECATED

Содержимое этой папки больше не используется. Оставлено как safety-net и
для возможного rollback'а в течение 2 недель после удаления (2026-05-14).

## chrome-extension/

Chrome-расширение, которое читало куки `.avito.ru` (включая httpOnly
`_avisc`) через `chrome.cookies.getAll` и POST-ило их в
`http://localhost:8001/api/avito/cookies`. Нужно было, потому что
Playwright из Docker не получал `_avisc` (Qrator блокировал DC-сессии).

Заменено на L0-стратегию: `services/parsers/parsers/stores/avito_qrator.py`
получает `_avisc` напрямую через curl-cffi из контейнера. Внешний браузер
больше не нужен.

См. `services/parsers/parsers/stores/avito.py` и
`docs/devlog.md` (запись 2026-05-14 «[AVT-CONT] Avito container-only
через L0 curl-cffi»).

## Как откатиться (если L0 однажды перестанет работать)

1. `git mv services/parsers/DEPRECATED/chrome-extension services/parsers/chrome-extension`
2. Восстановить `POST /api/avito/cookies` в `services/parsers/parsers/api.py`
   из git-истории (commit `0d04111` — оригинальная реализация).
3. Восстановить старый `services/parsers/parsers/stores/avito.py` оттуда же.
4. Восстановить env-секцию `AVITO_COOKIES` в `.env.example` и compose.
5. Поднять browser-service: `docker compose --profile full --profile browser up -d`.

## Когда удалять окончательно

После 2 недель стабильной работы L0 в проде (контрольный показатель —
`parser_log` по `avito` с `success=1` ratio ≥ 95% за 14 дней).
Целевая дата удаления: **2026-05-28**.
