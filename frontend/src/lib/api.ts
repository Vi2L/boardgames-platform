import type {
  HealthOut, ParserStatsOut, PriceDeltaOut, PricePointOut,
  ProductDetailOut, ProductsPage, SearchesPage,
  StoreOut, StoreStatsResponse, SummaryStatsResponse,
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
