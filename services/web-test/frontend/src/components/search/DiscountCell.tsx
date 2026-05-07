import type { ProductOut } from '../../types/api'
import type { AdjustedPrice } from '../../lib/loyalty'
import { isOnSale, originalPriceRub } from '../../lib/offer'
import { SaleBadge } from './SaleBadge'
import { LoyaltyBadge } from './LoyaltyBadge'

interface Props {
  p: ProductOut
  /** Скидка лояльности по этому товару, если применилась. */
  adjusted?: AdjustedPrice
}

function formatPrice(rub: number): string {
  return `${rub.toLocaleString('ru-RU', { minimumFractionDigits: 0 })} ₽`
}

/**
 * Узкая ячейка под колонкой «♢»: бейджи скидок (sale + лояльность) и
 * зачёркнутая базовая цена, когда применилась личная скидка лояльности.
 *
 * Зачёркнутую цену показываем только при applied loyalty (магазинная sale
 * не меняет p.price_rub — её оригинал уже отображается в tooltip-е sale-бейджа).
 */
export function DiscountCell({ p, adjusted }: Props) {
  const sale = isOnSale(p)
  const loyalty = adjusted?.applied ? adjusted.loyalty : null
  if (!sale && !loyalty) return null
  return (
    <div className="flex flex-col items-start gap-0.5">
      <div className="flex items-center gap-1 flex-wrap">
        {sale && <SaleBadge originalRub={originalPriceRub(p)} currentRub={p.price_rub} />}
        {loyalty && <LoyaltyBadge kind={loyalty} savedRub={adjusted!.savedRub} />}
      </div>
      {loyalty && (
        <s className="text-[10px] text-gray-500">{formatPrice(adjusted!.baseRub)}</s>
      )}
    </div>
  )
}
