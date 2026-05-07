import clsx from 'clsx'

interface Props {
  className?: string
  /** Высота строки/блока — короткое имя для частых вариантов. */
  height?: 'sm' | 'md' | 'lg' | string
}

/**
 * Простой skeleton-плейсхолдер с tailwind animate-pulse.
 *
 * Не делаем универсальный «render any shape» — для разных мест
 * проще писать `<div className="space-y-2"><Skeleton /><Skeleton /></div>`
 * напрямую. Это нужно как примитив для табличных/листовых заглушек.
 */
export function Skeleton({ className, height = 'md' }: Props) {
  const h = height === 'sm' ? 'h-3'
        : height === 'md' ? 'h-4'
        : height === 'lg' ? 'h-6'
        : ''
  const inline = typeof height === 'string' && !['sm', 'md', 'lg'].includes(height)
  return (
    <div
      className={clsx('animate-pulse bg-gray-800 rounded', h, className)}
      style={inline ? { height: height as string } : undefined}
    />
  )
}

/**
 * Заглушка строки результатов / товара в таблице — несколько узких
 * полос разной длины, как обычно бывает в реальном ряду.
 */
export function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 py-2">
      <Skeleton className="w-10 h-10 flex-shrink-0" height="40px" />
      <div className="flex-1 space-y-1.5">
        <Skeleton className="w-2/3" />
        <Skeleton className="w-1/3" height="sm" />
      </div>
      <Skeleton className="w-16" />
    </div>
  )
}

export function SkeletonList({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-1.5">
      {Array.from({ length: rows }).map((_, i) => <SkeletonRow key={i} />)}
    </div>
  )
}
