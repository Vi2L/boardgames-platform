import type { ProductOut } from '../types/api'
import type { HobbyLoyalty, LavkaLoyalty, LoyaltyStore } from '../store/loyalty'
import { isOnSale } from './offer'

/**
 * Какая скидка применилась к строке. `null` — никакая.
 */
export type LoyaltyKind = 'hg-bonus' | 'lavka' | null

export interface AdjustedPrice {
  /** Итоговая цена в рублях с учётом всех скидок. */
  finalRub: number
  /** Базовая цена парсера (без личной скидки). */
  baseRub: number
  /** Применилась ли личная скидка лояльности. */
  applied: boolean
  loyalty: LoyaltyKind
  /** Сэкономлено в рублях за счёт лояльности. Для UI/tooltip. */
  savedRub: number
}

const HG_BONUS_RATE = 0.15
const LAVKA_VK_DON_BONUS = 5

/**
 * Считает скидку HobbyGames для одного товара. Бонусами оплачивается до 15 %
 * стоимости товара и только для товаров без активной акции (on_sale=true
 * нельзя оплатить бонусами по правилам HG).
 *
 * Стратегия «по каждому товару отдельно»: для каждой строки делаем вид, что
 * весь доступный пул бонусов ляжет именно на этот товар. При unlim — всегда
 * полные 15 %.
 */
function applyHobby(p: ProductOut, cfg: HobbyLoyalty): number {
  if (!cfg.enabled) return 0
  if (isOnSale(p)) return 0
  const max = p.price_rub * HG_BONUS_RATE
  if (cfg.bonuses === 'unlim') return max
  return Math.min(cfg.bonuses, max)
}

function applyLavka(p: ProductOut, cfg: LavkaLoyalty): number {
  if (!cfg.enabled) return 0
  const base = clamp(cfg.percent, 0, 10)
  const total = base + (cfg.vkDon ? LAVKA_VK_DON_BONUS : 0)
  return p.price_rub * (total / 100)
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n))
}

/**
 * Применяет конфиг лояльности к списку товаров.
 *
 * Возвращает Map id→AdjustedPrice. Если loyalty выключен глобально — Map
 * пустой, и потребитель должен использовать `p.price_rub` напрямую.
 */
export function applyLoyalty(
  products: ProductOut[],
  cfg: LoyaltyStore,
): Map<number, AdjustedPrice> {
  const out = new Map<number, AdjustedPrice>()
  if (!cfg.enabled) return out

  for (const p of products) {
    let saved = 0
    let kind: LoyaltyKind = null
    if (p.store_slug === 'hobbygames') {
      saved = applyHobby(p, cfg.hobbygames)
      if (saved > 0) kind = 'hg-bonus'
    } else if (p.store_slug === 'lavkaigr') {
      saved = applyLavka(p, cfg.lavkaigr)
      if (saved > 0) kind = 'lavka'
    }
    if (saved <= 0) continue
    out.set(p.id, {
      baseRub: p.price_rub,
      finalRub: Math.round(p.price_rub - saved),
      applied: true,
      loyalty: kind,
      savedRub: Math.round(saved),
    })
  }
  return out
}
