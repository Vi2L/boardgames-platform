import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ProductDrawer } from '../components/search/ProductDrawer'
import {
  Database, Trash2, RefreshCw, AlertTriangle, ChevronLeft, ChevronRight,
  CheckCircle2, XCircle, Clock, Info,
} from 'lucide-react'
import clsx from 'clsx'
import {
  fetchDbProducts, fetchDbSearches, deleteDbProduct, fetchStatsStores,
  fetchParsersDbMeta,
} from '../lib/api'
import { getStoreBadgeColor, getStoreLabel, STORE_LABELS } from '../lib/stores'
import { PriceHistogram } from '../components/database/PriceHistogram'
import { InventoryTab } from '../components/database/parsers/InventoryTab'
import { AnalyticsTab } from '../components/database/parsers/AnalyticsTab'
import { ProductsBrowserTab } from '../components/database/parsers/ProductsBrowserTab'
import { ChartsTab } from '../components/database/parsers/ChartsTab'
import { SkeletonList } from '../components/shared/Skeleton'
import type { ProductOut, StoreHealthEntry } from '../types/api'

type Tab = 'products' | 'stores' | 'searches'
        | 'parsers-inventory' | 'parsers-products' | 'parsers-analytics' | 'parsers-charts'

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

      <DatabaseSummary onJump={setTab} />


      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="flex border-b border-gray-800 bg-gray-900/50 overflow-x-auto">
          <TabButton active={tab === 'products'} onClick={() => setTab('products')}>Товары портала</TabButton>
          <TabButton active={tab === 'stores'} onClick={() => setTab('stores')}>Магазины</TabButton>
          <TabButton active={tab === 'searches'} onClick={() => setTab('searches')}>Журнал</TabButton>
          <div className="w-px bg-gray-800 my-2 mx-1" />
          <TabButton active={tab === 'parsers-inventory'} onClick={() => setTab('parsers-inventory')}>
            БД парсеров: inventory
          </TabButton>
          <TabButton active={tab === 'parsers-products'} onClick={() => setTab('parsers-products')}>
            БД парсеров: товары
          </TabButton>
          <TabButton active={tab === 'parsers-analytics'} onClick={() => setTab('parsers-analytics')}>
            БД парсеров: аналитика
          </TabButton>
          <TabButton active={tab === 'parsers-charts'} onClick={() => setTab('parsers-charts')}>
            БД парсеров: графики
          </TabButton>
        </div>

        <div className="p-4">
          {tab === 'products' && <ProductsTab />}
          {tab === 'stores' && <StoresTab />}
          {tab === 'searches' && <SearchesTab />}
          {tab === 'parsers-inventory' && <InventoryTab />}
          {tab === 'parsers-products' && <ProductsBrowserTab />}
          {tab === 'parsers-analytics' && <AnalyticsTab />}
          {tab === 'parsers-charts' && <ChartsTab />}
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
  const [selected, setSelected] = useState<ProductOut | null>(null)
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
      {/* Info-блок */}
      <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-gray-950/40 border border-gray-800 text-xs text-gray-400">
        <Info size={13} className="text-violet-400 flex-shrink-0 mt-0.5" />
        <div>
          <strong className="text-gray-300">Локальный кеш товаров портала.</strong>
          {' '}Сюда попадает каждый товар, который пришёл в результатах поиска через web-test.
          Это «всё что когда-либо видели» — сравните с inventory parsers (свежее состояние БД parsers).
          Цена — в рублях, на момент последнего наблюдения. Клик по строке открывает карточку товара справа.
        </div>
      </div>

      {/* Фильтры */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text"
          value={q}
          onChange={e => { setQ(e.target.value); setPage(1) }}
          placeholder="Поиск по названию"
          title="Поиск SQL LIKE %text% по названию товара (без учёта регистра)"
          className="flex-1 min-w-[200px] px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-violet-500"
        />
        <select
          value={store}
          onChange={e => { setStore(e.target.value); setPage(1) }}
          title="Показывать товары только из выбранного магазина"
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
          title="Порядок сортировки результатов"
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
          title="Перезагрузить страницу из БД"
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
        <ProductsList items={items} onDelete={handleDelete} onSelect={setSelected} />
      )}

      {/* Пагинация */}
      {total > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} onChange={setPage} total={total} />
      )}

      {/* Карточка товара справа — переиспользуем ProductDrawer со страницы поиска. */}
      <ProductDrawer
        product={selected}
        pool={items}
        onClose={() => setSelected(null)}
        onSelect={setSelected}
      />
    </div>
  )
}

