import { useEffect, useState } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import { Search, Cpu, PanelLeftClose, PanelLeft } from 'lucide-react'
import clsx from 'clsx'
import { SearchPage } from './pages/SearchPage'
import { ParsersPage } from './pages/ParsersPage'
import { HealthBadge } from './components/shared/HealthBadge'

const NAV = [
  { to: '/', label: 'Поиск', icon: Search },
  { to: '/parsers', label: 'Парсеры', icon: Cpu },
]

const STORAGE_KEY = 'sidebar:collapsed'

/**
 * Начальное состояние сайдбара:
 * - на узких экранах (<768px) всегда стартуем сжатым;
 * - на десктопе берём сохранённое значение из localStorage;
 * - SSR-fallback: разворот по умолчанию.
 *
 * matchMedia читаем синхронно в lazy-init useState, чтобы не было
 * мигания «развернулся → схлопнулся» на первом рендере.
 */
function readInitialCollapsed(): boolean {
  if (typeof window === 'undefined') return false
  if (window.matchMedia('(max-width: 767px)').matches) return true
  return window.localStorage.getItem(STORAGE_KEY) === '1'
}

export default function App() {
  const [collapsed, setCollapsed] = useState(readInitialCollapsed)

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  return (
    <div className="flex h-screen bg-gray-950 overflow-hidden">
      <aside
        className={clsx(
          'flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col transition-[width] duration-200',
          collapsed ? 'w-14' : 'w-52',
        )}
      >
        <div className={clsx(
          'flex items-center border-b border-gray-800 h-14',
          collapsed ? 'justify-center px-0' : 'justify-between px-4',
        )}>
          {!collapsed && (
            <div>
              <div className="text-sm font-bold text-gray-100 tracking-tight">Parser Debug</div>
              <div className="text-xs text-gray-500 mt-0.5">Developer Portal</div>
            </div>
          )}
          <button
            type="button"
            onClick={() => setCollapsed(c => !c)}
            title={collapsed ? 'Развернуть боковую панель' : 'Свернуть боковую панель'}
            aria-label={collapsed ? 'Развернуть боковую панель' : 'Свернуть боковую панель'}
            className="p-1.5 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
          >
            {collapsed ? <PanelLeft size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>

        <nav className={clsx('flex-1 py-2 space-y-0.5', collapsed ? 'px-1.5' : 'px-2')}>
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              title={collapsed ? label : undefined}
              className={({ isActive }) => clsx(
                'flex items-center gap-2.5 rounded-md text-sm transition-colors',
                collapsed ? 'justify-center py-2' : 'px-3 py-2',
                isActive
                  ? 'bg-violet-900/50 text-violet-300 font-medium'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
              )}
            >
              <Icon size={15} />
              {!collapsed && label}
            </NavLink>
          ))}
        </nav>

        <div className={clsx(
          'border-t border-gray-800',
          collapsed ? 'py-3 flex flex-col items-center gap-2' : 'px-4 py-3 space-y-1.5',
        )}>
          <HealthBadge compact={collapsed} />
          {!collapsed && <div className="text-xs text-gray-600">v0.1.0</div>}
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto p-4 md:p-6">
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/parsers" element={<ParsersPage />} />
        </Routes>
      </main>
    </div>
  )
}
