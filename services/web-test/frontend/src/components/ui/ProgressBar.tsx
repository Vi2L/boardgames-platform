/**
 * ProgressBar — индикатор прогресса (job, import, batch).
 *
 * Высота 6px (h-1.5) — компактно. Tone из status-system (info по умолчанию,
 * ok при 100%, danger при failed). Опциональный label справа в font-mono.
 */
import clsx from 'clsx'
import { toneClasses, type StatusTone } from '../../lib/design-tokens'

export interface ProgressBarProps {
  /** 0..100. Clamped. */
  value: number
  tone?: StatusTone
  withLabel?: boolean
  className?: string
  /** Кастомный лейбл вместо `42%`. */
  label?: string
  /** Indeterminate-режим (loop animation) для неизвестного прогресса. */
  indeterminate?: boolean
}

export function ProgressBar({
  value, tone = 'info', withLabel = false, label, indeterminate = false, className,
}: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, value))
  const cls = toneClasses[tone]
  return (
    <div className={clsx('flex items-center gap-2', className)}>
      <div className={clsx(
        'flex-1 h-1.5 rounded-full overflow-hidden',
        'bg-zinc-800/80',
      )}>
        {indeterminate ? (
          <div className={clsx('h-full w-1/3 rounded-full animate-pulse', cls.dot)} />
        ) : (
          <div
            className={clsx('h-full rounded-full transition-[width] duration-300', cls.dot)}
            style={{ width: `${clamped}%` }}
            role="progressbar"
            aria-valuenow={clamped}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        )}
      </div>
      {withLabel && (
        <span className="text-xxs font-mono tabular-nums text-zinc-400 min-w-[36px] text-right">
          {label ?? `${Math.round(clamped)}%`}
        </span>
      )}
    </div>
  )
}
