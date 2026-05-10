"""HTTP-клиент для boardgames-catalog REST API.

Симметричен ParsersClient: тонкая обёртка над httpx.AsyncClient. Создаётся
синглтоном в deps.py при старте, закрывается на shutdown.

Каталог отдаёт игру с массивом aliases в детальной карточке и offers, но в
этом клиенте мы покрываем только то, что нужно UI ручного матчинга:
- list/get games (поиск через pg_trgm fuzzy)
- очередь unmatched-оффер'ов
- link / reject из очереди
"""
from __future__ import annotations

from typing import Any

import httpx


class CatalogServiceError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail or f"catalog HTTP {status_code}")


class CatalogClient:
    def __init__(
        self, base_url: str, api_key: str | None = None, timeout: float = 30.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=headers
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def list_games(
        self,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
        *,
        no_bgg: bool = False,
    ) -> dict[str, Any]:
        """GET /games — листинг с pg_trgm fuzzy-search по q.

        no_bgg=True → только игры без bgg_id (для UI «найти соответствие в BGG»).
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q:
            params["q"] = q
        if no_bgg:
            params["no_bgg"] = "true"
        resp = await self._client.get("/games", params=params)
        return _ok_or_raise(resp)

    async def get_game(self, game_id: int) -> dict[str, Any]:
        resp = await self._client.get(f"/games/{game_id}")
        return _ok_or_raise(resp)

    async def list_game_offers(self, game_id: int) -> dict[str, Any]:
        """GET /games/{id}/offers — для drawer-таба «Offers»."""
        resp = await self._client.get(f"/games/{game_id}/offers")
        return _ok_or_raise(resp)

    async def list_game_children(self, game_id: int) -> dict[str, Any]:
        """GET /games/{id}/children — допы/промо/аксессуары базы."""
        resp = await self._client.get(f"/games/{game_id}/children")
        return _ok_or_raise(resp)

    async def reassess_offer(self, offer_id: int) -> dict[str, Any]:
        """POST /matching/{id}/reassess → пересчитать score для offer."""
        resp = await self._client.post(f"/matching/{offer_id}/reassess")
        return _ok_or_raise(resp)

    async def reassess_all(
        self, store: str | None = None, max_score: float | None = None,
    ) -> dict[str, Any]:
        """POST /matching/reassess-all → batch-пересчёт unmatched."""
        params: dict[str, Any] = {}
        if store:
            params["store"] = store
        if max_score is not None:
            params["max_score"] = max_score
        resp = await self._client.post("/matching/reassess-all", params=params)
        return _ok_or_raise(resp)

    async def matching_stats(self) -> dict[str, Any]:
        """GET /matching/stats → breakdown unmatched по магазинам и score-buckets."""
        resp = await self._client.get("/matching/stats")
        return _ok_or_raise(resp)

    async def match_candidates(
        self, title: str, limit: int = 10,
    ) -> dict[str, Any]:
        """GET /matching/candidates → топ-N с score (для UI ручного link)."""
        resp = await self._client.get(
            "/matching/candidates", params={"title": title, "limit": limit},
        )
        return _ok_or_raise(resp)

    async def matching_queue(
        self,
        store: str | None = None,
        was_linked: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if store:
            params["store"] = store
        if was_linked is not None:
            params["was_linked"] = str(was_linked).lower()
        resp = await self._client.get("/matching/queue", params=params)
        return _ok_or_raise(resp)

    async def link_offer(self, offer_id: int, game_id: int) -> dict[str, Any]:
        resp = await self._client.post(
            f"/matching/{offer_id}/link", json={"game_id": game_id}
        )
        return _ok_or_raise(resp)

    async def unlink_offer(self, offer_id: int) -> dict[str, Any]:
        """POST /matching/{id}/unlink — отвязать оффер, вернуть в очередь."""
        resp = await self._client.post(f"/matching/{offer_id}/unlink")
        return _ok_or_raise(resp)

    async def reject_offer(self, offer_id: int) -> dict[str, Any]:
        resp = await self._client.post(f"/matching/{offer_id}/reject")
        return _ok_or_raise(resp)

    # ── Game CRUD ───────────────────────────────────────────────────────

    async def merge_games(self, source_id: int, target_id: int) -> dict[str, Any]:
        """POST /games/merge {source_id, target_id} → объединение."""
        resp = await self._client.post(
            "/games/merge", json={"source_id": source_id, "target_id": target_id}
        )
        return _ok_or_raise(resp)

    async def create_game(self, payload: dict) -> dict[str, Any]:
        """POST /games → создать каноническую игру вручную."""
        resp = await self._client.post("/games", json=payload)
        return _ok_or_raise(resp)

    async def patch_game(self, game_id: int, payload: dict) -> dict[str, Any]:
        """PATCH /games/{id} → частичное обновление."""
        resp = await self._client.patch(f"/games/{game_id}", json=payload)
        return _ok_or_raise(resp)

    # ── Imports (BGG / Tesera) ──────────────────────────────────────────

    async def import_bgg(self, payload: dict) -> dict[str, Any]:
        """POST /import/bgg → запустить async-импорт. Возвращает ImportJob."""
        resp = await self._client.post("/import/bgg", json=payload)
        return _ok_or_raise(resp)

    async def bgg_search(
        self, query: str, *, exact: bool = False, limit: int = 20,
    ) -> dict[str, Any]:
        """POST /parsers/bgg/search → поиск игр в BGG XML API.

        Возвращает {query, exact, count, items: [{bgg_id, title, year}]}.
        Используется UI «Каталог → BGG» для интерактивного выбора игр перед
        запуском enrich'а.
        """
        resp = await self._client.post(
            "/parsers/bgg/search",
            json={"query": query, "exact": exact, "limit": limit},
        )
        return _ok_or_raise(resp)

    async def import_bgg_batch(self, payload: dict) -> dict[str, Any]:
        """POST /import/bgg/batch → массовое XML-обогащение топ-N или всех ranked.

        Возвращает ImportJob — затем polling через get_job() для отображения
        progress.{phase, current, total, current_title} и log_lines в UI.
        """
        resp = await self._client.post("/import/bgg/batch", json=payload)
        return _ok_or_raise(resp)

    async def import_bgg_ranks(
        self,
        csv_content: bytes,
        filename: str,
        *,
        top_n: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """POST /import/bgg/ranks (multipart) → seed из BGG ranks CSV.

        Форвардит multipart/form-data к catalog: поле csv_file + top_n + dry_run.
        Возвращает ImportJob — polling через get_import_job().
        """
        data: dict[str, str] = {"dry_run": str(dry_run).lower()}
        if top_n is not None:
            data["top_n"] = str(top_n)
        resp = await self._client.post(
            "/import/bgg/ranks",
            data=data,
            files={"csv_file": (filename, csv_content, "text/csv")},
            timeout=60.0,  # загрузка большого CSV может занять несколько секунд
        )
        return _ok_or_raise(resp)

    async def import_bgg_geeklist(self, payload: dict) -> dict[str, Any]:
        """POST /import/bgg/geeklist → snapshot кураторского BGG GeekList'а.

        payload: {geeklist_id, auto_import?}. Возвращает ImportJob.
        """
        resp = await self._client.post("/import/bgg/geeklist", json=payload)
        return _ok_or_raise(resp)

    async def import_bgg_mini_batch(self, payload: dict) -> dict[str, Any]:
        """POST /import/bgg/mini-batch → ежедневный «catch-up» enrich хвоста."""
        resp = await self._client.post("/import/bgg/mini-batch", json=payload)
        return _ok_or_raise(resp)

    async def list_import_jobs(
        self,
        *,
        type: str | None = None,
        status: str | None = None,
        trigger: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """GET /import/jobs → история запусков с фильтрами для UI BGG Sync."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if type is not None:
            params["type"] = type
        if status is not None:
            params["status"] = status
        if trigger is not None:
            params["trigger"] = trigger
        resp = await self._client.get("/import/jobs", params=params)
        return _ok_or_raise(resp)

    # ── Scheduler (BGG Sync UI) ────────────────────────────────────────────

    async def list_scheduler_jobs(self) -> list[dict[str, Any]]:
        """GET /scheduler/jobs → конфиги + runtime info (next_run, last_run)."""
        resp = await self._client.get("/scheduler/jobs")
        return _ok_or_raise(resp)

    async def reschedule_job(
        self, job_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH /scheduler/jobs/{id} → cron/enabled/params + hot-reload."""
        resp = await self._client.patch(f"/scheduler/jobs/{job_id}", json=payload)
        return _ok_or_raise(resp)

    async def trigger_scheduler_job(self, job_id: str) -> dict[str, Any]:
        """POST /scheduler/jobs/{id}/trigger → manual trigger (создаёт ImportJob)."""
        resp = await self._client.post(f"/scheduler/jobs/{job_id}/trigger")
        return _ok_or_raise(resp)

    # ── BGG read API (snapshots для UI Hotness/GeekList) ────────────────────

    async def bgg_hotness_dates(self, *, limit: int = 30) -> list[str]:
        """GET /bgg/hotness/dates → доступные snapshot_date (ISO YYYY-MM-DD)."""
        resp = await self._client.get(
            "/bgg/hotness/dates", params={"limit": limit}
        )
        return _ok_or_raise(resp)

    async def bgg_hotness_snapshot(
        self, snapshot_date: str | None = None
    ) -> dict[str, Any]:
        """GET /bgg/hotness?date= → 50 позиций hotness на дату (или последнюю)."""
        params: dict[str, Any] = {}
        if snapshot_date is not None:
            params["date"] = snapshot_date
        resp = await self._client.get("/bgg/hotness", params=params)
        return _ok_or_raise(resp)

    async def bgg_geeklists(self) -> list[dict[str, Any]]:
        """GET /bgg/geeklists → список импортированных GeekList'ов."""
        resp = await self._client.get("/bgg/geeklists")
        return _ok_or_raise(resp)

    async def bgg_geeklist_snapshot(
        self, geeklist_id: int, *, snapshot_date: str | None = None
    ) -> dict[str, Any]:
        """GET /bgg/geeklists/{id}?date= → snapshot одного GeekList'а."""
        params: dict[str, Any] = {}
        if snapshot_date is not None:
            params["date"] = snapshot_date
        resp = await self._client.get(
            f"/bgg/geeklists/{geeklist_id}", params=params
        )
        return _ok_or_raise(resp)

    async def import_tesera(self, payload: dict) -> dict[str, Any]:
        """POST /import/tesera → запустить async-импорт. Возвращает ImportJob."""
        resp = await self._client.post("/import/tesera", json=payload)
        return _ok_or_raise(resp)

    async def import_dicefest(self, payload: dict) -> dict[str, Any]:
        """POST /import/dicefest → парсер dicefest.ru → пишет в staging."""
        resp = await self._client.post("/import/dicefest", json=payload)
        return _ok_or_raise(resp)

    async def import_dicefest_reparse(self) -> dict[str, Any]:
        """POST /import/dicefest/reparse → re-parse уже скачанных карточек.

        Без сети: используется сохранённый raw_html из staging. Полезно после
        изменения парсера (новые поля / правка селекторов).
        """
        resp = await self._client.post("/import/dicefest/reparse")
        return _ok_or_raise(resp)

    # ── Promotion (PR-2/PR-3) ───────────────────────────────────────────

    async def promotion_queue(
        self, provider: str, *, status: str = "new",
        limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        params = {"status": status, "limit": limit, "offset": offset}
        resp = await self._client.get(
            f"/promotion/{provider}/queue", params=params,
        )
        return _ok_or_raise(resp)

    async def promotion_get_raw(self, provider: str, raw_id: int) -> dict[str, Any]:
        resp = await self._client.get(f"/promotion/{provider}/{raw_id}")
        return _ok_or_raise(resp)

    async def promotion_candidates(
        self, provider: str, raw_id: int, *,
        threshold: float = 0.5, limit: int = 5,
    ) -> dict[str, Any]:
        params = {"threshold": threshold, "limit": limit}
        resp = await self._client.get(
            f"/promotion/{provider}/{raw_id}/candidates", params=params,
        )
        return _ok_or_raise(resp)

    async def promotion_apply(
        self, provider: str, raw_id: int, payload: dict,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/promotion/{provider}/{raw_id}/apply", json=payload,
        )
        return _ok_or_raise(resp)

    async def promotion_revert(self, log_id: int, payload: dict | None = None) -> dict[str, Any]:
        resp = await self._client.post(
            f"/promotion/log/{log_id}/revert", json=payload or {},
        )
        return _ok_or_raise(resp)

    async def promotion_log(
        self, *, provider: str | None = None,
        game_id: int | None = None,
        limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if provider:
            params["provider"] = provider
        if game_id is not None:
            params["game_id"] = game_id
        resp = await self._client.get("/promotion/log", params=params)
        return _ok_or_raise(resp)

    async def promotion_log_details(self, log_id: int) -> dict[str, Any]:
        """GET /promotion/log/{id}/details — запись + связанные raw/game/alias."""
        resp = await self._client.get(f"/promotion/log/{log_id}/details")
        return _ok_or_raise(resp)

    async def promotion_batch_link(
        self, provider: str, payload: dict,
    ) -> dict[str, Any]:
        """POST /promotion/{provider}/batch-link — auto-link высокий-score raw."""
        resp = await self._client.post(
            f"/promotion/{provider}/batch-link", json=payload,
        )
        return _ok_or_raise(resp)

    async def get_import_job(self, job_id: int) -> dict[str, Any]:
        """GET /import/jobs/{id} → polling статуса (pending/running/done/failed)."""
        resp = await self._client.get(f"/import/jobs/{job_id}")
        return _ok_or_raise(resp)

    # ── Aliases CRUD ────────────────────────────────────────────────────

    async def add_alias(self, game_id: int, payload: dict) -> dict[str, Any]:
        """POST /games/{id}/aliases — добавить альтернативное название."""
        resp = await self._client.post(f"/games/{game_id}/aliases", json=payload)
        return _ok_or_raise(resp)

    async def patch_alias(
        self, game_id: int, alias_id: int, payload: dict,
    ) -> dict[str, Any]:
        """PATCH /games/{id}/aliases/{alias_id} — редактирование."""
        resp = await self._client.patch(
            f"/games/{game_id}/aliases/{alias_id}", json=payload,
        )
        return _ok_or_raise(resp)

    async def delete_alias(self, game_id: int, alias_id: int) -> None:
        """DELETE /games/{id}/aliases/{alias_id} → 204."""
        resp = await self._client.delete(f"/games/{game_id}/aliases/{alias_id}")
        if resp.is_error:
            try:
                detail = resp.json().get("detail", "")
            except ValueError:
                detail = resp.text[:500]
            raise CatalogServiceError(resp.status_code, detail or f"HTTP {resp.status_code}")

    # ── Sources: detection runs ────────────────────────────────────────────

    async def start_source_run(
        self, provider: str, payload: dict,
    ) -> dict[str, Any]:
        """POST /sources/{provider}/runs — запуск сухого прогона.

        Возвращает run сразу с status='running'; реальная обработка идёт
        фоном, статус меняется на 'ready' / 'failed' через polling.
        """
        resp = await self._client.post(
            f"/sources/{provider}/runs", json=payload,
        )
        return _ok_or_raise(resp)

    async def list_source_runs(
        self, provider: str, *, limit: int = 20, offset: int = 0,
    ) -> dict[str, Any]:
        resp = await self._client.get(
            f"/sources/{provider}/runs",
            params={"limit": limit, "offset": offset},
        )
        return _ok_or_raise(resp)

    async def get_source_run(self, provider: str, run_id: int) -> dict[str, Any]:
        resp = await self._client.get(f"/sources/{provider}/runs/{run_id}")
        return _ok_or_raise(resp)

    async def list_source_run_items(
        self,
        provider: str,
        run_id: int,
        *,
        change_type: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if change_type:
            params["change_type"] = change_type
        if search:
            params["search"] = search
        resp = await self._client.get(
            f"/sources/{provider}/runs/{run_id}/items", params=params,
        )
        return _ok_or_raise(resp)

    async def apply_source_run(
        self, provider: str, run_id: int, payload: dict,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/sources/{provider}/runs/{run_id}/apply", json=payload,
        )
        return _ok_or_raise(resp)

    async def discard_source_run(
        self, provider: str, run_id: int,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/sources/{provider}/runs/{run_id}/discard",
        )
        return _ok_or_raise(resp)

    # ── Sources: match profiles ────────────────────────────────────────────

    async def list_match_profiles(self, provider: str) -> list[dict[str, Any]]:
        resp = await self._client.get(f"/sources/{provider}/match-profiles")
        if resp.is_error:
            try:
                detail = resp.json().get("detail", "")
            except ValueError:
                detail = resp.text[:500]
            raise CatalogServiceError(
                resp.status_code, detail or f"HTTP {resp.status_code}",
            )
        return resp.json()

    async def upsert_match_profile(
        self, provider: str, payload: dict,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/sources/{provider}/match-profiles", json=payload,
        )
        return _ok_or_raise(resp)

    async def delete_match_profile(self, provider: str, profile_id: int) -> None:
        resp = await self._client.delete(
            f"/sources/{provider}/match-profiles/{profile_id}",
        )
        if resp.is_error:
            try:
                detail = resp.json().get("detail", "")
            except ValueError:
                detail = resp.text[:500]
            raise CatalogServiceError(
                resp.status_code, detail or f"HTTP {resp.status_code}",
            )

    # ── /promotion/.../candidates с MatchParams ────────────────────────────

    async def promotion_candidates_with_params(
        self,
        provider: str,
        raw_id: int,
        *,
        threshold: float = 0.5,
        limit: int = 5,
        prefer_external_id: bool = False,
        weight_ru: float = 1.0,
        weight_en: float = 1.0,
        weight_alias: float = 1.0,
    ) -> dict[str, Any]:
        """GET /promotion/{provider}/{raw_id}/candidates с расширенными
        параметрами матчинга. UI MatchParamsForm использует эту обёртку,
        старая `promotion_candidates` остаётся как обратная совместимость.
        """
        resp = await self._client.get(
            f"/promotion/{provider}/{raw_id}/candidates",
            params={
                "threshold": threshold,
                "limit": limit,
                "prefer_external_id": str(prefer_external_id).lower(),
                "weight_ru": weight_ru,
                "weight_en": weight_en,
                "weight_alias": weight_alias,
            },
        )
        return _ok_or_raise(resp)


def _ok_or_raise(resp: httpx.Response) -> dict[str, Any]:
    if resp.is_error:
        try:
            detail = resp.json().get("detail", "")
        except ValueError:
            detail = resp.text[:500]
        raise CatalogServiceError(resp.status_code, detail or f"HTTP {resp.status_code}")
    return resp.json()
