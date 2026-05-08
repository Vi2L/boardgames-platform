/**
 * Fetch-функции для /api/sources/* (web-test backend → catalog).
 *
 * Все ручки провайдер-параметрические: provider передаётся явно в URL, чтобы
 * один и тот же UI-код работал с любым подключённым источником.
 */

const BASE = '/api/sources'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

// ─── Types ────────────────────────────────────────────────────────────────────

export type ScrapeRunStatus =
  | 'running' | 'ready' | 'applied' | 'discarded' | 'failed'

export type ScrapeRunTotals = {
  new?: number
  updated?: number
  unchanged?: number
  total_slugs?: number
  errors?: number
  applied?: number
}

export type ScrapeRun = {
  id: number
  provider: string
  status: ScrapeRunStatus
  params: Record<string, unknown>
  totals: ScrapeRunTotals
  error_message: string | null
  log_lines: string[]
  started_at: string
  finished_at: string | null
  performed_by: string | null
}

export type ScrapeRunList = { runs: ScrapeRun[]; total: number }

export type ScrapeChangeType = 'new' | 'updated' | 'unchanged'

export type ScrapeItem = {
  id: number
  run_id: number
  slug: string
  payload: Record<string, unknown>
  content_hash: string
  prev_hash: string | null
  change_type: ScrapeChangeType
  field_diffs: Record<string, { before: unknown; after: unknown }> | null
  fetched_at: string
}

export type ScrapeItemList = { items: ScrapeItem[]; total: number }

export type ScrapeRunCreate = {
  max_items?: number | null
  only_year?: number | null
  extra?: Record<string, unknown>
}

export type ScrapeRunApplyRequest = {
  item_ids?: number[]
  change_types?: ScrapeChangeType[]
  performed_by?: string
}

export type MatchWeights = { ru: number; en: number; alias: number }

export type MatchParams = {
  threshold: number
  prefer_external_id: boolean
  weights: MatchWeights
}

export type MatchProfile = {
  id: number
  provider: string
  name: string
  params: MatchParams
  is_default: boolean
  updated_at: string
}

// ─── Detection runs ───────────────────────────────────────────────────────────

export const startSourceRun = (provider: string, body: ScrapeRunCreate) =>
  fetch(`${BASE}/${provider}/runs`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }).then(r => json<ScrapeRun>(r))

export const fetchSourceRuns = (provider: string, limit = 20, offset = 0) => {
  const u = new URL(`${BASE}/${provider}/runs`, window.location.origin)
  u.searchParams.set('limit', String(limit))
  u.searchParams.set('offset', String(offset))
  return fetch(u.toString().replace(window.location.origin, ''))
    .then(r => json<ScrapeRunList>(r))
}

export const fetchSourceRun = (provider: string, runId: number) =>
  fetch(`${BASE}/${provider}/runs/${runId}`).then(r => json<ScrapeRun>(r))

export const fetchSourceRunItems = (
  provider: string,
  runId: number,
  opts: { changeType?: ScrapeChangeType; search?: string; limit?: number; offset?: number } = {},
) => {
  const u = new URL(
    `${BASE}/${provider}/runs/${runId}/items`,
    window.location.origin,
  )
  if (opts.changeType) u.searchParams.set('change_type', opts.changeType)
  if (opts.search) u.searchParams.set('search', opts.search)
  u.searchParams.set('limit', String(opts.limit ?? 50))
  u.searchParams.set('offset', String(opts.offset ?? 0))
  return fetch(u.toString().replace(window.location.origin, ''))
    .then(r => json<ScrapeItemList>(r))
}

export const applySourceRun = (
  provider: string, runId: number, body: ScrapeRunApplyRequest,
) =>
  fetch(`${BASE}/${provider}/runs/${runId}/apply`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }).then(r => json<{ run_id: number; applied: number }>(r))

export const discardSourceRun = (provider: string, runId: number) =>
  fetch(`${BASE}/${provider}/runs/${runId}/discard`, {
    method: 'POST',
  }).then(r => json<{ run_id: number; status: string }>(r))

// ─── Match profiles ───────────────────────────────────────────────────────────

export const fetchMatchProfiles = (provider: string) =>
  fetch(`${BASE}/${provider}/match-profiles`).then(r => json<MatchProfile[]>(r))

export const upsertMatchProfile = (
  provider: string,
  body: { name: string; params: MatchParams; is_default?: boolean },
) =>
  fetch(`${BASE}/${provider}/match-profiles`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }).then(r => json<MatchProfile>(r))

export const deleteMatchProfile = async (provider: string, profileId: number) => {
  const res = await fetch(`${BASE}/${provider}/match-profiles/${profileId}`, {
    method: 'DELETE',
  })
  if (!res.ok && res.status !== 204) throw new Error(`${res.status} ${await res.text()}`)
}

// ─── Promotion candidates с MatchParams ───────────────────────────────────────

export const fetchPromotionCandidatesWithParams = (
  provider: string,
  rawId: number,
  params: MatchParams,
  limit = 5,
) => {
  const u = new URL(
    `${BASE}/${provider}/promotion/${rawId}/candidates`,
    window.location.origin,
  )
  u.searchParams.set('threshold', String(params.threshold))
  u.searchParams.set('limit', String(limit))
  u.searchParams.set('prefer_external_id', String(params.prefer_external_id))
  u.searchParams.set('weight_ru', String(params.weights.ru))
  u.searchParams.set('weight_en', String(params.weights.en))
  u.searchParams.set('weight_alias', String(params.weights.alias))
  return fetch(u.toString().replace(window.location.origin, '')).then(r => json(r))
}

export const DEFAULT_MATCH_PARAMS: MatchParams = {
  threshold: 0.5,
  prefer_external_id: false,
  weights: { ru: 1.0, en: 1.0, alias: 1.0 },
}