function ProductsList({
  items, onDelete, onSelect,
}: {
  items: ProductOut[]
  onDelete: (id: number) => void
  onSelect: (p: ProductOut) => void
}) {
  return (
    <div className="overflow-x-auto rounded border border-gray-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-900/80">
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium w-10" title="Внутренний ID товара в БД parsers">#</th>
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Магазин</th>
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Название</th>
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium whitespace-nowrap" title="Цена на момент последнего наблюдения, в рублях">Цена</th>
            <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium hidden md:table-cell" title="Когда товар последний раз попадал в результаты поиска">Обновлено</th>
            <th className="px-3 py-2 w-10"></th>
          </tr>
        </thead>
        <tbody>
          {items.map(p => (
            <tr
              key={p.id}
              className="border-b border-gray-800/40 hover:bg-gray-900/60 cursor-pointer"
              onClick={() => onSelect(p)}
            >
              <td className="px-3 py-2 text-xs text-gray-600 font-mono">#{p.id}</td>
              <td className="px-3 py-2">
                <span className={clsx('px-2 py-0.5 rounded text-xs font-mono', getStoreBadgeColor(p.store_slug))} title={getStoreLabel(p.store_slug)}>
                  {p.store_slug}
                </span>
              </td>
              <td className="px-3 py-2 max-w-md">
                <span className="font-medium text-gray-200 hover:text-violet-300 truncate block" title={p.title}>
                  {p.title}
                </span>
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-green-400 font-semibold">
                {p.price_rub.toLocaleString('ru-RU')} ₽
              </td>
              <td
                className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap hidden md:table-cell"
                title={p.fetched_at}
              >
                {new Date(p.fetched_at).toLocaleDateString('ru-RU')}
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  type="button"
                  onClick={e => { e.stopPropagation(); onDelete(p.id) }}
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
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['stats-stores'], queryFn: fetchStatsStores })

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['stats-stores'] })
  }

  const entries = data && !('_unavailable' in data) ? (data as StoreHealthEntry[]) : []
  // Сортируем по success_rate возрастающе → проблемные парсеры наверху,
  // потом по total_calls_24h — больше нагрузки = выше внимание оператора.
  const sorted = [...entries].sort((a, b) => {
    const arate = a.success_rate_24h ?? -1
    const brate = b.success_rate_24h ?? -1
    if (arate !== brate) return arate - brate
    return (b.total_calls_24h ?? 0) - (a.total_calls_24h ?? 0)
  })

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-gray-950/40 border border-gray-800 text-xs text-gray-400">
        <Info size={13} className="text-violet-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <strong className="text-gray-300">Здоровье парсеров за последние 24 часа.</strong>
          {' '}Ok ≥ 90% успешных запросов, иначе красный значок. Сортировка — проблемные сначала.
          Время ответа = среднее по успешным вызовам, включая обогащение страниц товаров.
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-800 hover:bg-gray-700 text-gray-200"
          title="Перезагрузить статистику"
        >
          <RefreshCw size={11} /> Обновить
        </button>
      </div>

      {isLoading && <div className="text-sm text-gray-500 py-8 text-center">Загрузка…</div>}

      {!isLoading && data && '_unavailable' in data && (
        <div className="bg-yellow-950/30 border border-yellow-900/50 rounded p-4 text-sm">
          <div className="flex items-center gap-2 text-yellow-400 mb-1">
            <AlertTriangle size={14} /> parsers stats недоступны
          </div>
          <div className="text-gray-400 font-mono text-xs">{data._error}</div>
        </div>
      )}

      {!isLoading && (!data || (!('_unavailable' in data) && entries.length === 0)) && (
        <div className="text-sm text-gray-500 py-8 text-center">
          Нет данных за 24ч. Запусти любой парсер через «Поиск» или вкладку «Парсеры».
        </div>
      )}

      {!isLoading && sorted.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {sorted.map(s => <StoreCard key={s.store_slug} stats={s} />)}
        </div>
      )}
    </div>
  )
}

