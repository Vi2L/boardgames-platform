import type {
  CompareResponse, ContractResponse,
  DebugFeatures, DebugFetchUrlResult, DebugParseResponse,
  DiffResult, FavoriteOut, FieldCoverageRow,
  HealthAllResponse,
  HealthOut, ParserSnapshotFull, ParserSnapshotMeta, ParserStatsOut, PriceDeltaOut, PricePointOut, PriceStatsOut,
  ProductDetailOut, ProductsPage, SearchesPage,
  SnapshotFull, SnapshotsPage, StoreOut, StoreStatsResponse,
  SuiteOut, SuiteQuery, SuiteRunMeta, SummaryStatsResponse,
} from '../types/api'

const BASE = '/api'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

export const fetchStores = () =>
  fetch(`${BASE}/stores`).then(r => json<StoreOut[]>(r))

export const fetchParsers = () =>
  fetch(`${BASE}/parsers`).then(r => json<ParserStatsOut[]>(r))

export const fetchHistory = (id: number) =>
  fetch(`${BASE}/products/${id}/history`).then(r => json<PricePointOut[]>(r))

export const fetchOfferHistory = (storeSlug: string, externalId: string) =>
  fetch(`${BASE}/offers/history?store_slug=${encodeURIComponent(storeSlug)}&external_id=${encodeURIComponent(externalId)}`)
    .then(r => json<PricePointOut[]>(r))

export const fetchHealth = () =>
  fetch(`${BASE}/health`).then(r => json<HealthOut>(r))

export const fetchHealthAll = () =>
  fetch(`${BASE}/health/all`).then(r => json<HealthAllResponse>(r))

export const fetchRecentDeltas = (ids: number[]) => {
  if (ids.length === 0) return Promise.resolve([] as PriceDeltaOut[])
  const q = ids.join(',')
  return fetch(`${BASE}/products/recent-deltas?ids=${q}`).then(r => json<PriceDeltaOut[]>(r))
}

export const fetchPriceStats = (ids: number[]) => {
  if (ids.length === 0) return Promise.resolve([] as PriceStatsOut[])
  const q = ids.join(',')
  return fetch(`${BASE}/products/price-stats?ids=${q}`).then(r => json<PriceStatsOut[]>(r))
}

// ── DatabasePage / ProductPage ─────────────────────────────────────────

interface ListProductsParams {
  q?: string
  store?: string
  page?: number
  page_size?: number
  sort?: 'fetched_desc' | 'price_asc' | 'price_desc' | 'title_asc'
}

export const fetchDbProducts = (params: ListProductsParams = {}) => {
  const sp = new URLSearchParams()
  if (params.q) sp.set('q', params.q)
  if (params.store) sp.set('store', params.store)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  if (params.sort) sp.set('sort', params.sort)
  return fetch(`${BASE}/db/products?${sp}`).then(r => json<ProductsPage>(r))
}

export const fetchDbProduct = (id: number) =>
  fetch(`${BASE}/db/products/${id}`).then(r => json<ProductDetailOut>(r))

export const deleteDbProduct = (id: number) =>
  fetch(`${BASE}/db/products/${id}`, { method: 'DELETE' }).then(r => json<{ deleted: boolean; id: number }>(r))

export const fetchDbSearches = (page = 1, page_size = 50, query?: string) => {
  const sp = new URLSearchParams({ page: String(page), page_size: String(page_size) })
  if (query) sp.set('query', query)
  return fetch(`${BASE}/db/searches?${sp}`).then(r => json<SearchesPage>(r))
}

export const fetchStatsSummary = (hours = 24) =>
  fetch(`${BASE}/stats/summary?hours=${hours}`).then(r => json<SummaryStatsResponse>(r))

export const fetchStatsStores = () =>
  fetch(`${BASE}/stats/stores`).then(r => json<StoreStatsResponse>(r))

export const fetchStatsErrors = (limit = 20) =>
  fetch(`${BASE}/stats/errors?limit=${limit}`).then(r => json<unknown[]>(r))

// ── Parsers DB explorer (F4.1) ──────────────────────────────────────────

/**
 * Источник правды для имён полей — `parsers/api.py` / `services/web-test/app/api/parsers_db.py`.
 *
 * `tables` — counts из всех таблиц БД parsers (stores/products/price_observations/
 * request_log/parser_log). UI показывает product_count/observation_count из tables,
 * чтобы не плодить миграций при добавлении новых таблиц.
 */
export type ParsersDbMeta = {
  db_size_bytes: number
  db_size_mb: number
  tables: Record<string, number>
  oldest_observation: string | null
  newest_observation: string | null
  [k: string]: unknown
}

