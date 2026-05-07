import type {
  CompareResponse,
  DebugFeatures, DebugParseResponse,
  DiffResult, FavoriteOut,
  HealthOut, ParserSnapshotFull, ParserSnapshotMeta, ParserStatsOut, PriceDeltaOut, PricePointOut,
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

export const fetchHealth = () =>
  fetch(`${BASE}/health`).then(r => json<HealthOut>(r))

export const fetchRecentDeltas = (ids: number[]) => {
  if (ids.length === 0) return Promise.resolve([] as PriceDeltaOut[])
  const q = ids.join(',')
  return fetch(`${BASE}/products/recent-deltas?ids=${q}`).then(r => json<PriceDeltaOut[]>(r))
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

export const fetchFavorites = () =>
  fetch(`${BASE}/favorites`).then(r => json<FavoriteOut[]>(r))

export const createFavorite = (payload: {
  query: string; stores?: string[]; limit?: number; refresh?: boolean
}) =>
  fetch(`${BASE}/favorites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<FavoriteOut>(r))

export const deleteFavorite = (id: number) =>
  fetch(`${BASE}/favorites/${id}`, { method: 'DELETE' }).then(r => json<{ deleted: boolean }>(r))
