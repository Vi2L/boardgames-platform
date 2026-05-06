import type { HealthOut, ParserStatsOut, PriceDeltaOut, PricePointOut, StoreOut } from '../types/api'

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
