export interface StoreOut {
  slug: string
  name: string
  base_url: string
}

/**
 * Известные поля extra. У разных магазинов разный набор:
 * - HobbyGames:  gallery, rules, category, sku, complexity, availability
 * - Лавка игр:   gallery, tags, rules, composition, language, category, complexity
 * - GaGa:        gallery, rating, review_count, ranking, offline_price,
 *                rules, composition, dimensions, weight
 * - CrowdGames:  in_stock, language
 *
 * Все поля опциональные. `[k: string]: unknown` оставлен на случай новых
 * магазинов / парсеров, чтобы не падать на типизации, но при этом IDE
 * подсказывает известные имена.
 */
export interface ProductRule {
  url: string
  name: string
}

export interface ProductExtra {
  gallery?: string[]
  rules?: Array<string | ProductRule>
  tags?: string[]
  category?: string
  language?: string
  complexity?: string
  composition?: string[] | string
  rating?: string
  review_count?: string
  ranking?: string
  offline_price?: number       // копейки
  dimensions?: string
  weight?: string
  sku?: string
  availability?: boolean        // hobbygames: true = в наличии
  in_stock?: boolean            // crowdgames: true = в наличии
  on_sale?: boolean             // hobbygames: товар по акционной цене
  original_price?: number       // hobbygames: оригинальная цена в копейках (если on_sale)
  [k: string]: unknown
}

export interface ProductOut {
  id: number
  store_slug: string
  title: string
  price_rub: number             // рубли (float) — уже в рублях из API
  url: string
  image_url: string | null
  image_url_hd: string | null   // HD-изображение
  description: string | null
  players: string | null        // "2-5" или null (HobbyGames не даёт)
  age_min: number | null
  playtime: string | null       // "30-45 мин."
  rules_url: string | null
  fetched_at: string
  extra: ProductExtra
}

export interface PricePointOut {
  price: number       // копейки
  price_rub: number   // рубли
  fetched_at: string
}

export interface PriceDeltaOut {
  product_id: number
  prev_price_rub: number | null
  curr_price_rub: number | null
  delta_pct: number | null      // положительная — рост, отрицательная — падение
  days_between: number | null
}

export interface PriceStatsOut {
  product_id: number
  min_30d_rub: number | null
  min_all_rub: number | null
  points_30d: number
  points_all: number
}

export interface ParserStatsOut {
  slug: string
  name: string
  base_url: string
  available: boolean | null
}

export interface ProductDetailOut extends ProductOut {
  observations: PricePointOut[]
}

// ── SSE types ──────────────────────────────────────────────────────────────

export type StoreStatus = 'pending' | 'running' | 'done' | 'error' | 'cache'

export interface StoreProgress {
  slug: string
  name: string
  status: StoreStatus
  count?: number
  elapsed_ms?: number
  error?: string
}

// HttpLog используется в HttpLogEntry и ParserCard для отображения запросов к parsers API
export interface HttpLog {
  id: number
  slug: string
  type: 'request' | 'response'
  method?: string
  url?: string
  status?: number
  size_bytes?: number
  elapsed_ms?: number
  headers: Record<string, string>
  body_preview?: string
  timestamp: number
}

export interface ApiLog {
  id: number
  type: 'request' | 'response' | 'error'
  // request
  url?: string
  q?: string
  stores?: string[] | null
  // response
  status?: number
  elapsed_ms?: number
  source?: string
  products_count?: number
  error_count?: number
  // error
  error?: string
  timestamp: number
}

// ── Health ────────────────────────────────────────────────────────────────
export interface HealthOut {
  app: 'ok'
  parsers_url: string
  parsers_api: 'ok' | 'unreachable'
  error?: string
}

export interface HealthAllResponse {
  app: 'ok'
  checked_at: string
  parsers: {
    status: string
    url: string
    error?: string
    meta?: {
      size_bytes?: number | null
      product_count?: number | null
      observation_count?: number | null
      newest_observation?: string | null
    } | null
  }
  catalog: {
    status: string
    url: string
    error?: string
    total_games?: number | null
    unmatched_offers?: number | null
    unmatched_good?: number | null
  }
}

// ── DatabasePage / Stats ────────────────────────────────────────────────
export interface ProductsPage {
  items: ProductOut[]
  total: number
  page: number
  page_size: number
}

export interface SearchLogOut {
  id: number
  query: string
  stores: string | null
  source: string | null
  total_ms: number | null
  products_count: number
  error_count: number
  errors_json: string
  created_at: string
}

export interface SearchesPage {
  items: SearchLogOut[]
  total: number
  page: number
  page_size: number
}

/** parsers /api/stats/stores — здоровье парсеров за последние 24ч. */
export interface StoreHealthEntry {
  store_slug: string
  total_calls_24h: number
  success_count_24h: number
  /** Успешность в процентах (0..100), не fraction. */
  success_rate_24h: number | null
  /** Среднее время ответа в мс. */
  avg_response_ms: number | null
  last_seen: string | null
  last_success: string | null
  last_error: string | null
  [k: string]: unknown
}

// ── Snapshots / Suites / Favorites (фаза 4) ────────────────────────────

export interface SnapshotMeta {
  id: number
  name: string | null
  query: string
  stores: string | null
  limit_n: number
  refresh: boolean
  source: string | null
  total_ms: number | null
  error_count: number
  summary: {
    ms_per_product?: number | null
    error_rate?: number
    failed?: boolean
    products_count?: number
  }
  created_at: string
}

export interface SnapshotsPage {
  items: SnapshotMeta[]
  total: number
  page: number
  page_size: number
}

