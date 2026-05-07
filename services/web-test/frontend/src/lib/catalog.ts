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

export type MatchCandidate = {
  game_id: number
  score: number
  via: 'title' | 'alias'
  title: string
  slug: string
  year: number | null
  bgg_id: number | null
  tesera_id: number | null
  cover_url: string | null
  status: string
}

export type MatchCandidatesResponse = {
  title: string
  auto_threshold: number
  candidate_threshold: number
  items: MatchCandidate[]
}

export type MatchingStats = {
  total_unmatched: number
  by_store: Array<{ store_slug: string; total: number; avg_score: number | null }>
  by_bucket: { good?: number; candidate?: number; cold?: number }
  thresholds: { auto: number; candidate: number }
}

export const fetchMatchingStats = () =>
  fetch(`${BASE}/matching/stats`).then(r => json<MatchingStats>(r))

export const fetchMatchCandidates = (title: string, limit = 10) => {
  const params = new URLSearchParams({ title, limit: String(limit) })
  return fetch(`${BASE}/matching/candidates?${params}`)
    .then(r => json<MatchCandidatesResponse>(r))
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

export const reassessOffer = (offerId: number) =>
  fetch(`${BASE}/matching/${offerId}/reassess`, { method: 'POST' })
    .then(r => json<CatalogOffer>(r))

export type ReassessAllResult = {
  scanned: number
  promoted_to_auto: number
  score_improved: number
  unchanged: number
}

export const reassessAll = (params: { store?: string; max_score?: number } = {}) => {
  const sp = new URLSearchParams()
  if (params.store) sp.set('store', params.store)
  if (params.max_score != null) sp.set('max_score', String(params.max_score))
  return fetch(`${BASE}/matching/reassess-all?${sp}`, { method: 'POST' })
    .then(r => json<ReassessAllResult>(r))
}

// ── Game merge ─────────────────────────────────────────────────────

export type GameMergeResult = {
  source_id: number
  target_id: number
  offers_moved: number
  aliases_moved: number
  aliases_skipped_dup: number
}

export const mergeGames = (sourceId: number, targetId: number) =>
  fetch(`${BASE}/games/merge`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
  }).then(r => json<GameMergeResult>(r))

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

// ── Imports (BGG / Tesera / Dicefest) ──────────────────────────────────

export type ImportJobStatus = 'pending' | 'running' | 'done' | 'failed'

export type ImportJobResult = {
  // BGG/Tesera импортёры (одна игра — один объект):
  imported?: Array<{
    bgg_id?: number; tesera_id?: number; item?: string | number; slug?: string
    game_id?: number; title?: string; title_ru?: string
  }>
  errors?: Array<{ bgg_id?: number; item?: string | number; slug?: string; error: string }>
  // Dicefest-специфичные счётчики:
  total_slugs?: number
  skipped_fresh?: number
} | null

// Прогресс long-running job'а — обновляется батчами на бэке (LogBuffer).
// `phase`: collecting → parsing → done. `current_title` обновляется per-item.
export type ImportProgress = {
  phase: 'collecting' | 'parsing' | 'done' | string
  current: number
  total: number
  current_title: string | null
}

