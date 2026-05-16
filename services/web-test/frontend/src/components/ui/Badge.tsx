/**
 * Badge — единая визуальная кодировка статуса.
 *
 * Связь с `tokens/status-system.md`: каждый StatusKey мапится на tone, tone
 * мапится на toneClasses (bg/text/border/dot). Без этого UI рискует расходом
 * («pending зелёный здесь, серый там»).
 *
 * Использование:
 *   <Badge status="auto" />                  → ● auto (emerald)
 *   <Badge status="unmatched" />             → ● unmatched (amber)
 *   <Badge tone="info">manual</Badge>        → custom label, явный tone
 *   <Badge status="processing">enriching</Badge>  → label override, tone из status
 */
import type { HTMLAttributes, ReactNode } from 'react'
import clsx from 'clsx'
import { statusSystem, toneClasses, type StatusKey, type StatusTone } from '../../lib/design-tokens'

export interface BadgeProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  /** Из status-system.md — основной путь. Tone и label выводятся автоматом. */
  status?: StatusKey
  /** Если нет status — задать tone вручную. */
  tone?: StatusTone
  /** Если задан, переопределяет лейбл из statusSystem. Если status не задан, обязателен. */
  children?: ReactNode
  size?: 'xs' | 'sm'
  /** Скрыть dot — например, в plain-tag варианте. */
  dot?: boolean
}

export function Badge({
  status, tone, children, size = 'xs', dot = true, className, ...rest
}: BadgeProps) {
  const resolvedTone: StatusTone = tone ?? (status ? statusSystem[status].tone : 'neutral')
  const cls = toneClasses[resolvedTone]
  const label = children ?? (status ? statusSystem[status].label : null)

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 border rounded',
        size === 'xs' ? 'h-4 px-1.5 text-xxs' : 'h-[18px] px-1.5 text-xs',
        'font-mono uppercase tracking-wider',
        cls.bg, cls.text, cls.border,
        className,
      )}
      {...rest}
    >
      {dot && (
        <span className={clsx('w-1.5 h-1.5 rounded-full', cls.dot)} />
      )}
      {label}
    </span>
  )
}
