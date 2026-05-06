import { Routes, Route, NavLink } from 'react-router-dom'
import { Search, Cpu } from 'lucide-react'
import clsx from 'clsx'
import { SearchPage } from './pages/SearchPage'
import { ParsersPage } from './pages/ParsersPage'

const NAV = [
  { to: '/', label: 'Поиск', icon: Search },
  { to: '/parsers', label: 'Парсеры', icon: Cpu },
]

export default function App() {
  return (
    <div className="flex h-screen bg-gray-950 overflow-hidden">
      <aside className="w-52 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="px-4 py-4 border-b border-gray-800">
          <div className="text-sm font-bold text-gray-100 tracking-tight">Parser Debug</div>
          <div className="text-xs text-gray-500 mt-0.5">Developer Portal</div>
        </div>
        <nav className="flex-1 py-2 space-y-0.5 px-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => clsx(
                'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-violet-900/50 text-violet-300 font-medium'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
              )}
            >
              <Icon size={15} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-gray-800 text-xs text-gray-600">v0.1.0</div>
      </aside>

      <main className="flex-1 overflow-y-auto p-6">
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/parsers" element={<ParsersPage />} />
        </Routes>
      </main>
    </div>
  )
}
