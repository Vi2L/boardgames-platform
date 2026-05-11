"""Smoke-test async-pipeline: ingest нескольких офферов → ждём, что воркер
обработает их через T2 (bge-m3) или T3 (qwen2.5).

Запуск:
    uv run --package boardgames-catalog python -m catalog.scripts.smoke_async_pipeline

Pre-conditions:
  - Миграция 0011 применена.
  - Ollama запущен с моделями bge-m3 + qwen2.5:7b-instruct.
  - Catalog запущен на http://localhost:8002.
  - В БД есть несколько game-записей с title_ru (как минимум "Каркассон" id=231).

Идея:
  1. Ingest 5 разных вариантов написания «Каркассона» (опечатки, регистры,
     транслит). T0+T1 матчат только точные/почти-точные совпадения.
  2. Остальные должны попасть в match_queue со status='pending'.
  3. Если эмбеддинги уже прогреты для целевой игры — воркер сматчит их
     через T2 (или T3 для близких) и сместит в match_status='auto'.
  4. Опрашиваем /matching/log пока все офферы не получат match_status='auto'
     или 'unmatched' с tier>=2 (значит воркер их видел).

Полезно как ручная проверка после deploy + warmup.
"""
from __future__ import annotations

import asyncio
import time

import httpx

CATALOG_URL = "http://localhost:8002"

# Варианты написания «Каркассона». Первый — точное совпадение,
# остальные требуют embedding или LLM.
CARC_VARIANTS = [
    "Каркассон",                      # T1 точное совпадение (title_ru)
    "Каркасон",                       # опечатка, T2/T3 должен поймать
    "Carcassonne",                    # английская версия, T1 на title
    "КАРКАССОН",                      # верхний регистр — T0/T1 после нормализации
    "Каркассон базовая игра",         # с дополнительным текстом, T2 семантически
]


async def main() -> int:
    async with httpx.AsyncClient(base_url=CATALOG_URL, timeout=30.0) as client:
        # 1) Health-check
        r = await client.get("/health")
        if r.status_code != 200:
            print(f"catalog недоступен: {r.status_code}")
            return 1

        # 2) ML status
        r = await client.get("/matching/ml-status")
        ml = r.json()
        print("ML status:")
        print(f"  models: {ml['models']}")
        print(f"  queue: {ml.get('queue', {})}")
        if not any(ml["models"].values()):
            print("⚠ Ни одна модель не доступна. Async-pipeline работать не будет.")
            print("  Установи: ollama pull bge-m3 && ollama pull qwen2.5:7b-instruct")
            return 1

        # 3) Ingest всех вариантов
        print("\nIngest вариантов:")
        products = [
            {
                "external_id": f"smoke-async-{i}",
                "title": title,
                "url": f"http://smoke.test/{i}",
                "price": 100000,
            }
            for i, title in enumerate(CARC_VARIANTS)
        ]
        r = await client.post(
            "/ingest/offers",
            json={"store_slug": "smoke-async", "products": products},
        )
        if r.status_code != 200:
            print(f"ingest failed: {r.status_code} {r.text[:200]}")
            return 1
        result = r.json()
        print(f"  accepted: {result['accepted']}, "
              f"auto: {result['auto_matched']}, "
              f"unmatched: {result['unmatched']}")
        for item in result["items"]:
            tier_str = "T?" if item.get("match_score") is None else f"score={item['match_score']:.2f}"
            print(f"  {item['external_id']}: {item['match_status']} {tier_str}")

        offer_ids = [item["offer_id"] for item in result["items"]]

        # 4) Polling /matching/log до тех пор, пока все офферы не дойдут до tier>=2
        print("\nЖду воркер (max 90s)...")
        deadline = time.time() + 90
        while time.time() < deadline:
            await asyncio.sleep(5)
            r = await client.get("/matching/ml-status")
            ml = r.json()
            queue = ml.get("queue", {})
            pending = queue.get("pending", 0)
            print(f"  queue: pending={pending} processing={queue.get('processing', 0)} "
                  f"done={queue.get('done', 0)} skipped={queue.get('skipped', 0)} "
                  f"failed={queue.get('failed', 0)}")
            if pending == 0 and queue.get("processing", 0) == 0:
                break

        # 5) Финальный отчёт
        print("\nИтог по офферам:")
        for oid in offer_ids:
            r = await client.get(f"/matching/log?offer_id={oid}&limit=10")
            logs = r.json().get("items", [])
            if not logs:
                print(f"  offer {oid}: (no log entries)")
                continue
            last = logs[0]  # отсортирован DESC
            tier = last.get("tier")
            tier_label = (
                "T0 cache" if tier == 0 else
                "T1 trgm" if tier == 1 else
                "T2 vec" if tier == 2 else
                "T3 llm" if tier == 3 else
                f"tier={tier}"
            )
            print(f"  offer {oid}: action={last['action']} {tier_label} "
                  f"status={last['new_status']} score={last.get('score')} "
                  f"reason={last.get('reason')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
