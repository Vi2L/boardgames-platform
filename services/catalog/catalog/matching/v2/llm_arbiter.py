"""Tier 3: qwen2.5:7b-instruct арбитр между близкими кандидатами от T2.

LLM получает offer title + 2-3 кандидата, возвращает structured JSON:
  {"game_id": <int|null>, "kind": "base|expansion|accessory", "confidence": 0..1, "reason": "..."}

Защиты:
  1. format='json' в Ollama API → принудительный JSON output.
  2. game_id whitelist — LLM не может вернуть несуществующий ID.
  3. Retry 1 раз при невалидном JSON (regex extraction из markdown).
  4. confidence < threshold → возврат в T4 (manual).
"""
from __future__ import annotations

import json
import logging

import httpx

from catalog.config import get_settings
from catalog.matching.v2.domain import MatchAction, MatchContext, MatchResult
from catalog.matching.v2.embedder import OllamaError, OllamaUnavailable

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "Ты — эксперт по настольным играм. Тебе дают название товара из российского "
    "интернет-магазина и список канонических игр-кандидатов из базы. Определи, "
    "какой кандидат соответствует товару, или укажи что совпадения нет.\n"
    "Также классифицируй тип товара: 'base' (базовая игра), 'expansion' "
    "(дополнение к базе), 'accessory' (аксессуары: органайзер, чехлы, токены).\n"
    "\n"
    "ВАЖНО — отказ для не-настолок. Если товар очевидно НЕ настольная игра "
    "и не её компонент (книга, художественный роман, видеоигра, одежда, "
    "посуда, канцелярия, постер, коллекционная фигурка БЕЗ игровой механики, "
    "детская мягкая игрушка, велосипед, бытовая техника, продукты) — верни "
    '{\"game_id\": null, \"kind\": null, \"confidence\": 0.99, '
    '\"reason\": \"not_a_boardgame: <короткое объяснение>\"}. '
    "Высокая confidence сигнализирует движку, что это финальный reject, "
    "а не «не уверен» — оффер сразу попадёт в rejected, а не в manual.\n"
    "\n"
    "Отвечай ТОЛЬКО валидным JSON, без markdown, без пояснений вне JSON."
)


def _format_candidates(candidates: list[dict]) -> str:
    """Форматирует список кандидатов для промпта. Берём топ-3 по score."""
    lines: list[str] = []
    for i, c in enumerate(candidates[:3], 1):
        ru = f" / {c['title_ru']}" if c.get("title_ru") else ""
        year = f" ({c['year']})" if c.get("year") else ""
        kind_str = c.get("kind") or "?"
        score = c.get("score", 0.0)
        lines.append(
            f"{i}. [id={c['game_id']}] {c['title']}{ru}{year} [{kind_str}] — score={score:.2f}"
        )
    return "\n".join(lines)


def _extract_first_json_object(raw: str) -> dict | None:
    """Находит первый валидный JSON-объект в строке (даже с markdown-обвязкой).

    Идём по позициям `{` и пробуем `JSONDecoder.raw_decode` от каждой —
    это автоматически корректно обрабатывает вложенные объекты и пробелы.
    Старая реализация на regex `\\{.*?\\}` ломалась на вложенных скобках
    (non-greedy останавливался на первой `}` внутри nested object).
    """
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        idx = raw.find("{", pos)
        if idx == -1:
            return None
        try:
            obj, _end = decoder.raw_decode(raw, idx)
        except json.JSONDecodeError:
            pos = idx + 1
            continue
        if isinstance(obj, dict):
            return obj
        pos = idx + 1


