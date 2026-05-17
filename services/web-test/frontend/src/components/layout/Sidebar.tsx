/**
 * Sidebar — левая навигация.
 *
 * Спека: pages/02-appshell.md.
 *   - 208w expanded / 56w collapsed
 *   - 10+ плоских пунктов (ТЗ §10)
 *   - active style: text-zinc-100 + bg-indigo-500/10 + 2px indigo-400 рулька слева
 *   - inactive: text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60
 *   - Collapse persist в localStorage['sidebar:collapsed']
 *   - Footer: HealthBadge (3 dots cluster — ML/parsers/catalog) + версия
 *
 * Компонент презентационный — NAV-список передаётся снаружи (App.tsx).
 */
import { NavLink } from 'react-router-dom'
import { PanelLeft, PanelLeftClose } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'

import { IconButton } from '../ui/IconButton'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** Опциональный counter справа (DLQ 142, unmatched 38 …). */
  badge?: number | string
  /** Если задан — показывается StatusDot слева в collapsed mode. */
  badgeTone?: 'warn' | 'danger' | 'info'
  /**
   * Если true — пункт рендерится как обычный <a target="_blank">, минуя
   * React Router. Используется для self-contained HTML-страниц (например,
   * `/help.html` в `public/`), которые живут отдельно от SPA-бандла.
   * Такой пункт никогда не isActive — справка открывается в новой вкладке.
   */
  external?: boolean
}

export interface SidebarProps {
  items: NavItem[]
  collapsed: boolean
  onToggle: () => void
  /** Render-prop для footer (HealthBadge cluster и т.п.). */
  footer?: React.ReactNode
  /** Версия приложения, в footer. */
  version?: string
}

export function Sidebar({ items, collapsed, onToggle, footer, version = 'v0.1.0' }: SidebarProps) {
  return (
    <aside
      className={clsx(
        'shrink-0 flex flex-col bg-zinc-900 border-r border-zinc-800',
        'transition-[width] duration-200',
        collapsed ? 'w-14' : 'w-52',
      )}
    >
      <header
        className={clsx(
          'h-12 shrink-0 border-b border-zinc-800 flex items-center',
          collapsed ? 'justify-center px-0' : 'justify-between px-3',
        )}
      >
        {!collapsed && (
          <div className="min-w-0">
            <div className="text-xs font-semibold text-zinc-100 tracking-tight">Parser Cockpit</div>
            <div className="text-xxs text-zinc-500 mt-0.5">dev portal · {version}</div>
          </div>
        )}
        <IconButton
          icon={collapsed ? PanelLeft : PanelLeftClose}
          size="sm"
          variant="ghost"
          aria-label={collapsed ? 'Развернуть боковую панель' : 'Свернуть боковую панель'}
          onClick={onToggle}
        />
      </header>

      <nav
        aria-label="Основная навигация"
        className={clsx('flex-1 py-2 space-y-0.5', collapsed ? 'px-1.5' : 'px-2')}
      >
        {items.map(({ to, label, icon: Icon, badge, external }) => {
          // Внешние пункты (например, /help.html) — обычный <a target="_blank">,
          // без isActive, рендерятся в том же визуальном стиле, что и неактивный NavLink.
          if (external) {
            return (
              <a
                key={to}
                href={to}
                target="_blank"
                rel="noopener noreferrer"
                title={collapsed ? label : undefined}
                className={clsx(
                  'group relative flex items-center rounded text-xs transition-colors',
                  collapsed ? 'justify-center h-8' : 'h-8 px-2.5 gap-2.5',
                  'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60',
                )}
              >
                <Icon
                  size={14}
                  className="text-zinc-500 group-hover:text-zinc-300"
                />
                {!collapsed && (
                  <>
                    <span className="flex-1 truncate">{label}</span>
                    {badge !== undefined && badge !== 0 && (
                      <span className="text-xxs font-mono tabular-nums text-zinc-500">
                        {badge}
                      </span>
                    )}
                  </>
                )}
              </a>
            )
          }

          return (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              title={collapsed ? label : undefined}
              className={({ isActive }) => clsx(
                'group relative flex items-center rounded text-xs transition-colors',
                collapsed ? 'justify-center h-8' : 'h-8 px-2.5 gap-2.5',
                isActive
                  ? 'bg-indigo-500/10 text-zinc-100 font-medium'
                  : 'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60',
              )}
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      aria-hidden
                      className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r bg-indigo-400"
                    />
                  )}
                  <Icon size={14} className={clsx(isActive ? 'text-indigo-300' : 'text-zinc-500 group-hover:text-zinc-300')} />
                  {!collapsed && (
                    <>
                      <span className="flex-1 truncate">{label}</span>
                      {badge !== undefined && badge !== 0 && (
                        <span className={clsx(
                          'text-xxs font-mono tabular-nums',
                          isActive ? 'text-indigo-300' : 'text-zinc-500',
                        )}>
                          {badge}
                        </span>
                      )}
                    </>
                  )}
                  {collapsed && badge !== undefined && badge !== 0 && (
                    <span
                      className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-amber-400"
                      aria-label={`${badge} новых`}
                    />
                  )}
                </>
              )}
            </NavLink>
          )
        })}
      </nav>

      <footer
        className={clsx(
          'border-t border-zinc-800',
          collapsed ? 'py-3 flex flex-col items-center gap-2' : 'px-3 py-3 space-y-1.5',
        )}
      >
        {footer}
        {!collapsed && version && (
          <div className="text-xxs text-zinc-600 font-mono">{version}</div>
        )}
      </footer>
    </aside>
  )
}
