/**
 * CatalogPage — UI поверх boardgames-catalog (~/Projects/boardgames-catalog).
 *
 * Две секции:
 * 1. «Каталог»  — поиск + список Game (pg_trgm fuzzy через q).
 * 2. «Матчинг»  — очередь unmatched-оффер'ов с действиями [Связать]/[Отклонить].
 *
 * Намеренно простой layout (без drag&drop / modal'ок): прототип ручного
 * матчинга, нагружать визуалом будем по мере живого использования.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient, useMutation, useInfiniteQuery } from '@tanstack/react-query'
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef as TanColumnDef,
  type ColumnSizingState,
} from '@tanstack/react-table'
import { toast } from 'sonner'
import { useEffect } from 'react'
import {
  fetchCatalogHealth,
  fetchMatchCandidates,
  fetchMatchingQueue,
  fetchMatchingStats,
  linkOffer,
  listCatalogGames,
  reassessAll,
  reassessOffer,
  rejectOffer,
  type CatalogGame,
  type CatalogOffer,
  type MatchCandidate,
} from '../lib/catalog'
import { GameDetailDrawer } from '../components/catalog/GameDetailDrawer'
import { ImportWizard } from '../components/catalog/ImportWizard'
import { GameEditor } from '../components/catalog/GameEditor'
import { MatchingStatsHeader } from '../components/catalog/MatchingStatsHeader'
import { BackupButton } from '../components/catalog/BackupButton'
import { PromotionPanel } from '../components/catalog/PromotionPanel'
import { BggImportPanel } from '../components/catalog/BggImportPanel'
import { MatchLogTab } from '../components/catalog/MatchLogTab'
import { useCatalogTableStore } from '../store/catalog'
import { SuggestInput } from '../components/shared/SuggestInput'
import { useSearchHistory } from '../lib/searchHistory'
import { Download, Plus, Settings2 } from 'lucide-react'

type Tab = 'catalog' | 'matching' | 'match-log' | 'promotion' | 'bgg'

export function CatalogPage() {
  const [tab, setTab] = useState<Tab>('catalog')
  const [showImport, setShowImport] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const health = useQuery({
    queryKey: ['catalog', 'health'],
    queryFn: fetchCatalogHealth,
    refetchInterval: 30_000,
    retry: 0,
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-100">Каталог настольных игр</h1>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-emerald-700 hover:bg-emerald-600 text-white rounded"
          >
            <Plus size={12} /> Новая игра
          </button>
          <button
            type="button"
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 text-white rounded"
          >
            <Download size={12} /> Импорт BGG / Tesera
          </button>
          <BackupButton />
          <div className="text-xs text-gray-400">
            catalog: {health.isError ? <span className="text-red-400">недоступен</span> :
              health.data ? <span className="text-emerald-400">{health.data.status}</span> :
              <span>...</span>}
          </div>
        </div>
      </div>
      {showImport && <ImportWizard onClose={() => setShowImport(false)} />}
      {showCreate && <GameEditor mode="create" onClose={() => setShowCreate(false)} />}

      <div className="flex gap-2 border-b border-gray-800">
        {(['catalog', 'matching', 'match-log', 'promotion', 'bgg'] as Tab[]).map(t => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm transition-colors ${
              tab === t
                ? 'text-violet-300 border-b-2 border-violet-500'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {t === 'catalog' ? 'Каталог'
              : t === 'matching' ? 'Очередь матчинга'
              : t === 'match-log' ? 'Журнал матчинга'
              : t === 'promotion' ? 'Промоушен Dicefest'
              : 'BGG'}
          </button>
        ))}
      </div>

      {tab === 'catalog'  ? <CatalogSection />
        : tab === 'matching' ? <MatchingSection />
        : tab === 'match-log' ? <MatchLogTab />
        : tab === 'promotion' ? <PromotionPanel provider="dicefest" />
        : <BggImportPanel />}
    </div>
  )
}

// ─── Каталог ──────────────────────────────────────────────────────────────

// Пагинация через useInfiniteQuery: классический "Показать ещё" — каждый
// fetchNextPage добавляет ещё PAGE_SIZE результатов к предыдущим страницам.
// Для UX каталога это естественнее, чем нумерация: пользователь обычно ищет
// конкретную игру, остановится как только найдёт.
const PAGE_SIZE = 50

// Декларативный список колонок таблицы каталога. id используется как
// стабильный ключ для useCatalogTableStore (persist → localStorage), label —
// заголовок <th>, render — содержимое ячейки. defaultVisible определяет,
// какие колонки попадают в дефолтный набор после resetColumns(). defaultSize
// — стартовая ширина в пикселях; пользователь меняет её drag'ом за правый
// край th (TanStack columnResizeMode='onChange'), результат складывается в
// store.columnSizes.
type LocalColumnDef = {
  id: string
  label: string
  render: (g: CatalogGame) => ReactNode
  defaultVisible: boolean
  defaultSize: number
  cellClass?: string
}

const COLUMNS: LocalColumnDef[] = [
  {
    id: 'id', label: 'id', defaultVisible: true, defaultSize: 60,
    cellClass: 'font-mono text-xs text-gray-500',
    render: g => g.id,
  },
  {
    id: 'slug', label: 'slug', defaultVisible: true, defaultSize: 180,
    cellClass: 'font-mono text-xs text-gray-400 truncate',
    render: g => g.slug,
  },
  {
    id: 'title', label: 'title', defaultVisible: true, defaultSize: 280,
    cellClass: 'text-gray-100 truncate',
    render: g => g.title,
  },
  {
    id: 'title_ru', label: 'RU название', defaultVisible: true, defaultSize: 240,
    cellClass: 'text-gray-200 truncate',
    render: g => g.title_ru ?? <span className="text-gray-600">—</span>,
  },
  {
    id: 'year', label: 'year', defaultVisible: true, defaultSize: 70,
    cellClass: 'text-gray-300',
    render: g => g.year ?? '—',
  },
  {
    id: 'source', label: 'source', defaultVisible: true, defaultSize: 90,
    render: g => <SourceBadge source={g.source} />,
  },
  {
    id: 'bgg_tesera', label: 'BGG / Tesera', defaultVisible: true, defaultSize: 160,
    cellClass: 'text-xs text-gray-400',
    render: g => (
      <>
        {g.bgg_id && <span title="BGG">BGG#{g.bgg_id}</span>}
        {g.bgg_id && g.tesera_id && ' · '}
        {g.tesera_id && <span title="Tesera">T#{g.tesera_id}</span>}
        {!g.bgg_id && !g.tesera_id && '—'}
      </>
    ),
  },
  {
    id: 'kind', label: 'kind', defaultVisible: false, defaultSize: 100,
    cellClass: 'text-xs text-gray-300',
    render: g => g.kind,
  },
  {
    id: 'parent_game_id', label: 'parent', defaultVisible: false, defaultSize: 80,
    cellClass: 'font-mono text-xs text-gray-400',
    render: g => g.parent_game_id ?? '—',
  },
  {
    id: 'ru_publisher', label: 'ru_publisher', defaultVisible: false, defaultSize: 160,
    cellClass: 'text-xs text-gray-300 truncate',
    render: g => g.ru_publisher ?? '—',
  },
  {
    id: 'ru_release_year', label: 'ru_year', defaultVisible: false, defaultSize: 80,
    cellClass: 'text-xs text-gray-300',
    render: g => g.ru_release_year ?? '—',
  },
  {
    id: 'is_localized_ru', label: 'RU?', defaultVisible: false, defaultSize: 60,
    cellClass: 'text-center text-xs',
    render: g => g.is_localized_ru
      ? <span className="text-emerald-400">✓</span>
      : <span className="text-gray-600">—</span>,
  },
  {
    id: 'preorder_price', label: 'preorder', defaultVisible: false, defaultSize: 100,
    cellClass: 'text-xs text-gray-300 text-right',
    // preorder_price хранится в копейках — конвертим в рубли для отображения,
    // как и везде в UI портала (см. правило в корневом CLAUDE.md).
    render: g => g.preorder_price != null ? `${(g.preorder_price / 100).toFixed(0)} ₽` : '—',
  },
  {
    id: 'status', label: 'status', defaultVisible: false, defaultSize: 100,
    cellClass: 'text-xs text-gray-400',
    render: g => g.status,
  },
  {
    id: 'dicefest_id', label: 'dicefest', defaultVisible: false, defaultSize: 90,
    cellClass: 'font-mono text-xs text-gray-400',
    render: g => g.dicefest_id ?? '—',
  },
  {
    id: 'nastolio_id', label: 'nastolio', defaultVisible: false, defaultSize: 100,
    cellClass: 'font-mono text-xs text-gray-400',
    render: g => g.nastolio_id ?? '—',
  },
  {
    id: 'cover_url', label: 'cover', defaultVisible: false, defaultSize: 64,
    render: g => g.cover_url
      ? <img src={g.cover_url} alt="" className="w-8 h-8 object-cover rounded" />
      : <span className="text-gray-600 text-xs">—</span>,
  },
]

const ALL_COLUMN_IDS = COLUMNS.map(c => c.id)

function CatalogSection() {
  const [q, setQ] = useState('')
  // История запросов отдельная от /search — здесь юзер ищет канонические
  // игры в каталоге, не товары в магазинах. push'аем при ручном Enter.
  const { push: pushHistory } = useSearchHistory('catalog')
  const [openId, setOpenId] = useState<number | null>(null)
  const visibleColumnIds = useCatalogTableStore(s => s.visibleColumns)
  const columnSizes = useCatalogTableStore(s => s.columnSizes)
  const setColumnSize = useCatalogTableStore(s => s.setColumnSize)

  // Колонки, которые реально показываются: фильтруем декларацию COLUMNS
  // по сохранённому visibleColumns. При пустом сторе (первый заход или
  // сброс мусора) откатываемся на defaultVisible.
  const renderedColumns = useMemo(() => {
    const visible = COLUMNS.filter(c => visibleColumnIds.includes(c.id))
    return visible.length > 0 ? visible : COLUMNS.filter(c => c.defaultVisible)
  }, [visibleColumnIds])

  const games = useInfiniteQuery({
    queryKey: ['catalog', 'games', q],
    queryFn: ({ pageParam }) =>
      listCatalogGames(q || undefined, PAGE_SIZE, pageParam),
    initialPageParam: 0,
    // Если уже подгружено столько же или больше, чем total — следующих страниц нет.
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.items.length, 0)
      return loaded < lastPage.total ? loaded : undefined
    },
  })

  // flatMap собирает все загруженные страницы в один массив для рендера.
  const items = useMemo(
    () => games.data?.pages.flatMap(p => p.items) ?? [],
    [games.data],
  )
  const total = games.data?.pages[0]?.total ?? 0
  const remaining = Math.max(0, total - items.length)

  // Адаптер LocalColumnDef → TanStack ColumnDef.
  const tanColumns = useMemo<TanColumnDef<CatalogGame>[]>(
    () => renderedColumns.map(c => ({
      id: c.id,
      header: c.label,
      cell: ({ row }) => c.render(row.original),
      size: columnSizes[c.id] ?? c.defaultSize,
      minSize: 40,
      maxSize: 800,
      meta: { cellClass: c.cellClass },
    })),
    [renderedColumns, columnSizes],
  )

  // TanStack хранит ширины во внутреннем state. На каждый change синхронизируем
  // в zustand-стор (persist → localStorage). Используем функциональную форму
  // setState, потому что react-table передаёт `updater` как функцию.
  const handleSizingChange = (
    updater: ColumnSizingState | ((prev: ColumnSizingState) => ColumnSizingState),
  ) => {
    const prev = columnSizes
    const next = typeof updater === 'function'
      ? (updater as (p: ColumnSizingState) => ColumnSizingState)(prev)
      : updater
    for (const id of Object.keys(next)) {
      if (next[id] !== prev[id]) setColumnSize(id, next[id])
    }
  }

  const table = useReactTable({
    data: items,
    columns: tanColumns,
    getCoreRowModel: getCoreRowModel(),
    columnResizeMode: 'onChange',
    state: { columnSizing: columnSizes },
    onColumnSizingChange: handleSizingChange,
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <SuggestInput
          value={q}
          onChange={setQ}
          onSubmit={() => { if (q.trim()) pushHistory(q) }}
          historyKey="catalog"
          placeholder="Поиск по названиям (RU/EN aliases + fuzzy)"
          className="flex-1"
        />
        <ColumnsPicker />
      </div>
      {games.isError && (
        <div className="text-sm text-red-400">Не удалось получить каталог: {String(games.error)}</div>
      )}
      <div className="text-xs text-gray-500">
        {games.isLoading
          ? 'загрузка...'
          : `показано ${items.length} из ${total} игр`}
      </div>
      <div className="border border-gray-800 rounded overflow-x-auto">
        <table
          className="text-sm"
          style={{ width: table.getCenterTotalSize(), tableLayout: 'fixed' }}
        >
          <thead className="bg-gray-900 text-gray-400 text-left select-none">
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map(header => (
                  <th
                    key={header.id}
                    style={{ width: header.getSize() }}
                    className="relative px-3 py-2 truncate"
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {/* Resize-handle: 4px полоска у правого края, drag меняет ширину
                        в реальном времени (columnResizeMode='onChange'). */}
                    <div
                      onMouseDown={header.getResizeHandler()}
                      onTouchStart={header.getResizeHandler()}
                      className={`absolute top-0 right-0 h-full w-1 cursor-col-resize select-none touch-none ${
                        header.column.getIsResizing()
                          ? 'bg-violet-500'
                          : 'bg-transparent hover:bg-violet-700/60'
                      }`}
                    />
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-gray-800">
            {table.getRowModel().rows.map(row => (
              <tr
                key={row.id}
                className="hover:bg-gray-900 cursor-pointer"
                onClick={() => setOpenId(row.original.id)}
              >
                {row.getVisibleCells().map(cell => {
                  const meta = cell.column.columnDef.meta as
                    | { cellClass?: string } | undefined
                  return (
                    <td
                      key={cell.id}
                      style={{ width: cell.column.getSize() }}
                      className={`px-3 py-2 truncate ${meta?.cellClass ?? ''}`}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  )
                })}
              </tr>
            ))}
            {!games.isLoading && items.length === 0 && (
              <tr><td colSpan={renderedColumns.length} className="px-3 py-6 text-center text-gray-500">
                Нет игр {q && <>по запросу «{q}»</>}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {games.hasNextPage && (
        <button
          type="button"
          onClick={() => games.fetchNextPage()}
          disabled={games.isFetchingNextPage}
          className="w-full px-3 py-2 text-sm bg-gray-900 hover:bg-gray-800 border border-gray-800 rounded text-gray-300 disabled:opacity-50"
        >
          {games.isFetchingNextPage
            ? 'загрузка…'
            : `Показать ещё (осталось ${remaining})`}
        </button>
      )}

      {openId !== null && (
        <GameDetailDrawer gameId={openId} onClose={() => setOpenId(null)} />
      )}
    </div>
  )
}

