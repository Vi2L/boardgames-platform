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

export type CatalogGameKind = 'base' | 'expansion' | 'promo' | 'accessory'

export type CatalogGame = {
  id: number
  slug: string
  title: string
  // Производное на бэкенде: лучший alias-ru (verified-manual > dicefest >
  // wikidata). Не хранится в БД, а вычисляется при выдаче в /games и /games/{id}.
  title_ru: string | null
  year: number | null
  bgg_id: number | null
  tesera_id: number | null
  // Внешние ID других каталогов (миграция 0006)
  dicefest_id: number | null
  nastolio_id: string | null
  // Тип и связь с базовой игрой (миграция 0006)
  kind: CatalogGameKind
  parent_game_id: number | null
  // Локализация в РФ (миграция 0006)
  ru_publisher: string | null
  ru_release_year: number | null
  is_localized_ru: boolean
  preorder_price: number | null  // копейки
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

/** RU-название если есть, иначе EN. Единая точка выбора отображаемого имени. */
export const getDisplayName = (game: CatalogGame): string =>
  game.title_ru ?? game.title

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
  last_seen_at: string
  match_status: string
  match_score: number | null
  // Нормализованные поля магазина (миграция 0006)
  sku: string | null
  in_stock: boolean | null
  original_price: number | null   // копейки до скидки
  is_preorder: boolean | null
  // True если оффер ранее был привязан и отвязан оператором (миграция 0008)
  was_linked: boolean
  // Matcher v2 диагностика (миграция 0011). Все nullable до первого матча.
  match_tier: number | null       // 0=cache 1=trgm 2=embedding 3=llm
  match_reason: string | null     // 'cache_hit', 'trgm_title_ru', 'vec_confident', ...
  predicted_kind: string | null   // 'base'|'expansion'|'accessory' (от LLM)
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

// ── Drawer-табы: offers / children / promotion-log per game ───────────

export type GameOffersResponse = {
  game_id: number
  items: CatalogOffer[]
  total: number
}

export const fetchGameOffers = (gameId: number) =>
  fetch(`${BASE}/games/${gameId}/offers`).then(r => json<GameOffersResponse>(r))

export type CatalogGameChild = {
  id: number
  slug: string
  title: string
  kind: CatalogGameKind
  year: number | null
  cover_url: string | null
  status: string
}

export type GameChildrenResponse = {
  parent_game_id: number
  items: CatalogGameChild[]
  total: number
}

export const fetchGameChildren = (gameId: number) =>
  fetch(`${BASE}/games/${gameId}/children`).then(r => json<GameChildrenResponse>(r))

export const listCatalogGames = (
  q: string | undefined,
  limit = 20,
  offset = 0,
  options: { no_bgg?: boolean } = {},
) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q) params.set('q', q)
  if (options.no_bgg) params.set('no_bgg', 'true')
  return fetch(`${BASE}/games?${params}`).then(r => json<CatalogGameList>(r))
}

export const fetchMatchingQueue = (
  store: string | undefined,
  limit = 50,
  offset = 0,
  wasLinked?: boolean,
) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (store) params.set('store', store)
  if (wasLinked != null) params.set('was_linked', String(wasLinked))
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

export const unlinkOffer = (offerId: number) =>
  fetch(`${BASE}/matching/${offerId}/unlink`, { method: 'POST' })
    .then(r => json<CatalogOffer>(r))

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
  dicefest_id?: number | null
  nastolio_id?: string | null
  cover_url?: string | null
  description?: string | null
  kind?: CatalogGameKind
  parent_game_id?: number | null
  ru_publisher?: string | null
  ru_release_year?: number | null
  is_localized_ru?: boolean
  preorder_price?: number | null
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

