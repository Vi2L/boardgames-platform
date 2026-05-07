/**
 * Тонкий клиент к /api/catalog/* — backend сам форвардит на boardgames-catalog.
 * Все методы возвращают сырые JSON-ответы upstream'а, чтобы не плодить лишние
 * слои маппинга для прототипа UI ручного матчинга.
 */
const BASE = '/api/catalog'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

export type CatalogGame = {
  id: number
  slug: string
  title: string
  year: number | null
  bgg_id: number | null
  tesera_id: number | null
  source: string
  status: string
  cover_url: string | null
}

export type CatalogGameList = {
  items: CatalogGame[]
  total: number
  limit: number
  offset: number
}

export type CatalogOffer = {
  id: number
  game_id: number | null
  store_slug: string
  external_id: string
  url: string
  title_raw: string
  image_url: string | null
  last_price: number | null
  match_status: string
  match_score: number | null
}

export type CatalogQueue = {
  items: CatalogOffer[]
  total: number
  limit: number
  offset: number
}

export const fetchCatalogHealth = () =>
  fetch(`${BASE}/health`).then(r => json<{ status: string; service?: string }>(r))

export const listCatalogGames = (q: string | undefined, limit = 20, offset = 0) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q) params.set('q', q)
  return fetch(`${BASE}/games?${params}`).then(r => json<CatalogGameList>(r))
}

export const fetchMatchingQueue = (
  store: string | undefined, limit = 50, offset = 0,
) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (store) params.set('store', store)
  return fetch(`${BASE}/matching/queue?${params}`).then(r => json<CatalogQueue>(r))
}

export const linkOffer = (offerId: number, gameId: number) =>
  fetch(`${BASE}/matching/${offerId}/link`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ game_id: gameId }),
  }).then(r => json<CatalogOffer>(r))

export const rejectOffer = (offerId: number) =>
  fetch(`${BASE}/matching/${offerId}/reject`, { method: 'POST' })
    .then(r => json<CatalogOffer>(r))