// Popover-меню выбора видимых колонок таблицы каталога. Паттерн повторяет
// HealthPopover (components/shared/HealthBadge.tsx): fixed-overlay ловит клик
// мимо, absolute-контейнер позиционируется под кнопкой. Без сторонних
// dropdown-библиотек — в портале их нет.
function ColumnsPicker() {
  const [open, setOpen] = useState(false)
  const visible = useCatalogTableStore(s => s.visibleColumns)
  const toggle = useCatalogTableStore(s => s.toggleColumn)
  const reset = useCatalogTableStore(s => s.resetColumns)
  const showAll = useCatalogTableStore(s => s.showAllColumns)
  const resetSizes = useCatalogTableStore(s => s.resetColumnSizes)

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        title="Выбрать видимые колонки"
        className="flex items-center gap-1 px-2 py-1 text-xs bg-gray-900 hover:bg-gray-800 border border-gray-700 rounded text-gray-200"
      >
        <Settings2 size={12} /> Колонки
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-full mt-1 z-50 w-64 bg-gray-900 border border-gray-700 rounded shadow-lg p-2 max-h-96 overflow-y-auto">
            <div className="text-xs text-gray-500 px-2 py-1 mb-1">
              Видимые колонки таблицы
            </div>
            {COLUMNS.map(c => (
              <label
                key={c.id}
                className="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-800 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={visible.includes(c.id)}
                  onChange={() => toggle(c.id)}
                  className="accent-violet-500"
                />
                <span className="text-sm text-gray-200">{c.label}</span>
                <span className="ml-auto text-[10px] font-mono text-gray-500">{c.id}</span>
              </label>
            ))}
            <div className="flex gap-2 mt-2 pt-2 border-t border-gray-800 px-2">
              <button
                type="button"
                onClick={() => reset()}
                className="flex-1 px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 rounded"
              >
                Сбросить
              </button>
              <button
                type="button"
                onClick={() => showAll(ALL_COLUMN_IDS)}
                className="flex-1 px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 rounded"
              >
                Все
              </button>
            </div>
            <button
              type="button"
              onClick={() => resetSizes()}
              className="w-full mt-2 px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded"
              title="Вернуть стандартные ширины колонок"
            >
              Сбросить ширины
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function SourceBadge({ source }: { source: string }) {
  const colors: Record<string, string> = {
    manual: 'bg-gray-800 text-gray-300',
    bgg: 'bg-orange-900/50 text-orange-300',
    tesera: 'bg-blue-900/50 text-blue-300',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${colors[source] || 'bg-gray-800 text-gray-300'}`}>
      {source}
    </span>
  )
}

// ─── Очередь матчинга: split-view ────────────────────────────────────────────

type BucketFilter = 'good' | 'candidate' | 'cold'

function MatchingSection() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [storeFilter, setStoreFilter] = useState<string | undefined>(undefined)
  const [bucketFilter, setBucketFilter] = useState<BucketFilter | undefined>(undefined)
  const [limit, setLimit] = useState(50)
  const [selectedSet, setSelectedSet] = useState<Set<number>>(new Set())

  const stats = useQuery({
    queryKey: ['catalog', 'matching-stats'],
    queryFn: fetchMatchingStats,
    refetchInterval: 30_000,
  })

  const queue = useQuery({
    queryKey: ['catalog', 'matching-queue', storeFilter, limit],
    queryFn: () => fetchMatchingQueue(storeFilter, limit, 0),
  })

  const AUTO = stats.data?.thresholds.auto ?? 0.6
  const CAND = stats.data?.thresholds.candidate ?? 0.3

  // Bucket-фильтрация на клиенте — data уже отсортирована was_linked.desc() сервером
  const filteredItems = useMemo(() => {
    if (!queue.data?.items) return []
    if (!bucketFilter) return queue.data.items
    return queue.data.items.filter(o => {
      const s = o.match_score
      if (bucketFilter === 'good') return s != null && s >= AUTO
      if (bucketFilter === 'candidate') return s != null && s >= CAND && s < AUTO
      return s == null || s < CAND
    })
  }, [queue.data?.items, bucketFilter, AUTO, CAND])

  const returnedItems = filteredItems.filter(o => o.was_linked)
  const regularItems = filteredItems.filter(o => !o.was_linked)
  const selectedOffer = filteredItems.find(o => o.id === selectedId) ?? null

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['catalog', 'matching-queue'] })
    queryClient.invalidateQueries({ queryKey: ['catalog', 'matching-stats'] })
  }

  const reassessBatch = useMutation({
    mutationFn: () => reassessAll({ store: storeFilter }),
    onSuccess: (r) => {
      toast.success(
        `Пересчитано ${r.scanned}: → auto ${r.promoted_to_auto}, ` +
        `улучшено ${r.score_improved}, без изм. ${r.unchanged}`,
      )
      invalidateAll()
    },
    onError: (e) => toast.error(`Batch reassess failed: ${e}`),
  })

  const batchReject = useMutation({
    mutationFn: async () => {
      const ids = Array.from(selectedSet)
      await Promise.all(ids.map(id => rejectOffer(id)))
      return ids.length
    },
    onSuccess: (count) => {
      toast.success(`Отклонено ${count} офферов`)
      setSelectedSet(new Set())
      invalidateAll()
    },
    onError: (e) => toast.error(`Ошибка: ${e}`),
  })

  const toggleSelect = (id: number) =>
    setSelectedSet(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const stores = stats.data?.by_store ?? []

  return (
    <div className="space-y-3">
      <MatchingStatsHeader />

      <div className="flex gap-3" style={{ minHeight: '580px' }}>
        {/* ── Левая панель ─────────────────────────────── */}
        <div className="w-[40%] flex flex-col gap-2 min-w-0">

          {/* Store tabs */}
          <div className="flex flex-wrap gap-1">
            <button
              onClick={() => { setStoreFilter(undefined); setSelectedId(null) }}
              className={`px-2 py-0.5 text-xs rounded ${!storeFilter ? 'bg-violet-700 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
            >
              все
            </button>
            {stores.map(s => (
              <button
                key={s.store_slug}
                onClick={() => { setStoreFilter(s.store_slug); setSelectedId(null) }}
                className={`px-2 py-0.5 text-xs rounded ${storeFilter === s.store_slug ? 'bg-violet-700 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
              >
                {s.store_slug} <span className="opacity-60">{s.total}</span>
              </button>
            ))}
          </div>

          {/* Bucket filter */}
          <div className="flex gap-1">
            {(['good', 'candidate', 'cold'] as BucketFilter[]).map(b => (
              <button
                key={b}
                onClick={() => setBucketFilter(bucketFilter === b ? undefined : b)}
                className={`px-2 py-0.5 text-xs rounded ${bucketFilter === b
                  ? b === 'good' ? 'bg-emerald-700 text-white'
                    : b === 'candidate' ? 'bg-amber-700 text-white'
                    : 'bg-gray-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
              >
                {b} {stats.data?.by_bucket[b] ?? ''}
              </button>
            ))}
          </div>

          {/* Offer list */}
          <div className="flex-1 border border-gray-800 rounded overflow-y-auto">
            {/* Группа «Возвращены» */}
            {returnedItems.length > 0 && (
              <div>
                <div className="px-2 py-1 text-[10px] uppercase tracking-wide text-amber-400 bg-amber-900/10 border-b border-amber-900/30 flex items-center gap-1">
                  <span>⚠</span> Возвращены из матчинга ({returnedItems.length})
                </div>
                {returnedItems.map(o => (
                  <QueueOfferRow
                    key={o.id}
                    offer={o}
                    selected={selectedId === o.id}
                    checked={selectedSet.has(o.id)}
                    onSelect={() => setSelectedId(o.id)}
                    onToggleCheck={() => toggleSelect(o.id)}
                    autoThreshold={AUTO}
                  />
                ))}
                <div className="border-t border-gray-800" />
              </div>
            )}

            {/* Основная очередь */}
            {regularItems.map(o => (
              <QueueOfferRow
                key={o.id}
                offer={o}
                selected={selectedId === o.id}
                checked={selectedSet.has(o.id)}
                onSelect={() => setSelectedId(o.id)}
                onToggleCheck={() => toggleSelect(o.id)}
                autoThreshold={AUTO}
              />
            ))}

            {filteredItems.length === 0 && !queue.isLoading && (
              <div className="px-3 py-8 text-center text-xs text-gray-500">
                {queue.data?.total === 0
                  ? 'Очередь пуста — все офферы сматчены.'
                  : 'Нет офферов по текущему фильтру.'}
              </div>
            )}

            {queue.isLoading && (
              <div className="px-3 py-4 text-center text-xs text-gray-500">загрузка…</div>
            )}
          </div>

          {/* Footer: load more + batch actions */}
          <div className="flex items-center gap-2 flex-wrap">
            {queue.data && queue.data.total > limit && (
              <button
                onClick={() => setLimit(l => l + 50)}
                className="px-2 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700"
              >
                Загрузить ещё ({queue.data.total - filteredItems.length} скрыто)
              </button>
            )}
            {selectedSet.size > 0 && (
              <button
                onClick={() => {
                  if (window.confirm(`Отклонить ${selectedSet.size} офферов?`))
                    batchReject.mutate()
                }}
                disabled={batchReject.isPending}
                className="px-2 py-1 text-xs bg-red-900/60 text-red-200 rounded hover:bg-red-900 disabled:opacity-40"
              >
                {batchReject.isPending ? '…' : `Отклонить ${selectedSet.size}`}
              </button>
            )}
            <button
              onClick={() => {
                if (window.confirm(
                  'Запустить batch-reassess?\nПересчитает find_best_match для всех unmatched в текущем фильтре.',
                )) reassessBatch.mutate()
              }}
              disabled={reassessBatch.isPending}
              className="ml-auto px-2 py-1 text-xs bg-violet-800/60 text-violet-200 rounded hover:bg-violet-700 disabled:opacity-40"
            >
              {reassessBatch.isPending ? 'Пересчёт…' : 'Reassess всё'}
            </button>
          </div>
        </div>

        {/* ── Правая панель ────────────────────────────── */}
        <div className="flex-1 min-w-0 border border-gray-800 rounded">
          {selectedOffer
            ? (
              <MatchingOfferDetail
                key={selectedOffer.id}
                offer={selectedOffer}
                autoThreshold={AUTO}
                candidateThreshold={CAND}
                onLinked={() => { invalidateAll(); setSelectedId(null) }}
                onRejected={() => { invalidateAll(); setSelectedId(null) }}
                onReassessed={invalidateAll}
              />
            )
            : (
              <div className="h-full flex items-center justify-center text-sm text-gray-500">
                Выбери оффер слева для матчинга
              </div>
            )}
        </div>
      </div>
    </div>
  )
}

// ─── Строка в левой панели очереди ───────────────────────────────────────────

function QueueOfferRow({
  offer, selected, checked, onSelect, onToggleCheck, autoThreshold,
}: {
  offer: CatalogOffer
  selected: boolean
  checked: boolean
  onSelect: () => void
  onToggleCheck: () => void
  autoThreshold: number
}) {
  const scoreColor = offer.match_score == null ? 'text-gray-600'
    : offer.match_score >= autoThreshold ? 'text-emerald-400'
    : offer.match_score >= 0.3 ? 'text-amber-400'
    : 'text-gray-500'

  return (
    <div
      onClick={onSelect}
      className={`flex items-start gap-2 px-2 py-1.5 border-b border-gray-800/60 cursor-pointer transition-colors ${
        selected ? 'bg-violet-900/30' : 'hover:bg-gray-900'
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onClick={e => e.stopPropagation()}
        onChange={onToggleCheck}
        className="mt-0.5 shrink-0 accent-violet-500"
      />
      <div className="flex-1 min-w-0">
        <div className="text-xs text-gray-200 truncate" title={offer.title_raw}>
          {offer.title_raw}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] font-mono text-gray-500">{offer.store_slug}</span>
          {offer.last_price != null && (
            <span className="text-[10px] text-gray-400">
              {(offer.last_price / 100).toFixed(0)} ₽
            </span>
          )}
        </div>
      </div>
      <span className={`text-[10px] font-mono shrink-0 ${scoreColor}`}>
        {offer.match_score != null ? offer.match_score.toFixed(2) : '—'}
      </span>
    </div>
  )
}

// ─── Правая панель: детали оффера + кандидаты ────────────────────────────────

function MatchingOfferDetail({
  offer, autoThreshold, candidateThreshold, onLinked, onRejected, onReassessed,
}: {
  offer: CatalogOffer
  autoThreshold: number
  candidateThreshold: number
  onLinked: () => void
  onRejected: () => void
  onReassessed: () => void
}) {
  const [q, setQ] = useState(offer.title_raw)
  const [debouncedQ, setDebouncedQ] = useState(offer.title_raw)

  // Сброс поиска при смене оффера (key на компоненте сделает remount,
  // но на всякий случай синхронизируем вручную)
  useEffect(() => {
    setQ(offer.title_raw)
    setDebouncedQ(offer.title_raw)
  }, [offer.id, offer.title_raw])

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300)
    return () => clearTimeout(t)
  }, [q])

  const candidates = useQuery({
    queryKey: ['catalog', 'match-candidates', debouncedQ],
    queryFn: () => fetchMatchCandidates(debouncedQ, 20),
    enabled: debouncedQ.trim().length > 0,
    staleTime: 30_000,
  })

  const link = useMutation({
    mutationFn: (gameId: number) => linkOffer(offer.id, gameId),
    onSuccess: () => { toast.success('Оффер связан с игрой'); onLinked() },
    onError: (e) => toast.error(`Не удалось связать: ${e}`),
  })

  const reject = useMutation({
    mutationFn: () => rejectOffer(offer.id),
    onSuccess: () => { toast.success('Оффер отклонён'); onRejected() },
    onError: (e) => toast.error(`Ошибка: ${e}`),
  })

  const reassess = useMutation({
    mutationFn: () => reassessOffer(offer.id),
    onSuccess: (o) => {
      const status = o.match_status === 'auto' ? 'auto ✓' : 'unmatched'
      toast.success(`#${o.id} → ${status} (score ${o.match_score?.toFixed(2) ?? '—'})`)
      onReassessed()
    },
    onError: (e) => toast.error(`Reassess failed: ${e}`),
  })

  const items: MatchCandidate[] = candidates.data?.items ?? []
  const isPending = link.isPending || reject.isPending || reassess.isPending

  return (
    <div className="flex flex-col h-full p-3 gap-3">
      {/* Хедер оффера */}
      <div className="space-y-1">
        <div className="flex items-start justify-between gap-2">
          <div className="text-sm text-gray-100 font-medium leading-tight">{offer.title_raw}</div>
          <a href={offer.url} target="_blank" rel="noreferrer"
             className="text-gray-500 hover:text-gray-200 shrink-0 mt-0.5">
            <span className="text-[10px]">↗</span>
          </a>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-gray-500">
          <span className="font-mono">{offer.store_slug}</span>
          {offer.last_price != null && (
            <span>{(offer.last_price / 100).toFixed(0)} ₽</span>
          )}
          {offer.match_score != null && (
            <span className={
              offer.match_score >= autoThreshold ? 'text-emerald-400'
              : offer.match_score >= candidateThreshold ? 'text-amber-400'
              : 'text-gray-500'
            }>
              score {offer.match_score.toFixed(2)}
            </span>
          )}
          {offer.was_linked && (
            <span className="px-1 rounded bg-amber-900/40 text-amber-300">⚠ был привязан</span>
          )}
        </div>
      </div>

      {/* Поиск кандидатов */}
      <div className="space-y-1.5">
        <div className="text-[10px] uppercase tracking-wide text-gray-500">Поиск по каталогу</div>
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          className="w-full px-2 py-1.5 text-xs bg-gray-900 border border-gray-700 rounded text-gray-200 focus:border-violet-500 outline-none"
          placeholder="Название для поиска..."
        />
      </div>

      {/* Кандидаты */}
      <div className="flex-1 overflow-y-auto space-y-0.5 min-h-0">
        {candidates.isLoading && (
          <div className="text-xs text-gray-500 text-center py-2">поиск…</div>
        )}
        {items.map(c => (
          <button
            key={c.game_id}
            type="button"
            disabled={isPending}
            onClick={() => link.mutate(c.game_id)}
            className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-800 disabled:opacity-50 transition-colors"
          >
            <ScoreBadge score={c.score} auto={autoThreshold} via={c.via} />
            <span className="text-xs text-gray-200 truncate flex-1">{c.title}</span>
            {c.year != null && <span className="text-[10px] text-gray-500 shrink-0">{c.year}</span>}
            {c.bgg_id && (
              <span className="text-[10px] text-orange-300/70 shrink-0 font-mono">BGG#{c.bgg_id}</span>
            )}
          </button>
        ))}
        {!candidates.isLoading && items.length === 0 && debouncedQ.trim() && (
          <div className="text-xs text-gray-500 italic px-2 py-2">
            Кандидатов нет. Импортируй из BGG/Tesera или создай вручную.
          </div>
        )}
      </div>

      {/* Действия */}
      <div className="flex gap-2 pt-2 border-t border-gray-800">
        <button
          type="button"
          onClick={() => {
            if (window.confirm(`Отклонить «${offer.title_raw}»?`)) reject.mutate()
          }}
          disabled={isPending}
          className="px-3 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-40"
        >
          Отклонить
        </button>
        <button
          type="button"
          onClick={() => reassess.mutate()}
          disabled={isPending}
          title="Пересчитать score (после правки алиасов / импорта BGG)"
          className="px-3 py-1 text-xs bg-amber-900/50 text-amber-200 rounded hover:bg-amber-900 disabled:opacity-40"
        >
          {reassess.isPending ? '…' : 'Reassess ↻'}
        </button>
      </div>
    </div>
  )
}

function ScoreBadge({ score, auto, via }: { score: number; auto: number; via: 'title' | 'alias' }) {
  const cls = score >= auto
    ? 'bg-emerald-900/60 text-emerald-200'
    : score >= 0.5
      ? 'bg-amber-900/60 text-amber-200'
      : 'bg-gray-800 text-gray-400'
  return (
    <span
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono shrink-0 ${cls}`}
      title={`similarity по ${via === 'title' ? 'title канона' : 'алиасу'}`}
    >
      {score.toFixed(2)}
      <span className="opacity-60 uppercase">{via}</span>
    </span>
  )
}
