import { Sparkles } from 'lucide-react'
import clsx from 'clsx'
import type { LoyaltyKind } from '../../lib/loyalty'

interface Props {
  kind: LoyaltyKind
  /** Сэкономлено по этой строке в рублях. Для tooltip. */
  savedRub: number
}

const LABELS: Record<Exclude<LoyaltyKind, null>, string> = {
  'hg-bonus': 'HG-бонус',
  'lavka': 'Лавка %',
}

const COLORS: Record<Exclude<LoyaltyKind, null>, string> = {
  'hg-bonus': 'bg-indigo-900/60 text-indigo-200 border-indigo-800/60',
  'lavka': 'bg-sky-900/60 text-sky-200 border-sky-800/60',
}

export function LoyaltyBadge({ kind, savedRub }: Props) {
  if (!kind) return null
  return (
    <span
      title={`Личная скидка применена · сэкономлено ${savedRub.toLocaleString('ru-RU')} ₽`}
      className={clsx(
        'inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium border',
        COLORS[kind],
      )}
    >
      <Sparkles size={9} /> {LABELS[kind]}
    </span>
  )
}