/** Полный snapshot с products (для diff/просмотра). */
export interface SnapshotFull extends SnapshotMeta {
  errors: Record<string, string>
  products: ProductOut[]
}

export type DiffStatus = 'added' | 'removed' | 'changed'

export type DiffCategory = 'price' | 'lost' | 'gained' | 'raw' | 'field'

export interface DiffField {
  a: unknown
  b: unknown
  delta_pct?: number
  category?: DiffCategory
}

export interface DiffProductItem {
  key: string
  status: DiffStatus
  a?: ProductOut
  b?: ProductOut
  fields?: Record<string, DiffField>
}

export interface DiffResult {
  summary: {
    a_count: number
    b_count: number
    added: number
    removed: number
    changed: number
    same: number
    ms_a?: number | null
    ms_b?: number | null
    categories?: Record<DiffCategory, number>
  }
  products: DiffProductItem[]
  meta: {
    a: { id: number; query: string; created_at: string }
    b: { id: number; query: string; created_at: string }
  }
}

export interface SuiteQuery {
  q: string
  stores?: string[] | null
  limit?: number | null
  refresh?: boolean
}

export interface SuiteOut {
  id: number
  name: string
  description: string | null
  queries: SuiteQuery[]
  created_at: string
  updated_at: string
}

export interface SuiteRunMeta {
  id: number
  suite_id: number
  started_at: string
  finished_at: string | null
  summary: {
    total?: number
    passed?: number
    failed?: number
    ms_total?: number
    ms_per_query?: number
    source_breakdown?: Record<string, number>
  }
}

export interface SuiteRunItem {
  id: number
  query: string
  snapshot_id: number | null
  ms: number | null
  status: 'ok' | 'partial' | 'error'
  error: string | null
}

export interface FavoriteOut {
  id: number
  query: string
  stores: string | null
  limit_n: number | null
  refresh: boolean
  created_at: string
  show_out_of_stock?: boolean | null
  loyalty?: Record<string, unknown> | null
}

// ── Debug / Live Test ────────────────────────────────────────────────────

/**
 * Сырой продукт из debug-парсера. В отличие от ProductOut:
 * - нет id (товар не записан в БД);
 * - есть price в копейках для отладки разбора;
 * - external_id строковый (магазинный id, не наш PK).
 */
export interface DebugProduct {
  store_slug: string
  external_id: string | number
  title: string
  price: number          // копейки — сырое значение из парсера
  price_rub: number
  url: string
  image_url: string | null
  image_url_hd: string | null
  description: string | null
  players: string | null
  age_min: number | null
  playtime: string | null
  rules_url: string | null
  raw: Record<string, unknown>
}

/** Метрики ParserMetrics (asdict) — структура зависит от parsers, держим открытой. */
export interface DebugMetrics {
  search_ms?: number | null
  enrich_ms?: number | null
  http_requests?: number | null
  result_after_enrich?: number | null
  [k: string]: unknown
}

export interface DebugStoreResult {
  products: DebugProduct[]
  count: number
  duration_ms: number
  metrics: DebugMetrics | null
  error: string | null
}

export interface DebugParseResponse {
  query: string
  results: Record<string, DebugStoreResult>
}

export interface DebugFeatures {
  raw_snapshots: boolean
  [k: string]: unknown
}

export interface ParserSnapshotMeta {
  id: number
  store_slug: string
  query: string | null
  url: string | null
  method: string | null
  status_code: number | null
  encoding: string | null
  content_type: string | null
  body_size: number | null
  truncated: number | boolean | null
  duration_ms: number | null
  ts: string
  kind: string
}

export interface ParserSnapshotFull extends ParserSnapshotMeta {
  body_text: string
}

/**
 * Один cache↔live diff per-store. Ключ для diff — url продукта.
 *
 * - only_cache / only_live — массивы url, которых нет в другой стороне.
 * - changed — записи, где тот же url, но title/price_rub отличается.
 * - same_count — сколько url'ов идентичны (не показываем поштучно).
 */
export interface CompareStoreResult {
  cache: {
    count: number
    error: string | null
    products: ProductOut[]
  }
  live: {
    count: number
    error: string | null
    duration_ms: number | null
    metrics: DebugMetrics | null
    products: DebugProduct[]
  }
  diff: {
    only_cache: string[]
    only_live: string[]
    changed: Array<{
      url: string
      cache: { title: string | null; price_rub: number | null }
      live: { title: string | null; price_rub: number | null }
    }>
    same_count: number
  }
}

export interface CompareResponse {
  query: string
  cache_source: string | null
  results: Record<string, CompareStoreResult>
  errors: { cache: string | null; live: string | null }
}

/** Поле dataclass ParsedProduct (см. /api/debug/contract). */
export interface ContractField {
  name: string
  type: string
  required: boolean
  default: unknown
}

export interface ContractResponse {
  model: string
  module: string
  fields: ContractField[]
}

/** Покрытие опциональных полей per-store (heatmap data quality). */
export interface FieldCoverageRow {
  store_slug: string
  total: number
  coverage: Record<string, number>  // field -> percent (0..100)
}

/** Результат /api/debug/fetch-url: пробный GET через парсерский стек. */
export interface DebugFetchUrlResult {
  status_code: number
  encoding: string
  content_type: string | null
  body_size: number
  duration_ms: number
  body_text: string
  truncated: boolean
  final_url: string
  headers: Record<string, string>
  history: Array<{ status: number; url: string }>
}

/** Маркер недоступности parsers — приходит вместо реального ответа. */
export interface UnavailableMarker {
  _unavailable: true
  _error: string
}

export type StoreStatsResponse = StoreHealthEntry[] | UnavailableMarker
export type SummaryStatsResponse = Record<string, unknown> | UnavailableMarker
