/**
 * Skeleton — loading placeholder.
 *
 * Высота должна СОВПАДАТЬ с финальным контентом (h-3 для текста, h-7
 * для compact-строки таблицы) — иначе layout «прыгает» при загрузке.
 * Никаких spinner'ов по центру (см. components.md → Skeleton).
 *
 * Composite `<Skeleton.Row>` рендерит чёрточки для N колонок таблицы.
 */
import type { HTMLAttributes } from 'react'
import clsx from 'clsx'

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {}

function SkeletonBase({ className, ...rest }: SkeletonProps) {
  return (
    <div
      className={clsx(
        'animate-pulse bg-zinc-800/60 rounded',
        className,
      )}
      {...rest}
    />
  )
}

interface SkeletonRowProps {
  /** Сколько «колонок» рендерить. */
  columns?: number
  /** Высота строки в Tailwind-классе (h-7 = 28px = compact). */
  rowClass?: string
  /** Распределение ширин per-column в `flex-`-классах (по умолчанию равные). */
  widths?: string[]
}

function SkeletonRow({ columns = 4, rowClass = 'h-7', widths }: SkeletonRowProps) {
  return (
    <div className={clsx('flex items-center gap-3 px-3', rowClass)}>
      {Array.from({ length: columns }).map((_, i) => (
        <SkeletonBase
          key={i}
          className={clsx('h-3', widths?.[i] ?? 'flex-1')}
        />
      ))}
    </div>
  )
}

export const Skeleton = Object.assign(SkeletonBase, { Row: SkeletonRow })
