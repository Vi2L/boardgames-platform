/**
 * Клиент к /api/bgg-sync/* — proxy на catalog'овые /scheduler/*, /import/jobs,
 * /import/bgg/{geeklist,mini-batch}, /bgg/{hotness,geeklists}.
 *
 * Типы зеркалят response_model из catalog/schemas.py:
 *   SchedulerJobOut, ImportJobOut.
 *
 * Cache-key namespace в react-query — `['bgg-sync', ...]`.
 */
import type { ImportJob } from './catalog'

const BASE = '/api/bgg-sync'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

// ── Scheduler ────────────────────────────────────────────────────────────────

/**
 * WT-F7: описание одного поля в schema-driven форме параметров job'а.
 * Зеркало catalog/scheduler.py:FieldSpec.
 */
export type FieldSpec = {
  name: string
  type: 'int' | 'float' | 'bool' | 'string' | 'enum'
  label: string
  description?: string
  default: unknown
  required?: boolean
  enum?: string[]
  min?: number
  max?: number
}

/** Один scheduler-job: конфиг из БД + runtime info из APScheduler + meta. */
export type SchedulerJob = {
  job_id: string
  cron_expr: string
  enabled: boolean
  params: Record<string, unknown>
  // Денормализация — обновляется при каждом trigger'е.
  last_run_job_id: number | null
  last_run_status: 'pending' | 'running' | 'done' | 'failed' | null
  last_run_at: string | null
  // Из APScheduler runtime.
  next_run_at: string | null
  // Из реестра JOB_METADATA.
  display_name: string | null
  description: string | null
  // Ring-buffer тиков для interval-job'ов (заполнен для match_worker/ml_health/etc.).
  tick_history?: Array<{ ts: string; duration_ms: number; error: boolean }>
  // WT-F7: если null — UI показывает JSON-textarea (legacy fallback).
  params_schema: FieldSpec[] | null
}

export type RescheduleRequest = {
  cron_expr?: string
  enabled?: boolean
  params?: Record<string, unknown>
}

/** WT-F7: ответ bulk-action endpoint'ов. */
export type SchedulerBulkActionResult = {
  action: string
  affected: string[]
  triggered_import_job_ids: number[]
  errors: Array<{ job_id: string; error: string }>
}

/** WT-F7: сводка Global BGG Settings. */
export type BggRuntimeSummary = {
  bgg_api_token_set: boolean
  family_cascade_enabled: boolean
  family_cascade_enabled_editable: boolean
  family_cascade_rate_limit_sec: number
}

export const fetchSchedulerJobs = () =>
  fetch(`${BASE}/scheduler/jobs`).then(r => json<SchedulerJob[]>(r))

export const rescheduleJob = (jobId: string, payload: RescheduleRequest) =>
  fetch(`${BASE}/scheduler/jobs/${encodeURIComponent(jobId)}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<SchedulerJob>(r))

export const triggerSchedulerJob = (jobId: string) =>
  fetch(`${BASE}/scheduler/jobs/${encodeURIComponent(jobId)}/trigger`, {
    method: 'POST',
  }).then(r => json<ImportJob>(r))

// WT-F7 bulk actions.
export const pauseAllJobs = () =>
  fetch(`${BASE}/scheduler/jobs/pause-all`, { method: 'POST' })
    .then(r => json<SchedulerBulkActionResult>(r))

export const resumeAllJobs = () =>
  fetch(`${BASE}/scheduler/jobs/resume-all`, { method: 'POST' })
    .then(r => json<SchedulerBulkActionResult>(r))

export const triggerOverdueJobs = () =>
  fetch(`${BASE}/scheduler/jobs/trigger-overdue`, { method: 'POST' })
    .then(r => json<SchedulerBulkActionResult>(r))

export const fetchBggSettings = () =>
  fetch(`${BASE}/settings/bgg`).then(r => json<BggRuntimeSummary>(r))

// ── Import history ───────────────────────────────────────────────────────────

export type ImportJobsFilter = {
  type?: string
  status?: 'pending' | 'running' | 'done' | 'failed'
  trigger?: 'manual' | 'scheduled' | 'api'
  limit?: number
  offset?: number
}

export const fetchImportJobs = (filter: ImportJobsFilter = {}) => {
  const qs = new URLSearchParams()
  if (filter.type) qs.set('type', filter.type)
  if (filter.status) qs.set('status', filter.status)
  if (filter.trigger) qs.set('trigger', filter.trigger)
  qs.set('limit', String(filter.limit ?? 50))
  qs.set('offset', String(filter.offset ?? 0))
  return fetch(`${BASE}/jobs?${qs}`).then(r => json<ImportJob[]>(r))
}

// ── Manual triggers ──────────────────────────────────────────────────────────

export type GeeklistImportPayload = {
  geeklist_id: number
  auto_import?: boolean
}

export const importBggGeeklist = (payload: GeeklistImportPayload) =>
  fetch(`${BASE}/imports/geeklist`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<ImportJob>(r))

export type MiniBatchImportPayload = {
  batch_size?: number
  skip_recent_days?: number
  rate_limit_sec?: number
  dry_run?: boolean
}

export const importBggMiniBatch = (payload: MiniBatchImportPayload = {}) =>
  fetch(`${BASE}/imports/mini-batch`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<ImportJob>(r))

// ── BGG snapshots (Hotness + GeekList) ───────────────────────────────────────

export type HotnessItem = {
  rank: number
  bgg_id: number
  name: string
  year: number | null
  thumbnail_url: string | null
  // Денормализация: catalog game_id если игра уже в каталоге.
  game_id: number | null
  game_title: string | null
}

export type HotnessSnapshot = {
  snapshot_date: string | null
  items: HotnessItem[]
}

export const fetchHotnessDates = (limit = 30) =>
  fetch(`${BASE}/hotness/dates?limit=${limit}`).then(r => json<string[]>(r))

export const fetchHotnessSnapshot = (date?: string) => {
  const url = date ? `${BASE}/hotness?date=${date}` : `${BASE}/hotness`
  return fetch(url).then(r => json<HotnessSnapshot>(r))
}

export type GeeklistMeta = {
  geeklist_id: number
  latest_snapshot_date: string
  title: string | null
  username: string | null
  item_count: number
}

export type GeeklistItem = {
  rank: number
  bgg_id: number
  name: string
  body: string | null
  game_id: number | null
  game_title: string | null
}

export type GeeklistSnapshot = {
  geeklist_id: number
  snapshot_date: string
  title: string | null
  description: string | null
  username: string | null
  item_count: number
  items: GeeklistItem[]
  fetched_at: string
}

export const fetchGeeklists = () =>
  fetch(`${BASE}/geeklists`).then(r => json<GeeklistMeta[]>(r))

export const fetchGeeklistSnapshot = (geeklistId: number, date?: string) => {
  const url = date
    ? `${BASE}/geeklists/${geeklistId}?date=${date}`
    : `${BASE}/geeklists/${geeklistId}`
  return fetch(url).then(r => json<GeeklistSnapshot>(r))
}