export type ImportJob = {
  id: number
  type: 'bgg' | 'tesera' | 'dicefest'
  status: ImportJobStatus
  payload: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  error: string | null
  result: ImportJobResult
  // Поля из миграции 0003 — могут быть null до первого flush'а.
  progress: ImportProgress | null
  log_lines: string[] | null
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

export const importDicefest = (payload: { max_items?: number; only_year?: number }) =>
  fetch(`${BASE}/import/dicefest`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<ImportJob>(r))

export const fetchImportJob = (id: number) =>
  fetch(`${BASE}/import/jobs/${id}`).then(r => json<ImportJob>(r))

// ── Promotion (двухстадийная схема: staging → canonical) ─────────────────

export type DicefestRawGame = {
  id: number
  slug: string
  page_url: string
  title_ru: string | null
  title_en: string | null
  publisher: string | null
  release_year: number | null
  release_month: number | null
  release_status: string | null      // data-status code, например 'v-prodazhe'
  description: string | null
  cover_url: string | null
  raw: Record<string, unknown>
  source_listing: string | null
  fetched_at: string
  status: 'new' | 'promoted' | 'skipped' | 'rejected'
  promoted_at: string | null
  promoted_to_game_id: number | null
  notes: string | null
}

export type DicefestRawList = {
  items: DicefestRawGame[]
  total: number
  limit: number
  offset: number
}

export type PromotionCandidate = {
  game_id: number
  title: string
  year: number | null
  score: number
  via: string                         // 'title' | 'alias_ru' | 'alias_en' | ...
  matched_text: string | null
  aliases: CatalogGameAlias[]
  has_satellite_for_provider: boolean // 🚩 уже привязан другой dicefest-page
  year_diff: number | null            // ⚠ ≥3 лет — год не сходится
}

export type PromotionCandidates = {
  raw: DicefestRawGame
  candidates: PromotionCandidate[]
  threshold: number
}

export type PromotionAction = 'link' | 'create' | 'skip' | 'reject'

export type PromotionApplyRequest = {
  action: PromotionAction
  target_game_id?: number
  notes?: string
  performed_by?: string
}

export type PromotionApplyResult = {
  raw_id: number
  log_id: number
  game_id: number | null
  alias_id: number | null
  satellite_id: number | null
  status: string
}

export type PromotionLogEntry = {
  id: number
  provider: string
  raw_id: number
  action: 'link' | 'create' | 'skip' | 'reject' | 'revert'
  game_id: number | null
  alias_id: number | null
  satellite_created: boolean
  performed_by: string | null
  performed_at: string
  reverted_at: string | null
  reverted_by: string | null
  notes: string | null
}

export type PromotionLogList = {
  items: PromotionLogEntry[]
  total: number
  limit: number
  offset: number
}

export type PromotionRevertResult = {
  raw_id: number
  revert_log_id: number
  original_log_id: number
  status_after_revert: string
}

const PROVIDER = 'dicefest'  // пока поддерживается только dicefest

export const fetchPromotionQueue = (
  status: DicefestRawGame['status'] = 'new', limit = 50, offset = 0,
) => {
  const u = new URL(`${BASE}/promotion/${PROVIDER}/queue`, window.location.origin)
  u.searchParams.set('status', status)
  u.searchParams.set('limit', String(limit))
  u.searchParams.set('offset', String(offset))
  return fetch(u.toString().replace(window.location.origin, ''))
    .then(r => json<DicefestRawList>(r))
}

export const fetchPromotionCandidates = (
  rawId: number, threshold = 0.5, limit = 5,
) => {
  const u = new URL(
    `${BASE}/promotion/${PROVIDER}/${rawId}/candidates`,
    window.location.origin,
  )
  u.searchParams.set('threshold', String(threshold))
  u.searchParams.set('limit', String(limit))
  return fetch(u.toString().replace(window.location.origin, ''))
    .then(r => json<PromotionCandidates>(r))
}

export const applyPromotion = (rawId: number, body: PromotionApplyRequest) =>
  fetch(`${BASE}/promotion/${PROVIDER}/${rawId}/apply`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }).then(r => json<PromotionApplyResult>(r))

export const revertPromotion = (logId: number, notes?: string) =>
  fetch(`${BASE}/promotion/log/${logId}/revert`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(notes ? { notes } : {}),
  }).then(r => json<PromotionRevertResult>(r))

export const fetchPromotionLog = (limit = 50, offset = 0) => {
  const u = new URL(`${BASE}/promotion/log`, window.location.origin)
  u.searchParams.set('provider', PROVIDER)
  u.searchParams.set('limit', String(limit))
  u.searchParams.set('offset', String(offset))
  return fetch(u.toString().replace(window.location.origin, ''))
    .then(r => json<PromotionLogList>(r))
}

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

// ── Backup каталога ──────────────────────────────────────────────────────

export type BackupFile = {
  name: string
  size_bytes: number
  modified_at: string
}

export type BackupCreateResponse = {
  status: 'ok'
  file: BackupFile
  log_tail: string
}

export type BackupListResponse = {
  items: BackupFile[]
  dir: string
}

export const createCatalogBackup = () =>
  fetch(`${BASE}/backup`, { method: 'POST' }).then(r => json<BackupCreateResponse>(r))

export const listCatalogBackups = () =>
  fetch(`${BASE}/backups`).then(r => json<BackupListResponse>(r))
