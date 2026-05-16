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

// ── UX-improvements §A/§C/§D/§E (handoff v2) ───────────────────────────────

export type QueueDepthPoint = {
  ts: string
  depth: number
}

export type QueueDepthHistory = {
  points: QueueDepthPoint[]
  current: number
  peak: number
  drainage_rate_per_min: number
  range_hours: number
  bucket_minutes: number
}

export const fetchQueueDepthHistory = (params: { range_hours?: number; bucket_minutes?: number } = {}) => {
  const sp = new URLSearchParams()
  sp.set('range_hours', String(params.range_hours ?? 24))
  sp.set('bucket_minutes', String(params.bucket_minutes ?? 60))
  return fetch(`${BASE}/matching/queue/depth?${sp}`).then(r => json<QueueDepthHistory>(r))
}

export type QueueItemLookup = {
  id: number
  offer_id: number
  store_slug: string
  title_raw: string
  status: 'pending' | 'processing' | 'done' | 'failed' | 'skipped'
  priority: number
  attempts: number
  error_detail: string | null
  created_at: string
  claimed_at: string | null
  processed_at: string | null
  next_attempt_at: string | null
  result_game_id: number | null
  result_score: number | null
  result_tier: number | null
  position_in_pending: number | null
}

export const fetchQueueItem = (queueId: number) =>
  fetch(`${BASE}/matching/queue/${queueId}`).then(r => json<QueueItemLookup>(r))

export const cancelQueueItem = (queueId: number) =>
  fetch(`${BASE}/matching/queue/${queueId}`, { method: 'DELETE' })
    .then(r => json<{ queue_id: number; result: string }>(r))

export type ModelProbeResult = {
  model: string
  probed: boolean
  circuit_state: 'closed' | 'half_open' | 'open' | 'unknown'
  last_check_at: string | null
}

export const forceProbeModel = (modelName: string) =>
  fetch(`${BASE}/matching/ml-models/${encodeURIComponent(modelName)}/probe`, {
    method: 'POST',
  }).then(r => json<ModelProbeResult>(r))

// ── Auto-recovery rules CRUD ───────────────────────────────────────────────

export type AutoRecoveryRule = {
  id: number
  name: string
  condition: Record<string, unknown>
  action: Record<string, unknown>
  enabled: boolean
  last_triggered_at: string | null
  last_result: string | null
  created_at: string
  updated_at: string
  updated_by: string | null
}

export const fetchAutoRecoveryRules = () =>
  fetch(`${BASE}/admin/auto-recovery-rules`).then(r => json<AutoRecoveryRule[]>(r))

export const createAutoRecoveryRule = (payload: {
  name: string
  condition: Record<string, unknown>
  action: Record<string, unknown>
  enabled?: boolean
}) =>
  fetch(`${BASE}/admin/auto-recovery-rules`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<AutoRecoveryRule>(r))

export const updateAutoRecoveryRule = (
  ruleId: number,
  patch: Partial<{
    name: string
    condition: Record<string, unknown>
    action: Record<string, unknown>
    enabled: boolean
  }>,
) =>
  fetch(`${BASE}/admin/auto-recovery-rules/${ruleId}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch),
  }).then(r => json<AutoRecoveryRule>(r))

export const deleteAutoRecoveryRule = (ruleId: number) =>
  fetch(`${BASE}/admin/auto-recovery-rules/${ruleId}`, { method: 'DELETE' })
    .then(r => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
    })

// ── Расширение MlStatus типа (latency/rps/error metrics) ────────────────────
// Не пере-экспортим MlStatus (он в catalog.ts), но даём helper-тип для UI.

export type ModelMetrics = {
  p50_ms: number | null
  p95_ms: number | null
  rps_1m: number
  samples_count: number
  last_error_text: string | null
}

export type MlStatusWithMetrics = {
  models: Record<string, boolean>
  circuit_state: Record<string, 'closed' | 'half_open' | 'open' | 'unknown'>
  last_check_at: string | null
  last_success_at: string | null
  failures: Record<string, number>
  metrics: Record<string, ModelMetrics>
  queue: Record<string, number>
}

// ── Расширение SchedulerJob типа (tick_history) ─────────────────────────────

export type SchedulerJobTick = {
  ts: string
  duration_ms: number
  error: boolean
}

export type SchedulerJobInfoWithHistory = SchedulerJobInfo & {
  tick_history: SchedulerJobTick[]
}
