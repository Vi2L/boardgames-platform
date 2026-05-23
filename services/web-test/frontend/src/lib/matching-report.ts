/**
 * Типы и fetch-функции для отчётов по матчингу (CAT-17).
 *
 * Соответствуют backend-эндпоинтам в `services/catalog/catalog/routers/
 * matching_report.py` через web-test proxy `/api/catalog/matching/report/*`.
 *
 * Используется компонентом `components/matching/ReportTab.tsx`.
 */

// ─── Top unmatched ──────────────────────────────────────────────────────────

export interface TopUnmatchedItem {
  title_norm: string
  count: number
  first_seen: string  // ISO datetime
  last_seen: string
  sample_title_raw: string
  stores: string[]
}

export interface TopUnmatchedResponse {
  items: TopUnmatchedItem[]
  days: number
  min_count: number
}

export async function fetchTopUnmatched(params: {
  days?: number
  limit?: number
  min_count?: number
  store_slug?: string | null
}): Promise<TopUnmatchedResponse> {
  const qs = new URLSearchParams()
  if (params.days != null) qs.set('days', String(params.days))
  if (params.limit != null) qs.set('limit', String(params.limit))
  if (params.min_count != null) qs.set('min_count', String(params.min_count))
  if (params.store_slug) qs.set('store_slug', params.store_slug)
  const r = await fetch(`/api/catalog/matching/report/top-unmatched?${qs.toString()}`)
  if (!r.ok) throw new Error(`top-unmatched: HTTP ${r.status}`)
  return r.json()
}

// ─── Coverage by store ──────────────────────────────────────────────────────

export interface CoverageStoreItem {
  store_slug: string
  total: number
  matched_auto: number
  matched_manual: number
  pending_ml: number
  unmatched: number
  rejected: number
  coverage_pct: number
}

export interface CoverageResponse {
  stores: CoverageStoreItem[]
  days: number
}

export async function fetchCoverageByStore(days: number = 7): Promise<CoverageResponse> {
  const r = await fetch(`/api/catalog/matching/report/coverage?days=${days}`)
  if (!r.ok) throw new Error(`coverage: HTTP ${r.status}`)
  return r.json()
}

// ─── Activity timeline ──────────────────────────────────────────────────────

export interface ActivityRow {
  day: string  // ISO date
  action: string
  performed_by: string
  count: number
}

export interface ActivityResponse {
  rows: ActivityRow[]
  days: number
}

export async function fetchActivityTimeline(days: number = 14): Promise<ActivityResponse> {
  const r = await fetch(`/api/catalog/matching/report/activity?days=${days}`)
  if (!r.ok) throw new Error(`activity: HTTP ${r.status}`)
  return r.json()
}

// ─── SLA per tier ───────────────────────────────────────────────────────────

export interface TierShare {
  count: number
  share_pct: number
}

export interface TierLatency {
  p50_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
}

export interface SlaResponse {
  days: number
  tier_share: Record<string, TierShare>  // ключи: t0/t1/t2/t3/manual/unmatched/rejected/pending
  latency: Record<string, TierLatency>   // ключи: t2/t3
}

export async function fetchSlaStats(days: number = 7): Promise<SlaResponse> {
  const r = await fetch(`/api/catalog/matching/report/sla?days=${days}`)
  if (!r.ok) throw new Error(`sla: HTTP ${r.status}`)
  return r.json()
}

// ─── Publisher prefixes CRUD (CAT-17.2) ─────────────────────────────────────

export interface PublisherPrefix {
  id: number
  prefix: string
  normalized: string | null
  source: string
  is_active: boolean
  created_at: string
}

export interface PrefixListResponse {
  items: PublisherPrefix[]
  total: number
}

export async function fetchPublisherPrefixes(
  is_active?: boolean,
): Promise<PrefixListResponse> {
  const qs = new URLSearchParams()
  if (is_active != null) qs.set('is_active', String(is_active))
  const r = await fetch(`/api/catalog/matching/publisher-prefixes?${qs.toString()}`)
  if (!r.ok) throw new Error(`prefixes-list: HTTP ${r.status}`)
  return r.json()
}

export async function createPublisherPrefix(payload: {
  prefix: string
  normalized?: string | null
  source?: string
}): Promise<PublisherPrefix> {
  const r = await fetch('/api/catalog/matching/publisher-prefixes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) {
    const detail = await r.text()
    throw new Error(`create-prefix: HTTP ${r.status}: ${detail}`)
  }
  return r.json()
}

export async function deletePublisherPrefix(prefix_id: number): Promise<{ deleted: true; id: number; prefix: string }> {
  const r = await fetch(`/api/catalog/matching/publisher-prefixes/${prefix_id}`, {
    method: 'DELETE',
  })
  if (!r.ok) throw new Error(`delete-prefix: HTTP ${r.status}`)
  return r.json()
}

export async function reloadPipeline(): Promise<{ reloaded: boolean; prefixes_count: number }> {
  const r = await fetch('/api/catalog/matching/pipeline/reload', { method: 'POST' })
  if (!r.ok) throw new Error(`pipeline-reload: HTTP ${r.status}`)
  return r.json()
}