// Все известные типы job'ов. Список расширяется по мере добавления importer'ов;
// т.к. фронт использует поле как фильтр, держим явный union — TS подскажет
// при добавлении нового типа в catalog.
export type ImportJobType =
  | 'bgg'
  | 'bgg-batch'
  | 'bgg-hotness'
  | 'bgg-geeklist'
  | 'bgg-mini-batch'
  | 'bgg-ranks'
  | 'tesera'
  | 'dicefest'
  | 'dicefest-reparse'

export type ImportJob = {
  id: number
  type: ImportJobType
  status: ImportJobStatus
  // payload.trigger ∈ {'manual','scheduled','api'} — для фильтрации по источнику.
  payload: Record<string, unknown> & { trigger?: string }
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

// Re-parse сохранённого raw_html без HTTP к dicefest.ru (PR-4).
export const importDicefestReparse = () =>
  fetch(`${BASE}/import/dicefest/reparse`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: '{}',
  }).then(r => json<ImportJob>(r))

export const fetchImportJob = (id: number) =>
  fetch(`${BASE}/import/jobs/${id}`).then(r => json<ImportJob>(r))

// ── BGG search + batch enrich (этап 1-3) ────────────────────────────────

export type BggSearchHit = {
  bgg_id: number
  title: string
  year: number | null
}

export type BggSearchResponse = {
  query: string
  exact: boolean
  count: number
  items: BggSearchHit[]
}

// POST /catalog/parsers/bgg/search → поиск кандидатов в BGG XML API.
// `exact=true` — фильтр по полному совпадению primary name; default — fuzzy.
export const searchBgg = (
  query: string,
  opts: { exact?: boolean; limit?: number } = {},
) =>
  fetch(`${BASE}/parsers/bgg/search`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      query,
      exact: opts.exact ?? false,
      limit: opts.limit ?? 20,
    }),
  }).then(r => json<BggSearchResponse>(r))

export type BggBatchPayload = {
  // Один из rank_le / all_ranked обязателен (валидация на бэке: 400).
  rank_le?: number
  all_ranked?: boolean
  batch_size?: number      // 1..20
  skip_recent_days?: number  // 0 = форсировать, 30 = пропускать недавние
  limit?: number
  dry_run?: boolean
  rate_limit_sec?: number  // 0..10, default 1.0
}

// POST /catalog/import/bgg/batch → запуск фонового batch-enrich'а.
// Возвращает ImportJob со status='pending'; UI делает polling fetchImportJob(id).
export const importBggBatch = (payload: BggBatchPayload) =>
  fetch(`${BASE}/import/bgg/batch`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => json<ImportJob>(r))

// POST /catalog/import/bgg/ranks — seed из BGG ranks CSV (multipart/form-data).
// topN=null → импортировать все ранкированные игры из файла.
// Возвращает ImportJob; UI делает polling fetchImportJob(id).
export const importBggRanks = (
  file: File,
  topN: number | null,
  dryRun: boolean,
): Promise<ImportJob> => {
  const fd = new FormData()
  fd.append('csv_file', file)
  if (topN !== null) fd.append('top_n', String(topN))
  fd.append('dry_run', String(dryRun))
  return fetch(`${BASE}/import/bgg/ranks`, { method: 'POST', body: fd }).then(
    r => json<ImportJob>(r),
  )
}

// ── Promotion (двухстадийная схема: staging → canonical) ─────────────────

export type ExternalLink = {
  // Машинный тип источника. 'shop' — магазин-партнёр (gaga-games, hobbygames…).
  // 'other' зарезервировано на случай новых доменов.
  kind: 'bgg' | 'tesera' | 'nastolio' | 'shop' | 'other'
  url: string
  label: string
  external_id?: string             // BGG: '447174'; Tesera: 'pandemic'
}

