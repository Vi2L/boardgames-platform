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
  availability?: boolean        // hobbygames
  in_stock?: boolean            // crowdgames
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
