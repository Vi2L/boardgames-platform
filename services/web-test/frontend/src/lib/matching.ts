/**
 * Matching v2 — admin-операции из новой панели /matching.
 *
 * Существующий `lib/catalog.ts` уже экспонирует:
 *   - fetchMlStatus  (GET /matching/ml-status)
 *   - fetchMatchLog  (GET /matching/log)
 *   - revertMatchLog / bulkRevertMatchLog / batchRevertMatchLog
 *   - startWarmupEmbeddings
 *
 * Этот модуль добавляет NEW endpoints для /matching admin panel:
 *   - runtime_flags  (kill-switch ml_enabled)
 *   - re-enqueue skipped с фильтрами
 *   - штучный матчинг через v2 (run-v2)
 *   - trigger воркера руками
 *   - расширенный match_log filter
 *
 * Все методы проксируются через web-test backend `/api/catalog/*` →
 * upstream catalog с X-API-Key. Frontend сам ключ не видит.
 */

const BASE = '/api/catalog'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

// ── Runtime flags (kill-switch) ────────────────────────────────────────────

export type RuntimeFlag = {
  key: string
  value_bool: boolean | null
  updated_at: string
  updated_by: string | null
}

export const fetchRuntimeFlag = (key: string) =>
  fetch(`${BASE}/admin/runtime-flags/${key}`).then(r => json<RuntimeFlag>(r))

export const setRuntimeFlag = (key: string, value: boolean) =>
  fetch(`${BASE}/admin/runtime-flags/${key}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ value }),
  }).then(r => json<RuntimeFlag>(r))

// ── Skipped queue + re-enqueue ─────────────────────────────────────────────

export type SkippedQueueItem = {
  id: number
  offer_id: number
  store_slug: string
  title_raw: string
  error_detail: string | null   // reason: llm_unavailable, no_candidates, ...
  result_score: number | null
  attempts: number
  created_at: string
  processed_at: string | null
}

export type SkippedQueuePage = {
  items: SkippedQueueItem[]
  total: number
  limit: number
  offset: number
  /** breakdown по reasons для UI фильтра — заполняется backend'ом из тех же
   *  фильтров что в page-query (бэкенд возвращает {reason → count}). */
  reasons: Record<string, number>
  /** breakdown по магазинам. */
  stores: Record<string, number>
}

export type SkippedQueueFilters = {
  store_slug?: string[]      // multi
  reason?: string[]          // multi (matches error_detail prefix)
  limit?: number
  offset?: number
}

export const fetchSkippedQueue = (filters: SkippedQueueFilters = {}) => {
  const sp = new URLSearchParams()
  for (const s of filters.store_slug ?? []) sp.append('store_slug', s)
  for (const r of filters.reason ?? []) sp.append('reason', r)
  sp.set('limit', String(filters.limit ?? 100))
  sp.set('offset', String(filters.offset ?? 0))
  return fetch(`${BASE}/matching/queue/skipped?${sp}`).then(r => json<SkippedQueuePage>(r))
}

export type ReEnqueueResult = {
  requested: number
  re_enqueued: number
}

/**
 * Re-enqueue выбранных skipped. Если offer_ids не передан — re-enqueue ВСЕХ
 * skipped (опасная операция, UI должен показывать confirm).
 */
export const reEnqueueSkipped = (params: {
  offer_ids?: number[]
  store_slug?: string[]
  reason?: string[]
}) =>
  fetch(`${BASE}/matching/queue/re-enqueue-skipped`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(params),
  }).then(r => json<ReEnqueueResult>(r))

// ── Single-offer v2 run ────────────────────────────────────────────────────

export type RunV2Response = {
  offer_id: number
  queued: boolean
  priority: number
  /** существующий match_queue.id если оффер уже в очереди */
  queue_id: number | null
}

export const runV2OnOffer = (offerId: number) =>
  fetch(`${BASE}/matching/${offerId}/run-v2`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
  }).then(r => json<RunV2Response>(r))

// ── Trigger match_worker tick ──────────────────────────────────────────────

export type WorkerTriggerResponse = {
  triggered: boolean
  message: string
}

export const triggerMatchWorker = () =>
  fetch(`${BASE}/scheduler/jobs/match_worker/trigger`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
  }).then(r => json<WorkerTriggerResponse>(r))

// ── Worker config (interval_sec) — реюзает PATCH scheduler ─────────────────

export type SchedulerJobInfo = {
  job_id: string
  cron_expr: string
  enabled: boolean
  params: Record<string, unknown>
  last_run_job_id: number | null
  last_run_status: string | null
  last_run_at: string | null
  next_run_at: string | null
  display_name: string | null
  description: string | null
}

export const fetchWorkerJob = (jobId = 'match_worker') =>
  fetch(`${BASE}/scheduler/jobs`).then(r =>
    json<SchedulerJobInfo[]>(r).then(rows => rows.find(j => j.job_id === jobId)),
  )

export const updateWorkerInterval = (intervalSec: number) =>
  fetch(`${BASE}/scheduler/jobs/match_worker`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ params: { interval_sec: intervalSec, batch_size: 32 } }),
  }).then(r => json<SchedulerJobInfo>(r))

// ── Offer lookup для штучного матчинга ────────────────────────────────────

export type OfferLookup = {
  id: number
  store_slug: string
  external_id: string
  title_raw: string
  url: string | null
  image_url: string | null
  last_price: number | null
  game_id: number | null
  match_status: string
  match_score: number | null
  match_tier: number | null
  match_reason: string | null
}

export const findOfferById = (offerId: number) =>
  fetch(`${BASE}/matching/offers/${offerId}`).then(r => json<OfferLookup>(r))

export const findOffersByTitle = (q: string, limit = 10) => {
  const sp = new URLSearchParams({ q, limit: String(limit) })
  return fetch(`${BASE}/matching/offers/search?${sp}`).then(r =>
    json<{ items: OfferLookup[] }>(r),
  )
}

// ── /matching/stats с расширенным queue breakdown ─────────────────────────

export type MatchingStatsExtended = {
  total_unmatched: number
  by_store: Array<{ store_slug: string; total: number; avg_score: number | null }>
  by_bucket: Record<string, number>
  thresholds: { auto: number; candidate: number }
  queue: {
    pending: number
    processing: number
    skipped: number
    failed: number
    done: number
  }
}

export const fetchMatchingStatsExtended = () =>
  fetch(`${BASE}/matching/stats`).then(r => json<MatchingStatsExtended>(r))