export type DicefestRawGame = {
  id: number
  slug: string
  page_url: string
  title_ru: string | null            // RU из «RU / EN» split (PR-4)
  title_en: string | null            // EN из «RU / EN» split, иначе null
  publisher: string | null           // «Издатель в РФ» — UI label
  release_status: string | null      // data-status code, например 'v-prodazhe'
  description: string | null
  cover_url: string | null
  preorder_price: number | null      // копейки (1 ₽ = 100); null если не указана
  external_links: ExternalLink[]     // BGG / Tesera / Nastolio / магазины
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

// Развёрнутые детали одной записи журнала. Возвращает GET /promotion/log/{id}/details.
// Связанные сущности подгружены по id из самой записи и могут быть null,
// если ссылка пустая или объект был удалён (например, alias после revert).
export type PromotionLogRawSummary = {
  id: number
  slug: string
  title_ru: string | null
  title_en: string | null
  publisher: string | null
  page_url: string
  preorder_price: number | null  // копейки
  fetched_at: string
  status: string
}

export type PromotionLogGameSummary = {
  id: number
  slug: string
  title: string
  year: number | null
  status: string
}

export type PromotionLogAliasSummary = {
  id: number
  game_id: number
  alias: string
  alias_norm: string
  source: string
  language: string | null
  verified: boolean
}

export type PromotionLogDetails = {
  entry: PromotionLogEntry
  raw_game: PromotionLogRawSummary | null
  game: PromotionLogGameSummary | null
  alias: PromotionLogAliasSummary | null
  reverted_by_entry_id: number | null
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

// Получить одну raw-запись dicefest по id. Используется в GameDetailDrawer
// для side-by-side сравнения canonical поля игры с тем, что лежит в staging.
export const fetchPromotionDicefestRaw = (rawId: number) =>
  fetch(`${BASE}/promotion/${PROVIDER}/${rawId}`)
    .then(r => json<DicefestRawGame>(r))

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

// Журнал промоушенов, отфильтрованный по конкретной игре — для drawer-таба
// «Аудит». Без provider, чтобы при подключении новых источников все
// действия по этой game автоматически попали сюда.
export const fetchPromotionLogForGame = (gameId: number, limit = 20) => {
  const u = new URL(`${BASE}/promotion/log`, window.location.origin)
  u.searchParams.set('game_id', String(gameId))
  u.searchParams.set('limit', String(limit))
  return fetch(u.toString().replace(window.location.origin, ''))
    .then(r => json<PromotionLogList>(r))
}

export const fetchPromotionLogDetails = (logId: number) =>
  fetch(`${BASE}/promotion/log/${logId}/details`)
    .then(r => json<PromotionLogDetails>(r))

// ── PR-5: batch auto-link ────────────────────────────────────────────────

export type BatchLinkRequest = {
  threshold?: number          // default 0.95
  max_items?: number          // default 100
  dry_run?: boolean           // default true (UX «preview сначала»)
  skip_with_satellite?: boolean  // default true
}

export type BatchLinkItemPreview = {
  raw_id: number
  slug: string
  raw_title: string | null
  game_id: number
  game_title: string
  score: number
  via: string
}

export type BatchLinkSkipped = {
  raw_id: number
  slug: string
  // 'low_score' | 'already_linked' | 'no_candidates' | 'promote_failed:N'
  reason: string
  top_score: number | null
}

export type BatchLinkResult = {
  scanned: number
  linked: number              // 0 при dry_run
  would_link: number
  skipped: BatchLinkSkipped[]
  items: BatchLinkItemPreview[]   // топ-50 для preview
  dry_run: boolean
}

export const batchAutoLinkPromotion = (body: BatchLinkRequest) =>
  fetch(`${BASE}/promotion/${PROVIDER}/batch-link`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }).then(r => json<BatchLinkResult>(r))

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


// ── Matcher v2: ML status + match_log + warmup ───────────────────────────

export type MlStatus = {
  models: Record<string, boolean>          // 'bge-m3' → true
  last_check_at: string | null
  last_success_at: string | null
  failures: Record<string, number>
  queue: Record<string, number>            // 'pending', 'processing', 'done', ...
}

export const fetchMlStatus = () =>
  fetch(`${BASE}/matching/ml-status`).then(r => json<MlStatus>(r))


export type MatchLogEntry = {
  id: number
  offer_id: number
  prev_game_id: number | null
  new_game_id: number | null
  prev_status: string | null
  new_status: string
  action: string                            // 'auto_t0'|'auto_t1'|'auto_t2'|'auto_t3'|'manual'|...
  tier: number | null                       // 0..3
  score: number | null
  reason: string | null
  batch_id: string | null
  alias_created_id: number | null
  performed_by: string | null
  performed_at: string
  reverted_at: string | null
  reverted_by: string | null
  // Контекст из JOIN (упрощает UI):
  title_raw: string | null
  store_slug: string | null
  new_game_title: string | null
  prev_game_title: string | null
}

export type MatchLogPage = {
  items: MatchLogEntry[]
  total: number
  limit: number
  offset: number
}

export type MatchLogFilters = {
  offer_id?: number
  action?: string
  tier?: number
  performed_by?: string
  only_active?: boolean
  limit?: number
  offset?: number
}

export const fetchMatchLog = (filters: MatchLogFilters = {}) => {
  const sp = new URLSearchParams()
  if (filters.offer_id != null) sp.set('offer_id', String(filters.offer_id))
  if (filters.action) sp.set('action', filters.action)
  if (filters.tier != null) sp.set('tier', String(filters.tier))
  if (filters.performed_by) sp.set('performed_by', filters.performed_by)
  if (filters.only_active) sp.set('only_active', 'true')
  sp.set('limit', String(filters.limit ?? 50))
  sp.set('offset', String(filters.offset ?? 0))
  return fetch(`${BASE}/matching/log?${sp}`).then(r => json<MatchLogPage>(r))
}

export const revertMatchLog = (logId: number, deleteAlias = false) =>
  fetch(`${BASE}/matching/log/${logId}/revert`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ delete_alias: deleteAlias }),
  }).then(r => json<{ log_id: number; restored_status: string; revert_log_id: number }>(r))

