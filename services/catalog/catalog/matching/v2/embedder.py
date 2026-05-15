"""Ollama HTTP-клиент для embedding (bge-m3).

API:
  - embed_one(text) → list[float]            (один embed)
  - embed_batch(texts) → list[list[float]]   (batch для warmup)
  - build_text(game) → str                   (text_used для embedding)

Реализация — тонкая обёртка над POST /api/embed (новый Ollama API; старый
/api/embeddings deprecated). При 429/timeout/connect_error пробрасываем
OllamaError, чтобы caller (worker) откатил batch в pending.

build_text формирует embedding-input из:
    "title_ru || ' ' || title || ' ' || join(top_aliases_ru, ' ')"
Bge-m3 multilingual → русский, английский и транслит лежат в одном
семантическом пространстве. Конкатенация даёт кросс-языковую близость.
"""
from __future__ import annotations

import logging

import httpx

from catalog.config import get_settings

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Базовый класс ошибок взаимодействия с Ollama."""


class OllamaUnavailable(OllamaError):
    """Connection refused / timeout / 5xx — повторяем потом."""


class OllamaRateLimited(OllamaError):
    """HTTP 429 — backoff."""


async def embed_one(text: str, *, client: httpx.AsyncClient | None = None) -> list[float]:
    """Один embedding. Внешний caller может передать свой client (для batch).

    text — пустая строка не разрешена; вернёт OllamaError.
    """
    if not text or not text.strip():
        raise OllamaError("embed_one: empty text")

    own_client = client is None
    if client is None:
        settings = get_settings()
        client = httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=30.0)

    try:
        settings = get_settings()
        # Новый API Ollama: /api/embed (вместо /api/embeddings)
        # input может быть строкой или массивом — мы используем массив для batch,
        # одну строку оборачиваем для единообразия.
        resp = await client.post(
            "/api/embed",
            json={"model": settings.ml_embed_model, "input": text},
        )
        if resp.status_code == 429:
            raise OllamaRateLimited("rate limited")
        if resp.status_code >= 500:
            raise OllamaUnavailable(f"http_{resp.status_code}")
        if resp.status_code != 200:
            raise OllamaError(f"http_{resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        embeddings = data.get("embeddings") or []
        if not embeddings or not embeddings[0]:
            raise OllamaError("empty embedding response")
        # Успешный реальный вызов после half-open probe закрывает Circuit Breaker.
        # Импорт здесь (не top-level) чтобы embedder не тащил health-singleton на
        # стадии import — health.py инициализируется в lifespan'е раньше.
        from catalog.matching.v2.health import OllamaHealth
        OllamaHealth.get_instance().record_success(settings.ml_embed_model)
        return list(embeddings[0])
    except httpx.ConnectError as e:
        raise OllamaUnavailable(f"connect: {e}") from e
    except httpx.TimeoutException as e:
        raise OllamaUnavailable(f"timeout: {e}") from e
    finally:
        if own_client:
            await client.aclose()


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Batch-embed N строк одним HTTP-вызовом.

    Ollama /api/embed принимает массив input → массив embeddings того же размера.
    Это ~10x быстрее, чем N последовательных embed_one.

    Если batch слишком большой (Ollama лимит ~256 на m-series) — caller сам бьёт на чанки.
    """
    if not texts:
        return []
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url, timeout=120.0,  # batch может быть медленнее
    ) as client:
        try:
            resp = await client.post(
                "/api/embed",
                json={"model": settings.ml_embed_model, "input": texts},
            )
            if resp.status_code == 429:
                raise OllamaRateLimited("rate limited")
            if resp.status_code >= 500:
                raise OllamaUnavailable(f"http_{resp.status_code}")
            if resp.status_code != 200:
                raise OllamaError(f"http_{resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            vectors = data.get("embeddings") or []
            if len(vectors) != len(texts):
                raise OllamaError(
                    f"embed_batch: expected {len(texts)} vectors, got {len(vectors)}"
                )
            return [list(v) for v in vectors]
        except httpx.ConnectError as e:
            raise OllamaUnavailable(f"connect: {e}") from e
        except httpx.TimeoutException as e:
            raise OllamaUnavailable(f"timeout: {e}") from e


def build_text(
    *,
    title: str,
    title_ru: str | None = None,
    aliases: list[str] | None = None,
    max_aliases: int = 5,
) -> str:
    """Строит embedding-input из title + title_ru + первых N aliases.

    Порядок и приоритет: ru-локализация в начале (russian-first для нашего
    основного use case — РФ-магазины). Дубликаты исключаем (если title_ru ==
    title или входит в aliases).

    Слова разделяем пробелом — bge-m3 sentence-transformer, токенизация
    учитывает word boundaries.
    """
    parts: list[str] = []
    seen: set[str] = set()

    def _add(s: str | None) -> None:
        if not s:
            return
        s_clean = s.strip()
        if not s_clean:
            return
        key = s_clean.lower()
        if key in seen:
            return
        seen.add(key)
        parts.append(s_clean)

    _add(title_ru)
    _add(title)
    for alias in (aliases or [])[:max_aliases]:
        _add(alias)

    return " ".join(parts)
