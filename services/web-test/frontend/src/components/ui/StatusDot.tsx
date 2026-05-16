/**
 * StatusDot — отдельный indicator-dot без текста.
 *
 * Inline в строках текста, в health-карточках, как префикс к лейблам ML/CB.
 * Опционально pulse (`animated`) — для live-состояний типа `processing`.
 *
 * Для open-state (Circuit Breaker) НЕ пульсируем по умолчанию —
 * static red = alert (см. status-system.md → Что не делать).
 */
import clsx from 'clsx'
import type { HTMLAttributes } from 'react'
import { statusSystem, toneClasses, type StatusKey, type StatusTone } from '../../lib/design-tokens'

export interface StatusDotProps extends HTMLAttributes<HTMLSpanElement> {
  status?: StatusKey
  tone?: StatusTone
  /** Размер точки в пикселях; default 8px (`w-2 h-2`). */
  size?: number
  /** Pulse-анимация для «живых» состояний (processing, half_open). */
  animated?: boolean
}

export function StatusDot({
  status, tone, size = 8, animated = false, className, ...rest
}: StatusDotProps) {
  const resolvedTone: StatusTone = tone ?? (status ? statusSystem[status].tone : 'neutral')
  const cls = toneClasses[resolvedTone]
  const style = { width: size, height: size }

  return (
    <span
      className={clsx('relative inline-flex flex-shrink-0', className)}
      style={style}
      {...rest}
    >
      {animated && (
        <span
          className={clsx('absolute inset-0 rounded-full opacity-60 animate-ping', cls.dot)}
        />
      )}
      <span
        className={clsx('relative w-full h-full rounded-full', cls.dot)}
      />
    </span>
  )
}
