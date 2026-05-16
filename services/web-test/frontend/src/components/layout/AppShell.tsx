/**
 * AppShell — каркас всех страниц.
 *
 * Спека: pages/02-appshell.md.
 *
 * Структура:
 *   <AppShell.Root>
 *     <AppShell.Sidebar items={NAV} ... />
 *     <AppShell.Main>
 *       <AppShell.Topbar breadcrumbs={...} ... />
 *       <AppShell.Content>{children}</AppShell.Content>
 *     </AppShell.Main>
 *   </AppShell.Root>
 *
 * Для удобства экспортируется одиночный `<AppShell>` который под капотом
 * собирает всю структуру (props для Sidebar / Topbar / TooltipProvider).
 *
 * Tooltip-provider оборачивает всё внутри — Radix Tooltip требует Provider
 * выше по дереву (если использовать Tooltip без Provider — фоллбэк работает,
 * но delay 700ms; с Provider — настраиваемый 300ms).
 */
import { useEffect, useState, type ReactNode } from 'react'
import clsx from 'clsx'

import { TooltipProvider } from '../ui/Tooltip'
import { Sidebar, type NavItem } from './Sidebar'
import { Topbar, type BreadcrumbItem } from './Topbar'

const SIDEBAR_STORAGE_KEY = 'sidebar:collapsed'

function readInitialCollapsed(): boolean {
  if (typeof window === 'undefined') return false
  // На узких экранах всегда стартуем сжатым — иначе main контент режется.
  if (window.matchMedia('(max-width: 1279px)').matches) return true
  return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === '1'
}

export interface AppShellProps {
  navItems: NavItem[]
  breadcrumbs?: BreadcrumbItem[]
  /** Открыть CommandPalette по Cmd+K (handler из App.tsx). */
  onOpenCommandPalette?: () => void
  bgJobsCount?: number
  onBgJobsClick?: () => void
  /** Footer слот в sidebar — обычно HealthBadge cluster. */
  sidebarFooter?: ReactNode
  /** Доп. элементы в Topbar справа от bg-jobs (Recents, Settings). */
  topbarRightSlot?: ReactNode
  /** Основной контент — обычно <Routes>...</Routes>. */
  children: ReactNode
}

export function AppShell({
  navItems, breadcrumbs, onOpenCommandPalette,
  bgJobsCount = 0, onBgJobsClick,
  sidebarFooter, topbarRightSlot, children,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(readInitialCollapsed)

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  return (
    <TooltipProvider delayDuration={300}>
      <div className={clsx(
        'flex h-screen overflow-hidden',
        'bg-zinc-950 text-zinc-200 antialiased',
        // Inter — основной шрифт; mono используется явно через `font-mono`
        'font-sans',
      )}>
        <Sidebar
          items={navItems}
          collapsed={collapsed}
          onToggle={() => setCollapsed(c => !c)}
          footer={sidebarFooter}
        />
        <main className="flex-1 min-w-0 flex flex-col">
          <Topbar
            breadcrumbs={breadcrumbs}
            onOpenCommandPalette={onOpenCommandPalette}
            bgJobsCount={bgJobsCount}
            onBgJobsClick={onBgJobsClick}
            rightSlot={topbarRightSlot}
          />
          <div className="flex-1 min-h-0 overflow-y-auto">
            {children}
          </div>
        </main>
      </div>
    </TooltipProvider>
  )
}
