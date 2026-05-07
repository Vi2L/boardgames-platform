import { useRef } from 'react'
import { Search, RotateCcw, Square, PackageX } from 'lucide-react'
import clsx from 'clsx'
import type { StoreOut } from '../../types/api'
import { useSearchStore } from '../../store/search'
import { LoyaltyPanel } from './LoyaltyPanel'

interface Props {
  stores: StoreOut[]
  onSearch: () => void
  onStop: () => void
}

export function SearchForm({ stores, onSearch, onStop }: Props) {
  const {
    query, selectedStores, refresh, limit, showOutOfStock, isSearching,
    setQuery, toggleStore, setAllStores, clearStores, setRefresh, setLimit, setShowOutOfStock,
  } = useSearchStore()
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (isSearching) { onStop(); return }
    onSearch()
  }

  const allSelected = selectedStores.length === 0 || selectedStores.length === stores.length
  const isChecked = (slug: string) => selectedStores.length === 0 || selectedStores.includes(slug)

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            ref={inputRef}
            id="search-q-input"
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Название игры…  (Cmd+/)"
            className="w-full pl-9 pr-4 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30"
            disabled={isSearching}
            autoFocus
          />
        </div>
        <button
          type="submit"
          className={clsx(
            'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap',
            isSearching
              ? 'bg-red-900 hover:bg-red-800 text-red-300'
              : 'bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40 disabled:cursor-not-allowed',
          )}
          disabled={!isSearching && !query.trim()}
        >
          {isSearching
            ? <><Square size={13} /> Стоп</>
            : <><Search size={13} /> Поиск</>
          }
        </button>
      </div>

      {stores.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-gray-500">Магазины:</span>
          <button
            type="button"
            onClick={() => setAllStores(stores.map(s => s.slug))}
            className="text-xs text-violet-400 hover:text-violet-300"
          >
            Все
          </button>
          <button
            type="button"
            onClick={clearStores}
            className="text-xs text-gray-500 hover:text-gray-400"
          >
            Сброс
          </button>
          {stores.map(s => (
            <label key={s.slug} className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isChecked(s.slug)}
                onChange={() => {
                  if (allSelected && !selectedStores.includes(s.slug)) {
                    setAllStores(stores.map(x => x.slug))
                  }
                  toggleStore(s.slug)
                }}
                className="accent-violet-500 w-3.5 h-3.5"
              />
              <span className="text-xs text-gray-300">{s.name}</span>
            </label>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-5">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={refresh}
            onChange={e => setRefresh(e.target.checked)}
            className="accent-violet-500 w-3.5 h-3.5"
          />
          <span className="text-xs text-gray-400 flex items-center gap-1">
            <RotateCcw size={11} /> Принудительное обновление
          </span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none" title="HobbyGames и CrowdGames отдают признак наличия; Лавка и GaGa — нет, их товары всегда видны">
          <input
            type="checkbox"
            checked={showOutOfStock}
            onChange={e => setShowOutOfStock(e.target.checked)}
            className="accent-violet-500 w-3.5 h-3.5"
          />
          <span className="text-xs text-gray-400 flex items-center gap-1">
            <PackageX size={11} /> Показать товары не в наличии
          </span>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-xs text-gray-400">Лимит:</span>
          <input
            type="number"
            value={limit}
            onChange={e => setLimit(Math.max(1, Math.min(500, Number(e.target.value))))}
            min={1}
            max={500}
            className="w-16 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-300 focus:outline-none focus:border-violet-500"
          />
        </label>
      </div>

      <LoyaltyPanel />
    </form>
  )
}
