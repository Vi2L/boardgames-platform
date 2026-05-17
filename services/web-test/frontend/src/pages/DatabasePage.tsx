import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ProductDrawer } from '../components/search/ProductDrawer'
import {
  Database, Trash2, RefreshCw, AlertTriangle, ChevronLeft, ChevronRight,
  Clock, Info,
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
import { Tabs, Button, IconButton, Tag, StatusDot, Badge } from '../components/ui'

type Tab = 'products' | 'stores' | 'searches'
        | 'parsers-inventory' | 'parsers-products' | 'parsers-analytics' | 'parsers-charts'

const SORT_OPTIONS = [
  { value: 'fetched_desc', label: 'Свежие' },
  { value: 'price_asc',    label: 'Цена ↑' },
  { value: 'price_desc',   label: 'Цена ↓' },
  { value: 'title_asc',    label: 'А→Я' },
] as const

const PAGE_SIZE = 50

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'products', label: 'Товары портала' },
  { id: 'stores', label: 'Магазины' },
  { id: 'searches', label: 'Журнал' },
  { id: 'parsers-inventory', label: 'БД парсеров: inventory' },
  { id: 'parsers-products', label: 'БД парсеров: товары' },
  { id: 'parsers-analytics', label: 'БД парсеров: аналитика' },
  { id: 'parsers-charts', label: 'БД парсеров: графики' },
]