/** parsers `/api/db/stores-inventory` — цены сразу в рублях. */
export type ParsersStoreInventory = {
  store_slug: string
  products_count: number
  observations_count: number
  min_price_rub: number | null
  mean_price_rub: number | null
  max_price_rub: number | null
  oldest_obs: string | null
  newest_obs: string | null
  [k: string]: unknown
}

export type ParsersDbProductRow = {
  id: number
  store_slug: string
  external_id: string
  title: string
  url: string
  last_price: number | null
  last_fetched_at: string | null
  [k: string]: unknown
}

export type ParsersDbProductsPage = {
  items: ParsersDbProductRow[]
  total: number
  limit: number
  offset: number
  [k: string]: unknown
}

export type ParsersTopQuery = {
  query: string
  count: number
  cache_hits: number
  cache_hit_rate: number          // 0..100
  avg_ms: number | null
  errors: number
  last_seen: string | null
  [k: string]: unknown
}

export type ParsersLatency = {
  p50: number | null
  p95: number | null
  p99: number | null
  max: number | null
  avg: number | null
  count: number
  [k: string]: unknown
}

export type ParsersEmptyResponse = {
  store_slug: string
  query: string
  ts: string
  duration_ms: number | null
  [k: string]: unknown
}

export const fetchParsersDbMeta = () =>
  fetch(`${BASE}/parsers-db/meta`).then(r => json<ParsersDbMeta>(r))

export const fetchParsersStoresInventory = () =>
  fetch(`${BASE}/parsers-db/stores-inventory`).then(r => json<ParsersStoreInventory[]>(r))

export const fetchParsersDbProducts = (params: {
  store?: string; q?: string; limit?: number; offset?: number
} = {}) => {
  const sp = new URLSearchParams()
  if (params.store) sp.set('store', params.store)
  if (params.q) sp.set('q', params.q)
  if (params.limit) sp.set('limit', String(params.limit))
  if (params.offset) sp.set('offset', String(params.offset))
  return fetch(`${BASE}/parsers-db/products?${sp}`).then(r => json<ParsersDbProductsPage>(r))
}

export const fetchParsersTopQueries = (hours = 168, limit = 20) =>
  fetch(`${BASE}/parsers-db/top-queries?hours=${hours}&limit=${limit}`).then(r => json<ParsersTopQuery[]>(r))

export const fetchParsersLatency = (hours = 24) =>
  fetch(`${BASE}/parsers-db/latency?hours=${hours}`).then(r => json<ParsersLatency>(r))

export const fetchParsersEmptyResponses = (hours = 24, limit = 50) =>
  fetch(`${BASE}/parsers-db/empty-responses?hours=${hours}&limit=${limit}`).then(r => json<ParsersEmptyResponse[]>(r))

export type ParsersProductDetail = {
  id: number
  store_slug: string
  external_id: string
  title: string
  url: string
  observations: Array<{
    id: number
    price: number
    fetched_at: string
    raw_json?: string
    [k: string]: unknown
  }>
  [k: string]: unknown
}

export const fetchParsersDbProduct = (id: number) =>
  fetch(`${BASE}/parsers-db/products/${id}`).then(r => json<ParsersProductDetail>(r))

export const deleteParsersObservation = async (id: number) => {
  const r = await fetch(`${BASE}/parsers-db/observations/${id}`, { method: 'DELETE' })
  if (!r.ok && r.status !== 204) throw new Error(`${r.status} ${await r.text()}`)
}

// ── Charts (F4.1-extended: timeline, histogram, distribution, breakdown, raw-keys) ──

export type ParsersTimelinePoint = {
  ts: string
  total: number
  cache: number
  network: number
  partial: number
  errors: number
  avg_ms: number | null
  [k: string]: unknown
}

export type ParsersLatencyBin = {
  bin: string
  count: number
  [k: string]: unknown
}

export type ParsersStoreDistribution = {
  store_slug: string
  calls: number
  successes: number
  success_rate: number
  avg_results: number | null
  avg_ms: number | null
  share_pct: number
  [k: string]: unknown
}

export type ParsersBreakdownEntry = {
  store_slug: string
  calls: number
  successes: number
  avg_search_ms: number | null
  avg_enrich_ms: number | null
  avg_total_ms: number | null
  avg_http_requests: number | null
  [k: string]: unknown
}

export type ParsersRawKeyEntry = {
  store_slug: string
  keys: Array<{ key: string; count: number }>
  [k: string]: unknown
}

