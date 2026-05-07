import type { ProductOut } from '../types/api'

/**
 * Признак наличия товара. Возвращаем `true` при отсутствии явной информации
 * (LavkaIgr и GaGa не отдают availability) — это безопаснее: лучше показать
 * слишком много, чем спрятать товар, который на самом деле в наличии.
 */
export function isInStock(p: ProductOut): boolean {
  if (p.extra?.availability === false) return false
  if (p.extra?.in_stock === false) return false
  return true
}

export function isOnSale(p: ProductOut): boolean {
  return p.extra?.on_sale === true
}

/** Оригинальная цена в рублях, если товар по акции; иначе null. */
export function originalPriceRub(p: ProductOut): number | null {
  const kop = p.extra?.original_price
  if (typeof kop !== 'number' || kop <= 0) return null
  return kop / 100
}