export function DatabasePage() {
  const [tab, setTab] = useState<Tab>('products')

  return (
    <div className="p-4 space-y-4 max-w-6xl">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
          <Database size={18} /> База данных
        </h1>
        <p className="text-xs text-zinc-500 mt-0.5">
          Локальный кеш дебаг-портала и статистика по парсерам
        </p>
      </div>

      <DatabaseSummary onJump={setTab} />

      <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
        <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
          <Tabs.List className="px-2">
            {TABS.map(t => (
              <Tabs.Trigger key={t.id} value={t.id}>{t.label}</Tabs.Trigger>
            ))}
          </Tabs.List>
          <div className="p-4">
            <Tabs.Content value="products"><ProductsTab /></Tabs.Content>
            <Tabs.Content value="stores"><StoresTab /></Tabs.Content>
            <Tabs.Content value="searches"><SearchesTab /></Tabs.Content>
            <Tabs.Content value="parsers-inventory"><InventoryTab /></Tabs.Content>
            <Tabs.Content value="parsers-products"><ProductsBrowserTab /></Tabs.Content>
            <Tabs.Content value="parsers-analytics"><AnalyticsTab /></Tabs.Content>
            <Tabs.Content value="parsers-charts"><ChartsTab /></Tabs.Content>
          </div>
        </Tabs>
      </div>
    </div>
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
      <InfoBox>
        <strong className="text-zinc-300">Локальный кеш товаров портала.</strong>
        {' '}Сюда попадает каждый товар, который пришёл в результатах поиска через web-test.
        Это «всё что когда-либо видели» — сравните с inventory parsers (свежее состояние БД parsers).
        Цена — в рублях, на момент последнего наблюдения. Клик по строке открывает карточку товара справа.
      </InfoBox>

      {/* Фильтры */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text"
          value={q}
          onChange={e => { setQ(e.target.value); setPage(1) }}
          placeholder="Поиск по названию"
          title="Поиск SQL LIKE %text% по названию товара (без учёта регистра)"
          className="flex-1 min-w-[200px] h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-indigo-500"
        />
        <select
          value={store}
          onChange={e => { setStore(e.target.value); setPage(1) }}
          title="Показывать товары только из выбранного магазина"
          className="h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
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
          className="h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <IconButton
          icon={RefreshCw}
          variant="ghost"
          size="sm"
          aria-label="Перезагрузить страницу из БД"
          title="Перезагрузить страницу из БД"
          loading={isFetching}
          onClick={() => refetch()}
        />
      </div>

      {/* Гистограмма */}
      {prices.length >= 2 && (
        <details className="bg-zinc-950/50 border border-zinc-800 rounded">
          <summary className="px-3 py-2 text-xs text-zinc-400 cursor-pointer hover:text-zinc-200 select-none">
            Распределение цен на текущей странице ({prices.length} товаров)
          </summary>
          <div className="p-3 pt-0">
            <PriceHistogram prices={prices} />
          </div>
        </details>
      )}

      {/* Список */}
      {isError && (
        <div className="text-sm text-rose-400 py-8 text-center">Ошибка загрузки</div>
      )}
      {!isError && isLoading && (
        <SkeletonList rows={5} />
      )}
      {!isError && !isLoading && items.length === 0 && (
        <div className="text-sm text-zinc-500 py-12 text-center">
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
    <div className="overflow-x-auto rounded border border-zinc-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900/80">
            <th className="px-3 py-2 text-left text-xs text-zinc-500 font-medium w-10" title="Внутренний ID товара в БД parsers">#</th>
            <th className="px-3 py-2 text-left text-xs text-zinc-500 font-medium">Магазин</th>
            <th className="px-3 py-2 text-left text-xs text-zinc-500 font-medium">Название</th>
            <th className="px-3 py-2 text-left text-xs text-zinc-500 font-medium whitespace-nowrap" title="Цена на момент последнего наблюдения, в рублях">Цена</th>
            <th className="px-3 py-2 text-left text-xs text-zinc-500 font-medium hidden md:table-cell" title="Когда товар последний раз попадал в результаты поиска">Обновлено</th>
            <th className="px-3 py-2 w-10"></th>
          </tr>
        </thead>
        <tbody>
          {items.map(p => (
            <tr
              key={p.id}
              className="border-b border-zinc-800/40 hover:bg-zinc-800/30 cursor-pointer"
              onClick={() => onSelect(p)}
            >
              <td className="px-3 py-2 text-xs text-zinc-600 font-mono">#{p.id}</td>
              <td className="px-3 py-2">
                <span className={clsx('px-2 py-0.5 rounded text-xs font-mono', getStoreBadgeColor(p.store_slug))} title={getStoreLabel(p.store_slug)}>
                  {p.store_slug}
                </span>
              </td>
              <td className="px-3 py-2 max-w-md">
                <span className="font-medium text-zinc-200 hover:text-indigo-300 truncate block" title={p.title}>
                  {p.title}
                </span>
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-emerald-400 font-semibold font-mono tabular-nums">
                {p.price_rub.toLocaleString('ru-RU')} ₽
              </td>
              <td
                className="px-3 py-2 text-xs text-zinc-500 whitespace-nowrap hidden md:table-cell"
                title={p.fetched_at}
              >
                {new Date(p.fetched_at).toLocaleDateString('ru-RU')}
              </td>
              <td className="px-3 py-2 text-right">
                <IconButton
                  icon={Trash2}
                  size="xs"
                  variant="ghost"
                  aria-label="Удалить из локальной БД"
                  title="Удалить из локальной БД"
                  onClick={e => { e.stopPropagation(); onDelete(p.id) }}
                />
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
    <div className="flex items-center justify-between text-xs text-zinc-500">
      <span>Всего: <span className="font-mono tabular-nums text-zinc-300">{total}</span></span>
      <div className="flex items-center gap-2">
        <IconButton
          icon={ChevronLeft}
          variant="ghost"
          size="xs"
          aria-label="Предыдущая страница"
          disabled={page === 1}
          onClick={() => onChange(Math.max(1, page - 1))}
        />
        <span className="font-mono tabular-nums text-zinc-400">{page} / {totalPages}</span>
        <IconButton
          icon={ChevronRight}
          variant="ghost"
          size="xs"
          aria-label="Следующая страница"
          disabled={page === totalPages}
          onClick={() => onChange(Math.min(totalPages, page + 1))}
        />
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
      <InfoBox
        action={
          <Button variant="secondary" size="xs" icon={RefreshCw} onClick={handleRefresh}>
            Обновить
          </Button>
        }
      >
        <strong className="text-zinc-300">Здоровье парсеров за последние 24 часа.</strong>
        {' '}Ok ≥ 90% успешных запросов, иначе красный значок. Сортировка — проблемные сначала.
        Время ответа = среднее по успешным вызовам, включая обогащение страниц товаров.
      </InfoBox>

      {isLoading && <div className="text-sm text-zinc-500 py-8 text-center">Загрузка…</div>}

      {!isLoading && data && '_unavailable' in data && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded p-4 text-sm">
          <div className="flex items-center gap-2 text-amber-300 mb-1">
            <AlertTriangle size={14} /> parsers stats недоступны
          </div>
          <div className="text-zinc-400 font-mono text-xs">{data._error}</div>
        </div>
      )}

      {!isLoading && (!data || (!('_unavailable' in data) && entries.length === 0)) && (
        <div className="text-sm text-zinc-500 py-8 text-center">
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
    <div className="bg-zinc-950/40 border border-zinc-800 rounded p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-zinc-200">{getStoreLabel(slug)}</span>
        <span title={ok ? '≥ 90% успешных вызовов' : 'Менее 90% успешных вызовов — есть деградация'}>
          <StatusDot status={ok ? 'done' : 'failed'} />
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div title="Доля успешных HTTP-вызовов парсера за 24 часа">
          <div className="text-zinc-500">Успешность</div>
          <div className={clsx('font-mono font-semibold tabular-nums', ok ? 'text-emerald-400' : 'text-rose-400')}>
            {successPct != null ? `${successPct.toFixed(1)}%` : '—'}
          </div>
        </div>
        <div title="Среднее время поиска (включая обогащение страниц товаров)">
          <div className="text-zinc-500 flex items-center gap-1">
            <Clock size={10} /> Среднее
          </div>
          <div className="font-mono text-zinc-300 tabular-nums">
            {avgMs != null ? formatMs(avgMs) : '—'}
          </div>
        </div>
        <div title={`Всего ${total} запросов за 24ч, из них ${failures} с ошибкой`}>
          <div className="text-zinc-500">Запросов</div>
          <div className="font-mono text-zinc-300 tabular-nums">
            {total.toLocaleString('ru-RU')}
            {failures > 0 && <span className="text-rose-400"> / {failures}↯</span>}
          </div>
        </div>
      </div>
      {stats.last_seen && (
        <div className="text-xxs text-zinc-500" title={`Последний вызов: ${stats.last_seen}`}>
          last seen: {stats.last_seen.slice(0, 16).replace('T', ' ')}
        </div>
      )}
      {lastError && (
        <div className="text-xs text-rose-300/70 font-mono truncate" title={lastError}>
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
      <InfoBox>
        <strong className="text-zinc-300">Журнал поисков через debug-портал.</strong>
        {' '}Каждая строка — один запрос на /api/search. Тег <Tag tone="warn">cache</Tag> = взяли из кеша parsers,
        {' '}<Tag tone="ok">network</Tag> = был свежий парсинг хотя бы одного магазина. Раскрывайте строки,
        чтобы увидеть выбранные магазины и ошибки.
      </InfoBox>

      <input
        type="text"
        value={query}
        onChange={e => { setQuery(e.target.value); setPage(1) }}
        placeholder="Фильтр по запросу"
        title="LIKE %text% по сохранённой строке запроса"
        className="w-full h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-indigo-500"
      />

      {isLoading && <div className="text-sm text-zinc-500 py-8 text-center">Загрузка…</div>}

      {!isLoading && items.length === 0
        ? <div className="text-sm text-zinc-500 py-8 text-center">Журнал пуст. Запусти поиск на странице «Поиск».</div>
        : !isLoading && (
          <div className="space-y-1.5">
            {items.map(s => {
              const sourceTone =
                s.source === 'cache' ? 'warn' :
                s.source === 'network' ? 'ok' :
                'neutral'
              return (
                <details key={s.id} className="bg-zinc-950/40 border border-zinc-800 rounded">
                  <summary className="px-3 py-2 text-sm cursor-pointer flex items-center gap-3 select-none">
                    <span className="text-zinc-200 font-medium">{s.query}</span>
                    <Tag tone={sourceTone}>{s.source ?? 'fail'}</Tag>
                    <span className="text-xs text-zinc-500 tabular-nums">{s.products_count} товаров</span>
                    {s.error_count > 0 && (
                      <Badge tone="danger" size="xs" dot={false}>ошибок: {s.error_count}</Badge>
                    )}
                    <span className="ml-auto text-xs text-zinc-600 tabular-nums">
                      {s.total_ms != null && `${s.total_ms}ms · `}
                      {new Date(s.created_at).toLocaleString('ru-RU')}
                    </span>
                  </summary>
                  <div className="px-3 pb-3 text-xs space-y-1 font-mono">
                    {s.stores && <div className="text-zinc-500">stores: <span className="text-zinc-300">{s.stores}</span></div>}
                    {s.errors_json && s.errors_json !== '{}' && (
                      <pre className="text-rose-300/70 whitespace-pre-wrap">{s.errors_json}</pre>
                    )}
                  </div>
                </details>
              )
            })}
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
  return (
    <button
      type="button"
      onClick={onClick}
      title={tooltip}
      className="text-left bg-zinc-950/40 border border-zinc-800 rounded p-3 space-y-1 hover:bg-zinc-900/60 transition-colors"
    >
      <div className="flex items-center gap-1.5 text-xs text-zinc-500">
        {label}
        {ok != null && <StatusDot status={ok ? 'done' : 'failed'} />}
      </div>
      <div className="text-base font-mono text-zinc-100 tabular-nums">{value}</div>
      {hint && <div className="text-xxs text-zinc-600">{hint}</div>}
    </button>
  )
}

// ── Shared bits ───────────────────────────────────────────────────────────

function InfoBox({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 px-3 py-2 rounded bg-zinc-950/40 border border-zinc-800 text-xs text-zinc-400">
      <Info size={13} className="text-indigo-400 flex-shrink-0 mt-0.5" />
      <div className="flex-1">{children}</div>
      {action}
    </div>
  )
}
