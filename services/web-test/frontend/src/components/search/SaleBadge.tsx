import { Tag } from 'lucide-react'

interface Props {
  /** Оригинальная цена в рублях. */
  originalRub: number | null
  /** Текущая цена в рублях — для расчёта % скидки. */
  currentRub: number
}

/**
 * Бейдж «sale» с tooltip о % скидки и оригинальной цене.
 * Парсер HobbyGames проставляет on_sale + original_price; для остальных
 * магазинов параметр недоступен.
 */
export function SaleBadge({ originalRub, currentRub }: Props) {
  const pct = originalRub && originalRub > currentRub
    ? Math.round((1 - currentRub / originalRub) * 100)
    : null
  const tooltip = originalRub != null
    ? `Было ${originalRub.toLocaleString('ru-RU')} ₽${pct ? ` · −${pct}%` : ''}`
    : 'Акционная цена'
  return (
    <span
      title={tooltip}
      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-red-900/60 text-red-300 border border-red-800/60"
    >
      <Tag size={9} /> sale
    </span>
  )
}