export const fetchParsersTimeline = (bucket: 'hour' | 'day' = 'hour', hours = 24) =>
  fetch(`${BASE}/parsers-db/timeline?bucket=${bucket}&hours=${hours}`).then(r => json<ParsersTimelinePoint[]>(r))

export const fetchParsersLatencyHistogram = (hours = 24) =>
  fetch(`${BASE}/parsers-db/latency-histogram?hours=${hours}`).then(r => json<ParsersLatencyBin[]>(r))

export const fetchParsersStoreDistribution = (hours = 24) =>
  fetch(`${BASE}/parsers-db/store-distribution?hours=${hours}`).then(r => json<ParsersStoreDistribution[]>(r))

export const fetchParsersParserBreakdown = () =>
  fetch(`${BASE}/parsers-db/parser-breakdown`).then(r => json<ParsersBreakdownEntry[]>(r))

export const fetchParsersRawKeys = (topN = 10) =>
  fetch(`${BASE}/parsers-db/raw-keys?top_n=${topN}`).then(r => json<ParsersRawKeyEntry[]>(r))

// ── DLQ (F5.1) ───────────────────────────────────────────────────────

export type DlqItem = {
  id: number
  attempt_count: number
  last_error: string | null
  created_at: string
  last_attempt_at: string
  payload_size: number
}

export type DlqListResponse = {
  total: number
  limit: number
  offset: number
  items: DlqItem[]
}

export type DlqReplayResult = {
  status: 'ok' | 'failed'
  deleted?: boolean
  error?: string | null
}

export type DlqReplayAllResult = {
  replayed: number
  success: number
  failed: number
}

export const fetchDlq = (limit = 100, offset = 0) =>
  fetch(`${BASE}/dlq?limit=${limit}&offset=${offset}`).then(r => json<DlqListResponse>(r))

export const replayDlq = (id: number) =>
  fetch(`${BASE}/dlq/${id}/replay`, { method: 'POST' }).then(r => json<DlqReplayResult>(r))

export const replayDlqAll = (limit = 50) =>
  fetch(`${BASE}/dlq/replay-all?limit=${limit}`, { method: 'POST' }).then(r => json<DlqReplayAllResult>(r))

export const deleteDlq = async (id: number) => {
  const r = await fetch(`${BASE}/dlq/${id}`, { method: 'DELETE' })
  if (!r.ok && r.status !== 204) throw new Error(`${r.status} ${await r.text()}`)
}

// ── Cache invalidation ──────────────────────────────────────────────────

export interface CacheInvalidateResult {
  deleted_products: number
  deleted_observations: number
  store: string | null
  query: string | null
}

export const invalidateParserCache = (params: {
  store?: string; q?: string; confirm?: boolean
} = {}) => {
  const sp = new URLSearchParams()
  if (params.store) sp.set('store', params.store)
  if (params.q) sp.set('q', params.q)
  if (params.confirm) sp.set('confirm', 'true')
  return fetch(`${BASE}/parsers/cache?${sp}`, { method: 'DELETE' })
    .then(r => json<CacheInvalidateResult>(r))
}

// ── Debug / Live Test ──────────────────────────────────────────────────

export const debugParse = (params: { q: string; stores?: string[]; limit?: number }) => {
  const sp = new URLSearchParams({ q: params.q })
  if (params.stores && params.stores.length > 0) sp.set('stores', params.stores.join(','))
  if (params.limit) sp.set('limit', String(params.limit))
  return fetch(`${BASE}/debug/parse?${sp}`).then(r => json<DebugParseResponse>(r))
}

export const debugCompare = (params: { q: string; stores?: string[]; limit?: number }) => {
  const sp = new URLSearchParams({ q: params.q })
  if (params.stores && params.stores.length > 0) sp.set('stores', params.stores.join(','))
  if (params.limit) sp.set('limit', String(params.limit))
  return fetch(`${BASE}/debug/compare?${sp}`).then(r => json<CompareResponse>(r))
}

export const fetchDebugFeatures = () =>
  fetch(`${BASE}/debug/features`).then(r => json<DebugFeatures>(r))

export const fetchRawSnapshots = (params: {
  store?: string; query?: string; hours?: number; limit?: number
} = {}) => {
  const sp = new URLSearchParams()
  if (params.store) sp.set('store', params.store)
  if (params.query) sp.set('query', params.query)
  if (params.hours) sp.set('hours', String(params.hours))
  if (params.limit) sp.set('limit', String(params.limit))
  return fetch(`${BASE}/debug/snapshots?${sp}`).then(r => json<ParserSnapshotMeta[]>(r))
}

