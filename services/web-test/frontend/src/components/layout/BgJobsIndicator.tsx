/**
 * BgJobsIndicator — счётчик активных background-job'ов в Topbar.
 *
 * MVP-имплементация: показывает count из агрегатора `useBgJobs` (TanStack
 * Query keys, без отдельного polling-слоя). Сейчас читает из `useBgJobsStub`
 * → 0; реальная агрегация — в PR 3+ когда мигрируют страницы и появится
 * useBgJobs() хук.
 *
 * При count > 0: pulse-точка + count. Click открывает dropdown (потом).
 */
import { useMemo } from 'react'
import { Activity, ChevronDown } from 'lucide-react'
import clsx from 'clsx'

import { IconButton } from '../ui/IconButton'
import { Tooltip } from '../ui/Tooltip'

interface BgJobsIndicatorProps {
  /** Counter; 0 → ничего не рисуем. */
  count?: number
  onClick?: () => void
}

export function BgJobsIndicator({ count = 0, onClick }: BgJobsIndicatorProps) {
  const hasActive = count > 0
  const label = useMemo(() => (count === 1 ? '1 job' : `${count} jobs`), [count])

  if (!hasActive) {
    // Когда нет активных — компактный idle-индикатор. Не пустота, не «секрет».
    return (
      <Tooltip content="Нет активных background-job'ов">
        <IconButton
          icon={Activity}
          size="sm"
          variant="ghost"
          aria-label="Background jobs (idle)"
          onClick={onClick}
        />
      </Tooltip>
    )
  }

  return (
    <Tooltip content={`${label} в работе`}>
      <button
        type="button"
        onClick={onClick}
        className={clsx(
          'inline-flex items-center gap-1.5 h-7 px-2 rounded',
          'bg-amber-500/15 text-amber-300 border border-amber-500/30',
          'hover:bg-amber-500/25 transition-colors',
          'text-xs font-mono',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
        )}
      >
        <span className="relative flex">
          <span className="absolute inset-0 rounded-full bg-amber-400 animate-ping opacity-60" />
          <span className="relative w-1.5 h-1.5 rounded-full bg-amber-400" />
        </span>
        <span className="tabular-nums">{label}</span>
        <ChevronDown size={11} className="text-amber-400/60" />
      </button>
    </Tooltip>
  )
}
