/**
 * InfoTip — небольшая Info-иконка с tooltip.
 *
 * Дизайн: монохромная 12px-иконка `lucide:Info`, при hover показывает
 * абсолютно-позиционированный bubble с пояснением. Использует native
 * `title` attribute как fallback (для screen reader / touch), и CSS
 * `group-hover` для красивого hover-bubble.
 *
 * Без headless-ui / Radix — у нас в проекте их нет. CSS-only решение
 * экономит bundle.
 */
import { Info } from 'lucide-react'
import clsx from 'clsx'

interface InfoTipProps {
  text: string
  side?: 'top' | 'right' | 'bottom' | 'left'
  className?: string
}

export function InfoTip({ text, side = 'top', className }: InfoTipProps) {
  return (
    <span className={clsx('relative inline-flex group align-middle', className)}>
      <Info
        size={12}
        className="text-gray-600 group-hover:text-indigo-400 transition-colors cursor-help"
        aria-label={text}
      />
      <span
        role="tooltip"
        className={clsx(
          'pointer-events-none absolute z-50 hidden group-hover:block',
          'whitespace-pre-line text-[11px] leading-snug',
          'bg-gray-950 border border-indigo-900/50 text-gray-300',
          'px-2.5 py-1.5 rounded shadow-xl shadow-black/60',
          'min-w-[180px] max-w-[280px]',
          side === 'top'    && 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
          side === 'right'  && 'left-full top-1/2 -translate-y-1/2 ml-1.5',
          side === 'bottom' && 'top-full left-1/2 -translate-x-1/2 mt-1.5',
          side === 'left'   && 'right-full top-1/2 -translate-y-1/2 mr-1.5',
        )}
      >
        {text}
      </span>
    </span>
  )
}
