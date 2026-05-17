/**
 * Frontend-агрегация результатов поиска по канонической игре.
 *
 * Backend (`/api/search`) пока возвращает плоский список `ProductOut[]`
 * без `game_id` (см. `pages/05-search.md` § Backend dependency — fallback
 * B). Поэтому фронт делает greedy-clustering по `titleSimilarity`:
 *   - Для каждого product ищем существующую группу с centroid Jaccard ≥ T;
 *   - если нашли — добавляем в неё; иначе создаём новую группу (canonical
 *     title = title первого product'а).
 *
 * После прохода группы с одним product'ом считаем «не сматчёными» —
 * собираем в отдельный массив `orphans` (handoff §05 — секция
 * «Не сматчено»). Идея: если ни один другой магазин этот товар не
 * показал — высокая вероятность что catalog его не привязал.
 *
 * **Когда backend выкатит /search/grouped** с явным `game_id` —
 * этот файл будет заменён прямой группировкой по id (см. var. A в спеке).
 */
import type { ProductOut } from '../types/api'
import { titleSimilarity, tokenize } from './similarity'
import { isInStock, isOnSale } from './offer'

/** Порог Jaccard для merge'а в существующую группу. */
const SIMILARITY_THRESHOLD = 0.6

export interface ProductGroup {
  /** Псевдо-id (-1 если нет game_id). Для key'я списка используем canonical_title. */
  id: number
  canonicalTitle: string
  /** Tokens первого product'а — для greedy-сравнения с последующими. */
  centroidTokens: Set<string>
  offers: ProductOut[]
  /** Минимальная цена среди offers in_stock. */
  minPrice: number | null
  /** Магазины с in_stock=true. */
  inStockCount: number
  /** Всего магазинов в группе. */
  totalStores: number
  /** Список slug магазинов с хотя бы одним оффером. */
  storeSlugs: string[]
  /** Самая ранняя цена — для будущего Δ%. */
  hasSale: boolean
}

export interface GroupedResults {
  groups: ProductGroup[]
  orphans: ProductOut[]
  /** Сводка: общее число офферов и групп. */
  stats: {
    totalOffers: number
    totalGroups: number
    totalOrphans: number
  }
}

/**
 * Greedy-clustering: O(n×k) где k — кол-во уже найденных групп. На 100-500
 * results это ~50K сравнений в worst case — приемлемо для UI (≤10ms).
 */
export function groupProducts(products: ProductOut[]): GroupedResults {
  const groups: ProductGroup[] = []

  for (const p of products) {
    const tokens = tokenize(p.title)
    if (tokens.size === 0) {
      // Пустой токенный набор — добавим как «новую группу из 1»; позже
      // улетит в orphans.
      groups.push(createGroup(p, tokens))
      continue
    }

    // Ищем лучшую существующую группу по similarity.
    let bestIdx = -1
    let bestScore = SIMILARITY_THRESHOLD - 0.0001
    for (let i = 0; i < groups.length; i++) {
      const score = jaccardSets(groups[i].centroidTokens, tokens)
      if (score > bestScore) {
        bestScore = score
        bestIdx = i
      }
    }

    if (bestIdx >= 0) {
      addToGroup(groups[bestIdx], p)
    } else {
      groups.push(createGroup(p, tokens))
    }
  }

  // Финализация: orphans = группы с 1 оффером (вряд ли каноническая игра).
  const orphans: ProductOut[] = []
  const realGroups: ProductGroup[] = []
  for (const g of groups) {
    if (g.offers.length <= 1) {
      orphans.push(...g.offers)
    } else {
      // Дополнительно подсчитываем in_stock и min_price на финале.
      finalizeGroup(g)
      realGroups.push(g)
    }
  }

  // Сортируем группы по убыванию числа магазинов (более «канонические» сверху).
  realGroups.sort((a, b) => b.totalStores - a.totalStores)

  return {
    groups: realGroups,
    orphans,
    stats: {
      totalOffers: products.length,
      totalGroups: realGroups.length,
      totalOrphans: orphans.length,
    },
  }
}

// ── Inline helpers ──────────────────────────────────────────────────────────

function createGroup(p: ProductOut, tokens: Set<string>): ProductGroup {
  return {
    id: -1,
    canonicalTitle: p.title,
    centroidTokens: tokens,
    offers: [p],
    minPrice: isInStock(p) ? p.price_rub : null,
    inStockCount: isInStock(p) ? 1 : 0,
    totalStores: 1,
    storeSlugs: [p.store_slug],
    hasSale: isOnSale(p),
  }
}

function addToGroup(g: ProductGroup, p: ProductOut): void {
  g.offers.push(p)
  if (!g.storeSlugs.includes(p.store_slug)) {
    g.storeSlugs.push(p.store_slug)
    g.totalStores += 1
  }
  if (isInStock(p)) {
    g.inStockCount += 1
    if (g.minPrice == null || p.price_rub < g.minPrice) g.minPrice = p.price_rub
  }
  if (isOnSale(p)) g.hasSale = true
}

function finalizeGroup(g: ProductGroup): void {
  // Никаких побочных вычислений — пока. Резерв под extension (Δ%, spread).
  void g
}

function jaccardSets(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0
  let intersect = 0
  for (const t of a) if (b.has(t)) intersect += 1
  const union = a.size + b.size - intersect
  return union === 0 ? 0 : intersect / union
}

/** Для совместимости / тестов — выставляем сторонним кодом. */
export { titleSimilarity }
