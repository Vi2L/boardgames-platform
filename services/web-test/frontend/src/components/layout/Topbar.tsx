/**
 * Topbar — верхняя панель приложения.
 *
 * Спека: pages/02-appshell.md.
 *   - h-12 (48px), bg-zinc-950, border-b-zinc-800
 *   - Breadcrumbs слева
 *   - CommandPaletteTrigger по центру (w-280)
 *   - BgJobsIndicator + (опц.) Recents/Settings справа
 *
 * Breadcrumbs из map'инга path → [{label, href}] вычисляется снаружи —
 * Topbar получает готовый массив.
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Search as SearchIcon, ChevronRight } from 'lucide-react'
import clsx from 'clsx'

import { KBD } from '../ui/KBD'
import { BgJobsIndicator } from './BgJobsIndicator'

export interface BreadcrumbItem {
  label: string
  href?: string
}

export interface TopbarProps {
  breadcrumbs?: BreadcrumbItem[]
  /** Открыть CommandPalette (Cmd+K). */
  onOpenCommandPalette?: () => void
  bgJobsCount?: number
  onBgJobsClick?: () => void
  /** Дополнительные элементы справа (Recents, Settings, ...). */
  rightSlot?: React.ReactNode
}

export function Topbar({
  breadcrumbs, onOpenCommandPalette, bgJobsCount, onBgJobsClick, rightSlot,
}: TopbarProps) {
  const isMac = useMemo(
    () => typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform),
    [],
  )

  return (
    <header className="h-12 shrink-0 bg-zinc-950 border-b border-zinc-800 flex items-center gap-3 px-4">
      <Breadcrumbs items={breadcrumbs ?? []} />
      <div className="flex-1" />

      {/* Command palette trigger — кнопка с placeholder + KBD-подсказкой */}
      <button
        type="button"
        onClick={onOpenCommandPalette}
        className={clsx(
          'hidden md:inline-flex items-center gap-2 h-8 px-2.5 rounded',
          'bg-zinc-900 border border-zinc-800 hover:border-zinc-700',
          'text-xs text-zinc-500 transition-colors w-[280px]',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
        )}
        aria-keyshortcuts="Meta+K Control+K"
        aria-label="Открыть command palette"
      >
        <SearchIcon size={13} />
        <span className="flex-1 text-left">Перейти / выполнить…</span>
        <span className="flex items-center gap-0.5">
          <KBD>{isMac ? '⌘' : 'Ctrl'}</KBD>
          <KBD>K</KBD>
        </span>
      </button>

      <BgJobsIndicator count={bgJobsCount} onClick={onBgJobsClick} />

      {rightSlot}
    </header>
  )
}

function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  if (items.length === 0) return null
  return (
    <nav aria-label="Хлебные крошки" className="flex items-center gap-1 min-w-0">
      <ol className="flex items-center gap-1 text-xs min-w-0">
        {items.map((b, i) => {
          const isLast = i === items.length - 1
          return (
            <li key={i} className="flex items-center gap-1 min-w-0">
              {b.href && !isLast ? (
                <Link
                  to={b.href}
                  className="text-zinc-500 hover:text-zinc-200 transition-colors truncate"
                >
                  {b.label}
                </Link>
              ) : (
                <span className={clsx('truncate', isLast ? 'text-zinc-100 font-medium' : 'text-zinc-500')}>
                  {b.label}
                </span>
              )}
              {!isLast && <ChevronRight size={11} className="text-zinc-700 flex-shrink-0" />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