export const bulkRevertMatchLog = (logIds: number[], deleteAlias = false) =>
  fetch(`${BASE}/matching/log/bulk-revert`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ log_ids: logIds, delete_alias: deleteAlias }),
  }).then(r => json<{ requested: number; reverted: number; skipped: number }>(r))

export const batchRevertMatchLog = (batchId: string, deleteAlias = false) =>
  fetch(`${BASE}/matching/log/batch-revert`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ batch_id: batchId, delete_alias: deleteAlias }),
  }).then(r => json<{ requested: number; reverted: number; batch_id: string }>(r))

/**
 * Эквивалент Python normalize_title из catalog/matching/v2/domain.py:
 * NFKD-разложение → удалить combining marks → lowercase → trim.
 *
 * Используется UI для построения title_norm перед вызовом
 * DELETE /matching/decisions/{title_norm}. Если эквивалентность с
 * backend'ом сломается (например, добавят unaccent ß→ss) — caller
 * получит deleted=0 (запись осталась) и должен дёрнуть bulk-вариант.
 */
export function normalizeTitle(raw: string): string {
  return raw
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .trim()
}

export const invalidateDecision = (titleNorm: string) =>
  fetch(`${BASE}/matching/decisions/${encodeURIComponent(titleNorm)}`, {
    method: 'DELETE',
  }).then(r => json<{ title_norm: string; deleted: number }>(r))

export const invalidateDecisionsBulk = (
  filters: { title_contains?: string; only_negative?: boolean },
) =>
  fetch(`${BASE}/matching/decisions/invalidate`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(filters),
  }).then(r => json<{ deleted: number; filters: Record<string, unknown> }>(r))


export type WarmupParams = {
  batch_size?: number
  limit?: number | null
  only_games?: boolean
  only_aliases?: boolean
}

export const startWarmupEmbeddings = (params: WarmupParams = {}) =>
  fetch(`${BASE}/matching/warmup-embeddings`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(params),
  }).then(r => json<{ job_id: number; status: string }>(r))
