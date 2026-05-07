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

export type CatalogGameAlias = {
  id: number
  alias: string
  source: string
  language: string | null
  verified: boolean
}

export type CatalogGameBgg = {
  bgg_id: number
  rank: number | null
  bayes_average: number | null
  average: number | null
  users_rated: number | null
  is_expansion: boolean
  subtype_ranks: Record<string, unknown> | null
  description: string | null
  designers: string[] | null
  artists: string[] | null
  publishers: string[] | null
  mechanics: string[] | null
  categories: string[] | null
  min_players: number | null
  max_players: number | null
  min_age: number | null
  playtime_min: number | null
  playtime_max: number | null
  image_url: string | null
  thumbnail_url: string | null
  source: string | null
  fetched_at: string
}

export type CatalogGameWikidata = {
  bgg_id: number | null
  entity_id: string | null
  found: boolean
  labels: Record<string, string>
  aliases: Record<string, string[]>
  descriptions: Record<string, string>
  fetched_at: string
}

export type CatalogGameDetail = CatalogGame & {
  designers: string[] | null
  publishers: string[] | null
  players_min: number | null
  players_max: number | null
  age_min: number | null
  playtime_min: number | null
  playtime_max: number | null
  description: string | null
  meta: Record<string, unknown> | null
  created_at: string
  updated_at: string
  aliases: CatalogGameAlias[]
  bgg: CatalogGameBgg | null
  wikidata: CatalogGameWikidata | null
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

export const fetchCatalogGame = (id: number) =>
  fetch(`${BASE}/games/${id}`).then(r => json<CatalogGameDetail>(r))

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

// ── Game CRUD (manual) ─────────────────────────────────────────────

export type GameCreatePayload = {
  slug: string
  title: string
  year?: number | null
  designers?: string[] | null
  publishers?: string[] | null
  players_min?: number | null
  players_max?: number | null
  age_min?: number | null
  playtime_min?: number | null
  playtime_max?: number | null
  bgg_id?: number | null
  tesera_id?: number | null
  cover_url?: string | null
  description?: string | null
  source?: string
}

export type GamePatchPayload = Partial<Omit<GameCreatePayload, 'slug'>> & {
  status?: string
}

export const createGame = (payload: GameCreatePayload) =>
  fetch(`${BASE}/games`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<CatalogGame>(r))

export const patchGame = (gameId: number, payload: GamePatchPayload) =>
  fetch(`${BASE}/games/${gameId}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<CatalogGame>(r))

// ── Imports (BGG / Tesera) ──────────────────────────────────────────

export type ImportJobStatus = 'pending' | 'running' | 'done' | 'failed'

export type ImportJobResult = {
  imported?: Array<{ bgg_id?: number; tesera_id?: number; item?: string|number; game_id: number; title: string }>
  errors?: Array<{ bgg_id?: number; item?: string|number; error: string }>
} | null

export type ImportJob = {
  id: number
  type: 'bgg' | 'tesera'
  status: ImportJobStatus
  payload: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  error: string | null
  result: ImportJobResult
  created_at: string
}

export const importBgg = (payload: { bgg_id?: number; ids?: number[] }) =>
  fetch(`${BASE}/import/bgg`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<ImportJob>(r))

export const importTesera = (payload: { alias?: string; tesera_id?: number; items?: (string|number)[] }) =>
  fetch(`${BASE}/import/tesera`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<ImportJob>(r))

export const fetchImportJob = (id: number) =>
  fetch(`${BASE}/import/jobs/${id}`).then(r => json<ImportJob>(r))

// ── Aliases CRUD ──────────────────────────────────────────────────────

export type AliasInput = {
  alias: string
  source?: string
  language?: string | null
  verified?: boolean
}

export const addAlias = (gameId: number, payload: AliasInput) =>
  fetch(`${BASE}/games/${gameId}/aliases`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<CatalogGameAlias>(r))

export const patchAlias = (
  gameId: number, aliasId: number, payload: Partial<AliasInput>,
) =>
  fetch(`${BASE}/games/${gameId}/aliases/${aliasId}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<CatalogGameAlias>(r))

export const deleteAlias = async (gameId: number, aliasId: number) => {
  const r = await fetch(`${BASE}/games/${gameId}/aliases/${aliasId}`, {
    method: 'DELETE',
  })
  if (!r.ok && r.status !== 204) throw new Error(`${r.status} ${await r.text()}`)
}
