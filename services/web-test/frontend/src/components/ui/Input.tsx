/**
 * Input — текстовое поле с опциональной leading/trailing иконкой.
 *
 * Дизайн: одна высота 28px (sm) или 32px (md). text-xs (11px) — оператор
 * знает поля без больших label'ов.
 */
import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'

// Omit `size` — native HTML `size` ожидает number, а наш variant — 'sm' | 'md'.
export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  icon?: LucideIcon
  iconRight?: LucideIcon
  size?: 'sm' | 'md'
  /** font-mono для ID / score / SKU. */
  mono?: boolean
  error?: boolean
  /** Render-prop для слота правее поля (loading-spinner, KBD-подсказка и т.п.). */
  rightSlot?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    {
      className, icon: Icon, iconRight: IconRight, rightSlot,
      size = 'sm', mono = false, error = false, type = 'text',
      ...rest
    },
    ref,
  ) => {
    const height = size === 'md' ? 'h-8' : 'h-7'
    const iconSize = size === 'md' ? 14 : 12
    const padLeft = Icon ? 'pl-7' : 'pl-2.5'
    const padRight = (IconRight || rightSlot) ? 'pr-7' : 'pr-2.5'

    return (
      <div className={clsx('relative inline-flex items-center w-full', className)}>
        {Icon && (
          <span className="pointer-events-none absolute left-2 text-zinc-500">
            <Icon size={iconSize} />
          </span>
        )}
        <input
          ref={ref}
          type={type}
          className={clsx(
            height, padLeft, padRight,
            'w-full bg-zinc-900 border rounded text-xs',
            mono && 'font-mono',
            'text-zinc-100 placeholder:text-zinc-600',
            error ? 'border-rose-500/40' : 'border-zinc-800',
            'focus:outline-none focus:border-indigo-500',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'tabular-nums',
          )}
          {...rest}
        />
        {IconRight && !rightSlot && (
          <span className="pointer-events-none absolute right-2 text-zinc-500">
            <IconRight size={iconSize} />
          </span>
        )}
        {rightSlot && (
          <span className="absolute right-2 flex items-center">{rightSlot}</span>
        )}
      </div>
    )
  },
)
Input.displayName = 'Input'