function StoreCard({ stats }: { stats: StoreHealthEntry }) {
  const slug = stats.store_slug
  const successPct = stats.success_rate_24h               // 0..100
  const avgMs = stats.avg_response_ms
  const lastError = stats.last_error
  const total = stats.total_calls_24h
  const failures = total - stats.success_count_24h
  const ok = successPct != null && successPct >= 90

  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-200">{getStoreLabel(slug)}</span>
        <span title={ok ? '≥ 90% успешных вызовов' : 'Менее 90% успешных вызовов — есть деградация'}>
          {ok
            ? <CheckCircle2 size={14} className="text-green-400" />
            : <XCircle size={14} className="text-red-400" />}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div title="Доля успешных HTTP-вызовов парсера за 24 часа">
          <div className="text-gray-500">Успешность</div>
          <div className={clsx('font-mono font-semibold', ok ? 'text-green-400' : 'text-red-400')}>
            {successPct != null ? `${successPct.toFixed(1)}%` : '—'}
          </div>
        </div>
        <div title="Среднее время поиска (включая обогащение страниц товаров)">
          <div className="text-gray-500 flex items-center gap-1">
            <Clock size={10} /> Среднее
          </div>
          <div className="font-mono text-gray-300">
            {avgMs != null ? formatMs(avgMs) : '—'}
          </div>
        </div>
        <div title={`Всего ${total} запросов за 24ч, из них ${failures} с ошибкой`}>
          <div className="text-gray-500">Запросов</div>
          <div className="font-mono text-gray-300">
            {total.toLocaleString('ru-RU')}
            {failures > 0 && <span className="text-red-400"> / {failures}↯</span>}
          </div>
        </div>
      </div>
      {stats.last_seen && (
        <div className="text-[10px] text-gray-500" title={`Последний вызов: ${stats.last_seen}`}>
          last seen: {stats.last_seen.slice(0, 16).replace('T', ' ')}
        </div>
      )}
      {lastError && (
        <div className="text-xs text-red-300/70 font-mono truncate" title={lastError}>
          {lastError}
        </div>
      )}
    </div>
  )
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} мс`
  return `${(ms / 1000).toFixed(1)} с`
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

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-gray-950/40 border border-gray-800 text-xs text-gray-400">
        <Info size={13} className="text-violet-400 flex-shrink-0 mt-0.5" />
        <div>
          <strong className="text-gray-300">Журнал поисков через debug-портал.</strong>
          {' '}Каждая строка — один запрос на /api/search. Бейдж <span className="text-yellow-400">cache</span> = взяли из кеша parsers,
          {' '}<span className="text-green-400">network</span> = был свежий парсинг хотя бы одного магазина. Раскрывайте строки,
          чтобы увидеть выбранные магазины и ошибки.
        </div>
      </div>

      <input
        type="text"
        value={query}
        onChange={e => { setQuery(e.target.value); setPage(1) }}
        placeholder="Фильтр по запросу"
        title="LIKE %text% по сохранённой строке запроса"
        className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-violet-500"
      />

      {isLoading && <div className="text-sm text-gray-500 py-8 text-center">Загрузка…</div>}

      {!isLoading && items.length === 0
        ? <div className="text-sm text-gray-500 py-8 text-center">Журнал пуст. Запусти поиск на странице «Поиск».</div>
        : !isLoading && (
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

// ── Сводный health-блок наверху страницы ────────────────────────────────

function DatabaseSummary({ onJump }: { onJump: (t: Tab) => void }) {
  const meta = useQuery({ queryKey: ['parsers-db', 'meta'], queryFn: fetchParsersDbMeta })
  const stores = useQuery({ queryKey: ['stats-stores'], queryFn: fetchStatsStores })

  const storesArr = stores.data && !('_unavailable' in stores.data) ? (stores.data as StoreHealthEntry[]) : []
  const okStores = storesArr.filter(s => (s.success_rate_24h ?? 0) >= 90).length
  const totalStores = storesArr.length
  const products = meta.data?.tables?.products
  const observations = meta.data?.tables?.price_observations
  const sizeMb = meta.data?.db_size_mb

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <SummaryCard
        label="Парсеры"
        value={totalStores > 0 ? `${okStores} / ${totalStores}` : '—'}
        hint={totalStores > 0 ? `${okStores} ok из ${totalStores}` : 'нет данных'}
        ok={totalStores > 0 ? okStores === totalStores : null}
        onClick={() => onJump('stores')}
        tooltip="Сколько парсеров с success_rate ≥ 90% за последние 24 часа. Клик — на вкладку «Магазины»"
      />
      <SummaryCard
        label="Товары parsers"
        value={products != null ? products.toLocaleString('ru-RU') : '—'}
        hint="в кеше"
        onClick={() => onJump('parsers-inventory')}
        tooltip="Уникальных товаров в SQLite БД parsers. Клик — на «БД парсеров: inventory»"
      />
      <SummaryCard
        label="Точек цен"
        value={observations != null ? observations.toLocaleString('ru-RU') : '—'}
        hint="наблюдений"
        onClick={() => onJump('parsers-inventory')}
        tooltip="Записей в price_observations — каждый успешный парсинг добавляет точку"
      />
      <SummaryCard
        label="Размер БД"
        value={sizeMb != null ? `${sizeMb} MB` : '—'}
        hint="parsers SQLite"
        onClick={() => onJump('parsers-inventory')}
        tooltip="Размер файла data/prices.sqlite внутри parsers-контейнера"
      />
    </div>
  )
}

function SummaryCard({
  label, value, hint, ok, onClick, tooltip,
}: {
  label: string
  value: string
  hint?: string
  ok?: boolean | null
  onClick?: () => void
  tooltip?: string
}) {
  const indicator = ok == null ? null : ok
    ? <CheckCircle2 size={12} className="text-green-400" />
    : <XCircle size={12} className="text-red-400" />
  return (
    <button
      type="button"
      onClick={onClick}
      title={tooltip}
      className="text-left bg-gray-950/40 border border-gray-800 rounded p-3 space-y-1 hover:bg-gray-900/60 transition-colors"
    >
      <div className="flex items-center gap-1.5 text-xs text-gray-500">
        {label} {indicator}
      </div>
      <div className="text-base font-mono text-gray-100">{value}</div>
      {hint && <div className="text-[10px] text-gray-600">{hint}</div>}
    </button>
  )
}
