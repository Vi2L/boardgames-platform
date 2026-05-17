import { useEffect, useState } from 'react'
import { Command } from 'cmdk'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Search, Cpu, Database, FlaskConical, RotateCcw, Star, Zap,
} from 'lucide-react'
import { fetchFavorites } from '../../lib/api'
import { useSearchStore } from '../../store/search'

/**
 * @deprecated Use `src/components/ui/CommandPalette.tsx` instead.
 *
 * Старая Command-K палитра с hard-coded командами. Заменена новой версией
 * в `src/components/ui/CommandPalette.tsx` с register-API (`useCommand`).
 * Удалить после миграции всех страниц на новый UI (см. handoff PR 3+).
 *
 * Команды:
 *   - Навигация: Поиск, Парсеры, БД, Тесты
 *   - Force refresh последнего запроса
 *   - Запуск любимых поисков (последние 5)
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { query, setRefresh, refresh, startSearch, setQuery, setAllStores, setLimit } = useSearchStore()
  const { data: favorites = [] } = useQuery({
    queryKey: ['favorites'], queryFn: fetchFavorites,
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen(o => !o)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const close = () => setOpen(false)

  const go = (path: string) => {
    navigate(path)
    close()
  }

  const refreshLast = () => {
    if (!query.trim()) {
      close()
      return
    }
    setRefresh(true)
    // даём React-у моргнуть, потом запускаем — иначе startSearch увидит старое значение
    setTimeout(() => startSearch([]), 0)
    close()
  }

  const runFavorite = (f: typeof favorites[number]) => {
    setQuery(f.query)
    if (f.stores) setAllStores(f.stores.split(',').filter(Boolean))
    setRefresh(f.refresh)
    if (f.limit_n != null) setLimit(f.limit_n)
    navigate('/')
    setTimeout(() => startSearch([]), 50)
    close()
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 bg-black/60 z-[70] flex items-start justify-center pt-[15vh]"
      onClick={close}
    >
      <Command
        label="Command Palette"
        className="w-full max-w-lg bg-gray-900 border border-gray-700 rounded-lg shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <Command.Input
          autoFocus
          placeholder="Что нужно сделать?"
          className="w-full px-4 py-3 bg-gray-900 border-b border-gray-800 text-sm text-gray-100 placeholder-gray-500 focus:outline-none"
        />
        <Command.List className="max-h-[60vh] overflow-y-auto p-2">
          <Command.Empty className="text-sm text-gray-500 px-3 py-6 text-center">
            Ничего не найдено
          </Command.Empty>

          <Command.Group heading="Навигация" className="text-xs text-gray-500 px-2 py-1">
            <Item icon={<Search size={14} />} label="Поиск" hint="/" onSelect={() => go('/')} />
            <Item icon={<Cpu size={14} />} label="Парсеры" hint="/parsers" onSelect={() => go('/parsers')} />
            <Item icon={<Database size={14} />} label="База данных" hint="/database" onSelect={() => go('/database')} />
            <Item icon={<FlaskConical size={14} />} label="Тестирование" hint="/testing" onSelect={() => go('/testing')} />
          </Command.Group>

          <Command.Group heading="Действия" className="text-xs text-gray-500 px-2 py-1">
            <Item
              icon={<RotateCcw size={14} className={refresh ? 'text-orange-400' : ''} />}
              label="Force refresh последнего запроса"
              hint={query ? query : 'нет активного запроса'}
              disabled={!query.trim()}
              onSelect={refreshLast}
            />
          </Command.Group>

          {favorites.length > 0 && (
            <Command.Group heading="Избранное" className="text-xs text-gray-500 px-2 py-1">
              {favorites.slice(0, 5).map(f => (
                <Item
                  key={f.id}
                  icon={<Star size={14} className="text-yellow-400" fill="currentColor" />}
                  label={f.query}
                  hint={f.stores ?? 'все магазины'}
                  onSelect={() => runFavorite(f)}
                />
              ))}
            </Command.Group>
          )}
        </Command.List>

        <div className="px-3 py-1.5 border-t border-gray-800 text-[10px] text-gray-600 flex items-center gap-3">
          <Zap size={9} /> ↑↓ выбор · Enter запуск · Esc закрыть
        </div>
      </Command>
    </div>
  )
}

function Item({
  icon, label, hint, onSelect, disabled,
}: {
  icon: React.ReactNode
  label: string
  hint?: string
  onSelect: () => void
  disabled?: boolean
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      disabled={disabled}
      className="flex items-center gap-3 px-3 py-2 rounded text-sm text-gray-200 cursor-pointer aria-selected:bg-indigo-900/40 aria-selected:text-indigo-200 data-[disabled=true]:opacity-40 data-[disabled=true]:cursor-not-allowed"
    >
      {icon}
      <span className="flex-1">{label}</span>
      {hint && <span className="text-xs text-gray-500 truncate max-w-[40%]">{hint}</span>}
    </Command.Item>
  )
}
