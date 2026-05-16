/**
 * Tag — semantic, не-status визуальная метка.
 *
 * Для случаев когда нужен «не-state» tag: тип источника, метка магазина,
 * kind. tone задаётся явно (нет дефолтного маппинга через statusSystem,
 * это сознательное отличие от Badge).
 *
 * Если нужен store-tag — лучше передавать готовые `tagClass` из
 * `tokens.stores`.
 */
import type { HTMLAttributes } from 'react'
import clsx from 'clsx'
import { toneClasses, type StatusTone } from '../../lib/design-tokens'

export interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: StatusTone
  size?: 'xs' | 'sm'
  /** font-mono (например для slug'ов). */
  mono?: boolean
}

export function Tag({
  tone = 'neutral', size = 'xs', mono = false, className, children, ...rest
}: TagProps) {
  const cls = toneClasses[tone]
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 border rounded',
        size === 'xs' ? 'h-4 px-1.5 text-xxs' : 'h-[18px] px-1.5 text-xs',
        mono && 'font-mono',
        cls.bg, cls.text, cls.border,
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  )
}
