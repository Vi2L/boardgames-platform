/**
 * EmptyState — центрированный placeholder когда нет данных / результата.
 *
 * Иконка 20px text-zinc-600. Title text-sm zinc-300. Description text-xs
 * zinc-500 max-w-xs. Optional primary action — Button. См. components.md.
 */
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'

export interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  className?: string
  /** Размер иконки в px (по умолчанию 24 — увеличиваем чуть, чтобы было видно). */
  iconSize?: number
}

export function EmptyState({
  icon: Icon, title, description, action, className, iconSize = 24,
}: EmptyStateProps) {
  return (
    <div className={clsx(
      'flex flex-col items-center justify-center gap-3 py-10 text-center',
      className,
    )}>
      {Icon && (
        <Icon size={iconSize} className="text-zinc-600" />
      )}
      <div className="space-y-1">
        <div className="text-sm text-zinc-300">{title}</div>
        {description && (
          <p className="text-xs text-zinc-500 max-w-xs leading-relaxed">{description}</p>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  )
}
