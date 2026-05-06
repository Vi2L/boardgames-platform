import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Database, Trash2, RefreshCw, AlertTriangle, ChevronLeft, ChevronRight,
  CheckCircle2, XCircle, Clock,
} from 'lucide-react'
import clsx from 'clsx'
import {
  fetchDbProducts, fetchDbSearches, deleteDbProduct, fetchStatsStores,
} from '../lib/api'
import { getStoreBadgeColor, getStoreLabel, STORE_LABELS } from '../lib/stores'
import { PriceHistogram } from '../components/database/PriceHistogram'
import { SkeletonList } from '../components/shared/Skeleton'
import type { ProductOut, StoreHealthEntry } from '../types/api'

type Tab = 'products' | 'stores' | 'searches'

const SORT_OPTIONS = [
  { value: 'fetched_desc', label: 'Свежие' },
  { value: 'price_asc',    label: 'Цена ↑' },
  { value: 'price_desc',   label: 'Цена ↓' },
  { value: 'title_asc',    label: 'А→Я' },
] as const

const PAGE_SIZE = 50

export function DatabasePage() {
  const [tab, setTab] = useState<Tab>('products')

  return (
    <div className="space-y-4 max-w-6xl">
      <div>
        <h1 className="text-lg font-semibold text-gray-100 flex items-center gap-2">
          <Database size={18} /> База данных
        </h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Локальный кеш дебаг-портала и статистика по парсерам
        </p>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="flex border-b border-gray-800 bg-gray-900/50">
          <TabButton active={tab === 'products'} onClick={() => setTab('products')}>Товары</TabButton>
          <TabButton active={tab === 'stores'} onClick={() => setTab('stores')}>Магазины</TabButton>
          <TabButton active={tab === 'searches'} onClick={() => setTab('searches')}>Журнал</TabButton>
        </div>

        <div className="p-4">
          {tab === 'products' && <ProductsTab />}
          {tab === 'stores' && <StoresTab />}
          {tab === 'searches' && <SearchesTab />}
        </div>
      </div>
    </div>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
        active
          ? 'border-violet-500 text-violet-400'
          : 'border-transparent text-gray-500 hover:text-gray-300',
      )}
    >
      {children}
    </button>
  )
}

// ── Товары ────────────────────────────────────────────────────────────────

function ProductsTab() {
  const [q, setQ] = useState('')
  const [store, setStore] = useState('')
  const [sort, setSort] = useState<typeof SORT_OPTIONS[number]['value']>('fetched_desc')
  const [page, setPage] = useState(1)
  const queryClient = useQueryClient()

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['db-products', q, store, sort, page],
    queryFn: () => fetchDbProducts({ q: q || undefined, store: store || undefined, sort, page, page_size: PAGE_SIZE }),
    placeholderData: (prev) => prev,    // не «прыгать» в пустое состояние при пагинации
  })

  const handleDelete = async (id: number) => {
    if (!confirm(`Удалить товар #${id} из локальной БД?`)) return
    await deleteDbProduct(id)
    void queryClient.invalidateQueries({ queryKey: ['db-products'] })
  }

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const prices = items.map(p => p.price_rub)

  return (
    <div className="space-y-4">
      {/* Фильтры */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text"
          value={q}
          onChange={e => { setQ(e.target.value); setPage(1) }}
          placeholder="Поиск по названию"
          className="flex-1 min-w-[200px] px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-violet-500"
        />
        <select
          value={store}
          onChange={e => { setStore(e.target.value); setPage(1) }}
          className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200"
        >
          <option value="">Все магазины</option>
          {Object.entries(STORE_LABELS).map(([slug, label]) => (
            <option key={slug} value={slug}>{label}</option>
          ))}
        </select>
        <select
          value={sort}
          onChange={e => setSort(e.target.value as typeof sort)}
          className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200"
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => refetch()}
          className="p-1.5 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-800"
          title="Обновить"
        >
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Гистограмма */}
      {prices.length >= 2 && (
        <details className="bg-gray-950/50 border border-gray-800 rounded">
          <summary className="px-3 py-2 text-xs text-gray-400 cursor-pointer hover:text-gray-200 select-none">
            Распределение цен на текущей странице ({prices.length} товаров)
          </summary>
          <div className="p-3 pt-0">
            <PriceHistogram prices={prices} />
          </div>
        </details>
      )}

      {/* Список */}
      {isError && (
        <div className="text-sm text-red-400 py-8 text-center">Ошибка загрузки</div>
      )}
      {!isError && isLoading && (
        <SkeletonList rows={5} />
      )}
      {!isError && !isLoading && items.length === 0 && (
        <div className="text-sm text-gray-500 py-12 text-center">
          Пока пусто. Запусти поиск — товары попадут сюда.
        </div>
      )}
      {!isError && items.length > 0 && (
        <ProductsList items={items} onDelete={handleDelete} />
      )}

      {/* Пагинация */}
      {total > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} onChange={setPage} total={total} />
      )}
    </div>
  )
}