export const fetchRawSnapshot = (id: number) =>
  fetch(`${BASE}/debug/snapshots/${id}`).then(r => json<ParserSnapshotFull>(r))

export const rawSnapshotTextUrl = (id: number) => `${BASE}/debug/snapshots/${id}/raw`

export const fetchContract = () =>
  fetch(`${BASE}/debug/contract`).then(r => json<ContractResponse>(r))

export const fetchFieldCoverage = () =>
  fetch(`${BASE}/debug/field-coverage`).then(r => json<FieldCoverageRow[]>(r))

export const debugFetchUrl = (params: { url: string; encoding_hint?: string }) => {
  const sp = new URLSearchParams({ url: params.url })
  if (params.encoding_hint) sp.set('encoding_hint', params.encoding_hint)
  return fetch(`${BASE}/debug/fetch-url?${sp}`).then(r => json<DebugFetchUrlResult>(r))
}

// ── Snapshots / Suites / Favorites ─────────────────────────────────────

export const createSnapshot = (payload: {
  name?: string; query: string; stores?: string[]; limit?: number; refresh?: boolean
}) =>
  fetch(`${BASE}/snapshots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<{ id: number; summary: unknown }>(r))

export const fetchSnapshots = (page = 1, page_size = 50, query?: string) => {
  const sp = new URLSearchParams({ page: String(page), page_size: String(page_size) })
  if (query) sp.set('query', query)
  return fetch(`${BASE}/snapshots?${sp}`).then(r => json<SnapshotsPage>(r))
}

export const fetchSnapshot = (id: number) =>
  fetch(`${BASE}/snapshots/${id}`).then(r => json<SnapshotFull>(r))

export const deleteSnapshot = (id: number) =>
  fetch(`${BASE}/snapshots/${id}`, { method: 'DELETE' }).then(r => json<{ deleted: boolean }>(r))

export const fetchSnapshotDiff = (a: number, b: number) =>
  fetch(`${BASE}/snapshots/diff?a=${a}&b=${b}`).then(r => json<DiffResult>(r))

export const fetchSuites = () =>
  fetch(`${BASE}/suites`).then(r => json<SuiteOut[]>(r))

export const fetchSuite = (id: number) =>
  fetch(`${BASE}/suites/${id}`).then(r => json<SuiteOut>(r))

export const createSuite = (payload: { name: string; description?: string; queries: SuiteQuery[] }) =>
  fetch(`${BASE}/suites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<SuiteOut>(r))

export const deleteSuite = (id: number) =>
  fetch(`${BASE}/suites/${id}`, { method: 'DELETE' }).then(r => json<{ deleted: boolean }>(r))

export const fetchSuiteRuns = (suiteId: number, limit = 10) =>
  fetch(`${BASE}/suites/${suiteId}/runs?limit=${limit}`).then(r => json<SuiteRunMeta[]>(r))

// ── Suite baselines (F4.4) ──────────────────────────────────────────

export type SuiteBaselineSpec = {
  min_count?: number
  expected_stores?: string[]
  min_field_coverage?: Record<string, number>  // field -> percent (0..100)
  notes?: string
}

export type SuiteBaseline = {
  id: number
  suite_id: number
  query: string
  baseline: SuiteBaselineSpec
  created_at: string
  updated_at: string
}

export const fetchSuiteBaselines = (suiteId: number) =>
  fetch(`${BASE}/suites/${suiteId}/baselines`).then(r => json<SuiteBaseline[]>(r))

export const upsertSuiteBaseline = (
  suiteId: number, payload: { query: string; baseline: SuiteBaselineSpec },
) =>
  fetch(`${BASE}/suites/${suiteId}/baselines`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<SuiteBaseline>(r))

export const deleteSuiteBaseline = async (suiteId: number, baselineId: number) => {
  const r = await fetch(`${BASE}/suites/${suiteId}/baselines/${baselineId}`, { method: 'DELETE' })
  if (!r.ok && r.status !== 204) throw new Error(`${r.status} ${await r.text()}`)
}

export const fetchFavorites = () =>
  fetch(`${BASE}/favorites`).then(r => json<FavoriteOut[]>(r))

export const createFavorite = (payload: {
  query: string
  stores?: string[]
  limit?: number
  refresh?: boolean
  show_out_of_stock?: boolean
  loyalty?: Record<string, unknown>
}) =>
  fetch(`${BASE}/favorites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<FavoriteOut>(r))

export const deleteFavorite = (id: number) =>
  fetch(`${BASE}/favorites/${id}`, { method: 'DELETE' }).then(r => json<{ deleted: boolean }>(r))