def _parse_response(raw: str, valid_ids: set[int]) -> dict | None:
    """Парсит JSON, валидирует структуру.

    1. Прямой json.loads (быстрый путь — при format='json' Ollama обычно
       возвращает чистый JSON).
    2. Fallback: ищем первый валидный JSON-объект через JSONDecoder.raw_decode —
       работает с markdown-обвязкой и вложенными объектами.
    3. Whitelist game_id — отсекает галлюцинации.

    Возвращает dict с обязательными ключами или None.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = _extract_first_json_object(raw)
        if data is None:
            return None

    # Базовая валидация структуры
    if not isinstance(data, dict):
        return None
    gid = data.get("game_id")
    if gid is not None:
        try:
            gid = int(gid)
        except (TypeError, ValueError):
            gid = None
        # Whitelist: LLM не может вернуть несуществующий id
        if gid is not None and gid not in valid_ids:
            logger.warning("LLM hallucinated game_id=%s, not in candidates", gid)
            gid = None
    data["game_id"] = gid

    kind = data.get("kind")
    if kind not in ("base", "expansion", "accessory"):
        data["kind"] = None

    try:
        data["confidence"] = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        data["confidence"] = 0.0

    return data


async def tier_3_llm(
    ctx: MatchContext,
    candidates: list[dict],
    *,
    confidence_threshold: float = 0.75,
) -> MatchResult:
    """T3: LLM-арбитр над top-3 кандидатами.

    Возвращает:
      - matched MatchResult (tier=3, action=AUTO_T3) если confidence >= threshold.
      - unmatched (tier=3, reason='llm_low_confidence') если confidence ниже.
      - unmatched (tier=3, reason='llm_parse_failed') при невалидном JSON.

    OllamaError → пропагируем (worker реtries).
    """
    if not candidates:
        return MatchResult(
            game_id=None, tier=3, action=None, reason="llm_no_candidates",
        )

    settings = get_settings()
    valid_ids = {int(c["game_id"]) for c in candidates}

    user_prompt = (
        f'Товар из магазина: "{ctx.title_raw}"\n'
        f"Магазин: {ctx.store_slug or '?'}\n\n"
        f"Кандидаты (по убыванию релевантности):\n{_format_candidates(candidates)}\n\n"
        "Ответь JSON:\n"
        '{"game_id": <int или null если нет совпадения>, '
        '"kind": "<base|expansion|accessory>", '
        '"confidence": <0.0..1.0>, '
        '"reason": "<1-2 предложения>"}'
    )

    payload = {
        "model": settings.ml_llm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",  # принудительный JSON output
        "options": {"temperature": 0.0},
    }

    import time as _time
    started = _time.monotonic()
    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url, timeout=60.0,
        ) as client:
            resp = await client.post("/api/chat", json=payload)
            if resp.status_code == 429:
                raise OllamaError("rate limited (429)")
            if resp.status_code >= 500:
                raise OllamaUnavailable(f"http_{resp.status_code}")
            if resp.status_code != 200:
                raise OllamaError(f"http_{resp.status_code}: {resp.text[:200]}")
            content = resp.json().get("message", {}).get("content", "")
            # Успешный реальный вызов после half-open probe закрывает цепь;
            # latency идёт в rolling-buffer для UI p50/p95/rps.
            duration_ms = (_time.monotonic() - started) * 1000.0
            from catalog.matching.v2.health import OllamaHealth
            OllamaHealth.get_instance().record_success(settings.ml_llm_model, duration_ms)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        from catalog.matching.v2.health import OllamaHealth
        OllamaHealth.get_instance().record_error(settings.ml_llm_model, f"connect: {e}")
        raise OllamaUnavailable(f"connect: {e}") from e

    parsed = _parse_response(content, valid_ids)
    if parsed is None:
        logger.warning("LLM returned invalid JSON: %s", content[:500])
        return MatchResult(
            game_id=None, tier=3, action=None,
            reason="llm_parse_failed", candidates=candidates,
        )

    if parsed["game_id"] is None:
        llm_reason = str(parsed.get("reason", ""))
        # Финальный отказ от LLM: товар не является настольной игрой.
        # System-prompt просит LLM начинать `reason` с `not_a_boardgame:`
        # и confidence ≥ некоего порога — это сигнал «оффер сразу в
        # rejected, не дёргать оператора в manual queue».
        is_explicit_reject = (
            llm_reason.lower().startswith("not_a_boardgame")
            and parsed["confidence"] >= confidence_threshold
        )
        if is_explicit_reject:
            return MatchResult(
                game_id=None, tier=3, action=MatchAction.REJECT,
                reason=f"llm_reject: {llm_reason}"[:200],
                candidates=candidates,
                predicted_kind=None,
            )
        return MatchResult(
            game_id=None, tier=3, action=None,
            reason=f"llm_no_match: {llm_reason}"[:200],
            candidates=candidates,
            predicted_kind=parsed.get("kind"),
        )

    if parsed["confidence"] < confidence_threshold:
        return MatchResult(
            game_id=None, tier=3, action=None,
            reason=f"llm_low_confidence ({parsed['confidence']:.2f})",
            candidates=candidates,
            predicted_kind=parsed.get("kind"),
        )

    return MatchResult(
        game_id=parsed["game_id"],
        score=parsed["confidence"],
        tier=3,
        action=MatchAction.AUTO_T3,
        reason=f"llm: {parsed.get('reason', '')}"[:200],
        candidates=candidates,
        predicted_kind=parsed.get("kind"),
    )