function ProductsList({
  items, onDelete,
}: { items: ProductOut[]; onDelete: (id: number) => void }) {
  return (
    <div className="overflow-x-auto rounded border border-gray-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-900/80">
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium w-10"></th>
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Магазин</th>
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Название</th>
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium whitespace-nowrap">Цена</th>
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium hidden md:table-cell">Обновлено</th>
            <th className="px-3 py-2 w-10"></th>
          </tr>
        </thead>
        <tbody>
          {items.map(p => (
            <tr key={p.id} className="border-b border-gray-800/40 hover:bg-gray-900/60">
              <td className="px-3 py-2 text-xs text-gray-600 font-mono">#{p.id}</td>
              <td className="px-3 py-2">
                <span className={clsx('px-2 py-0.5 rounded text-xs font-mono', getStoreBadgeColor(p.store_slug))}>
                  {p.store_slug}
                </span>
              </td>
              <td className="px-3 py-2 max-w-md">
                <Link
                  to={`/products/${p.id}`}
                  className="font-medium text-gray-200 hover:text-violet-300 truncate block"
                  title={p.title}
                >
                  {p.title}
                </Link>
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-green-400 font-semibold">
                {p.price_rub.toLocaleString('ru-RU')} ₽
              </td>
              <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap hidden md:table-cell">
                {new Date(p.fetched_at).toLocaleDateString('ru-RU')}
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  type="button"
                  onClick={() => onDelete(p.id)}
                  className="p-1 rounded text-gray-500 hover:text-red-400 hover:bg-red-950/30"
                  title="Удалить из локальной БД"
                >
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Pagination({
  page, totalPages, total, onChange,
}: { page: number; totalPages: number; total: number; onChange: (p: number) => void }) {
  return (
    <div className="flex items-center justify-between text-xs text-gray-500">
      <span>Всего: {total}</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(Math.max(1, page - 1))}
          disabled={page === 1}
          className="p-1 rounded hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <ChevronLeft size={14} />
        </button>
        <span className="font-mono">{page} / {totalPages}</span>
        <button
          type="button"
          onClick={() => onChange(Math.min(totalPages, page + 1))}
          disabled={page === totalPages}
          className="p-1 rounded hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}

// ── Магазины (stats) ──────────────────────────────────────────────────────

function StoresTab() {
  const { data, isLoading } = useQuery({ queryKey: ['stats-stores'], queryFn: fetchStatsStores })

  if (isLoading) return <div className="text-sm text-gray-500 py-8 text-center">Загрузка…</div>

  if (data && '_unavailable' in data) {
    return (
      <div className="bg-yellow-950/30 border border-yellow-900/50 rounded p-4 text-sm">
        <div className="flex items-center gap-2 text-yellow-400 mb-1">
          <AlertTriangle size={14} /> parsers stats недоступны
        </div>
        <div className="text-gray-400 font-mono text-xs">{data._error}</div>
      </div>
    )
  }

  const entries = (data ?? []) as StoreHealthEntry[]
  if (entries.length === 0) {
    return <div className="text-sm text-gray-500 py-8 text-center">Нет данных</div>
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
      {entries.map((s, i) => <StoreCard key={s.slug ?? i} stats={s} />)}
    </div>
  )
}

function StoreCard({ stats }: { stats: StoreHealthEntry }) {
  const slug = stats.slug ?? '—'
  const successRate = stats.success_rate
  const avgMs = stats.avg_ms
  const lastError = stats.last_error
  const ok = successRate != null && successRate >= 0.9

  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-200">{getStoreLabel(slug)}</span>
        {ok
          ? <CheckCircle2 size={14} className="text-green-400" />
          : <XCircle size={14} className="text-red-400" />}
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <div className="text-gray-500">Успешность</div>
          <div className={clsx('font-mono font-semibold', ok ? 'text-green-400' : 'text-red-400')}>
            {successRate != null ? `${(successRate * 100).toFixed(1)}%` : '—'}
          </div>
        </div>
        <div>
          <div className="text-gray-500 flex items-center gap-1">
            <Clock size={10} /> Среднее
          </div>
          <div className="font-mono text-gray-300">
            {avgMs != null ? `${Math.round(avgMs)}ms` : '—'}
          </div>
        </div>
      </div>
      {lastError && (
        <div className="text-xs text-red-300/70 font-mono truncate" title={lastError}>
          {lastError}
        </div>
      )}
    </div>
  )
}

// ── Журнал поисков ────────────────────────────────────────────────────────

function SearchesTab() {
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['db-searches', page, query],
    queryFn: () => fetchDbSearches(page, PAGE_SIZE, query || undefined),
    placeholderData: (prev) => prev,
  })

  if (isLoading) return <div className="text-sm text-gray-500 py-8 text-center">Загрузка…</div>

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-3">
      <input
        type="text"
        value={query}
        onChange={e => { setQuery(e.target.value); setPage(1) }}
        placeholder="Фильтр по запросу"
        className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-violet-500"
      />

      {items.length === 0
        ? <div className="text-sm text-gray-500 py-8 text-center">Журнал пуст</div>
        : (
          <div className="space-y-1.5">
            {items.map(s => (
              <details key={s.id} className="bg-gray-950/40 border border-gray-800 rounded">
                <summary className="px-3 py-2 text-sm cursor-pointer flex items-center gap-3 select-none">
                  <span className="text-gray-200 font-medium">{s.query}</span>
                  <span className={clsx(
                    'px-1.5 py-0.5 rounded text-xs',
                    s.source === 'cache' ? 'bg-yellow-950 text-yellow-400'
                      : s.source === 'network' ? 'bg-green-950 text-green-400'
                      : 'bg-gray-800 text-gray-400',
                  )}>
                    {s.source ?? 'fail'}
                  </span>
                  <span className="text-xs text-gray-500">{s.products_count} товаров</span>
                  {s.error_count > 0 && (
                    <span className="text-xs text-red-400">ошибок: {s.error_count}</span>
                  )}
                  <span className="ml-auto text-xs text-gray-600">
                    {s.total_ms != null && `${s.total_ms}ms · `}
                    {new Date(s.created_at).toLocaleString('ru-RU')}
                  </span>
                </summary>
                <div className="px-3 pb-3 text-xs space-y-1 font-mono">
                  {s.stores && <div className="text-gray-500">stores: <span className="text-gray-300">{s.stores}</span></div>}
                  {s.errors_json && s.errors_json !== '{}' && (
                    <pre className="text-red-300/70 whitespace-pre-wrap">{s.errors_json}</pre>
                  )}
                </div>
              </details>
            ))}
          </div>
        )}

      {total > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} onChange={setPage} total={total} />
      )}
    </div>
  )
}
