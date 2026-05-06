import type { ParserStatsOut, PricePointOut, StoreOut } from '../types/api'

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
