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
import { Download, Plus, Settings2, CheckCircle2 } from 'lucide-react'
import { Tabs, Button, Badge } from '../components/ui'

type Tab = 'catalog' | 'matching' | 'match-log' | 'promotion' | 'bgg'

const TAB_LABELS: Record<Tab, string> = {
  'catalog':    'Каталог',
  'matching':   'Очередь матчинга',
  'match-log':  'Журнал матчинга',
  'promotion':  'Промоушен Dicefest',
  'bgg':        'BGG',
}

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
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-100">Каталог настольных игр</h1>
        <div className="flex items-center gap-3">
          <Button variant="success" size="sm" icon={Plus} onClick={() => setShowCreate(true)}>
            Новая игра
          </Button>
          <Button variant="primary" size="sm" icon={Download} onClick={() => setShowImport(true)}>
            Импорт BGG / Tesera
          </Button>
          <BackupButton />
          <div className="text-xs text-zinc-400 flex items-center gap-1.5">
            catalog:
            {health.isError ? <Badge status="failed" size="xs">недоступен</Badge> :
              health.data ? <Badge status="done" size="xs">{health.data.status}</Badge> :
              <span>...</span>}
          </div>
        </div>
      </div>
      {showImport && <ImportWizard onClose={() => setShowImport(false)} />}
      {showCreate && <GameEditor mode="create" onClose={() => setShowCreate(false)} />}

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <Tabs.List>
          {(['catalog', 'matching', 'match-log', 'promotion', 'bgg'] as Tab[]).map(t => (
            <Tabs.Trigger key={t} value={t}>{TAB_LABELS[t]}</Tabs.Trigger>
          ))}
        </Tabs.List>

        <Tabs.Content value="catalog" className="pt-4"><CatalogSection /></Tabs.Content>
        <Tabs.Content value="matching" className="pt-4"><MatchingSection /></Tabs.Content>
        <Tabs.Content value="match-log" className="pt-4"><MatchLogTab /></Tabs.Content>
        <Tabs.Content value="promotion" className="pt-4"><PromotionPanel provider="dicefest" /></Tabs.Content>
        <Tabs.Content value="bgg" className="pt-4"><BggImportPanel /></Tabs.Content>
      </Tabs>
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
    cellClass: 'font-mono text-xs text-zinc-500',
    render: g => g.id,
  },
  {
    id: 'slug', label: 'slug', defaultVisible: true, defaultSize: 180,
    cellClass: 'font-mono text-xs text-zinc-400 truncate',
    render: g => g.slug,
  },
  {
    id: 'title', label: 'title', defaultVisible: true, defaultSize: 280,
    cellClass: 'text-zinc-100 truncate',
    render: g => g.title,
  },
  {
    id: 'title_ru', label: 'RU название', defaultVisible: true, defaultSize: 240,
    cellClass: 'text-zinc-200 truncate',
    render: g => g.title_ru ?? <span className="text-zinc-600">—</span>,
  },
  {
    id: 'year', label: 'year', defaultVisible: true, defaultSize: 70,
    cellClass: 'text-zinc-300',
    render: g => g.year ?? '—',
  },
  {
    id: 'source', label: 'source', defaultVisible: true, defaultSize: 90,
    render: g => <SourceBadge source={g.source} />,
  },
  {
    id: 'bgg_tesera', label: 'BGG / Tesera', defaultVisible: true, defaultSize: 160,
    cellClass: 'text-xs text-zinc-400',
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
    cellClass: 'text-xs text-zinc-300',
    render: g => g.kind,
  },
  {
    id: 'parent_game_id', label: 'parent', defaultVisible: false, defaultSize: 80,
    cellClass: 'font-mono text-xs text-zinc-400',
    render: g => g.parent_game_id ?? '—',
  },
  {
    id: 'ru_publisher', label: 'ru_publisher', defaultVisible: false, defaultSize: 160,
    cellClass: 'text-xs text-zinc-300 truncate',
    render: g => g.ru_publisher ?? '—',
  },
  {
    id: 'ru_release_year', label: 'ru_year', defaultVisible: false, defaultSize: 80,
    cellClass: 'text-xs text-zinc-300',
    render: g => g.ru_release_year ?? '—',
  },
  {
    id: 'is_localized_ru', label: 'RU?', defaultVisible: false, defaultSize: 60,
    cellClass: 'text-center text-xs',
    render: g => g.is_localized_ru
      ? <CheckCircle2 size={12} className="text-emerald-400" />
      : <span className="text-zinc-600">—</span>,
  },
  {
    id: 'preorder_price', label: 'preorder', defaultVisible: false, defaultSize: 100,
    cellClass: 'text-xs text-zinc-300 text-right',
    // preorder_price хранится в копейках — конвертим в рубли для отображения,
    // как и везде в UI портала (см. правило в корневом CLAUDE.md).
    render: g => g.preorder_price != null ? `${(g.preorder_price / 100).toFixed(0)} ₽` : '—',
  },
  {
    id: 'status', label: 'status', defaultVisible: false, defaultSize: 100,
    cellClass: 'text-xs text-zinc-400',
    render: g => g.status,
  },
  {
    id: 'dicefest_id', label: 'dicefest', defaultVisible: false, defaultSize: 90,
    cellClass: 'font-mono text-xs text-zinc-400',
    render: g => g.dicefest_id ?? '—',
  },
  {
    id: 'nastolio_id', label: 'nastolio', defaultVisible: false, defaultSize: 100,
    cellClass: 'font-mono text-xs text-zinc-400',
    render: g => g.nastolio_id ?? '—',
  },
  {
    id: 'cover_url', label: 'cover', defaultVisible: false, defaultSize: 64,
    render: g => g.cover_url
      ? <img src={g.cover_url} alt="" className="w-8 h-8 object-cover rounded" />
      : <span className="text-zinc-600 text-xs">—</span>,
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

  // Selected row (для подсветки в split-view) — синхронизирован с drawer-id.
  const selectedRowId = openId

  return (
    <div className="space-y-3">
      {/* Toolbar: search + counter + columns */}
      <div className="flex items-center gap-2">
        <SuggestInput
          value={q}
          onChange={setQ}
          onSubmit={() => { if (q.trim()) pushHistory(q) }}
          historyKey="catalog"
          placeholder="Поиск: title · alias · slug · BGG# · T#"
          className="flex-1"
        />
        <div className="text-xs text-zinc-500 font-mono tabular-nums whitespace-nowrap">
          {games.isLoading
            ? 'загрузка…'
            : <><span className="text-zinc-300">{items.length}</span> / {total}</>}
        </div>
        <ColumnsPicker />
      </div>

      {games.isError && (
        <div className="text-sm text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded px-3 py-2">
          Не удалось получить каталог: {String(games.error)}
        </div>
      )}

      <div className="border border-zinc-800 rounded overflow-x-auto">
        <table
          className="text-sm"
          style={{ width: table.getCenterTotalSize(), tableLayout: 'fixed' }}
        >
          <thead className="bg-zinc-900 text-zinc-400 text-left select-none sticky top-0 z-10">
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map(header => (
                  <th
                    key={header.id}
                    style={{ width: header.getSize() }}
                    className="relative px-3 py-2 truncate text-xs font-normal border-b border-zinc-800"
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {/* Resize-handle: indigo accent (handoff §5) */}
                    <div
                      onMouseDown={header.getResizeHandler()}
                      onTouchStart={header.getResizeHandler()}
                      className={`absolute top-0 right-0 h-full w-1 cursor-col-resize select-none touch-none ${
                        header.column.getIsResizing()
                          ? 'bg-indigo-500'
                          : 'bg-transparent hover:bg-indigo-500/40'
                      }`}
                    />
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {table.getRowModel().rows.map(row => {
              const isActive = selectedRowId === row.original.id
              return (
                <tr
                  key={row.id}
                  className={`cursor-pointer ${isActive ? 'bg-indigo-500/10' : 'hover:bg-zinc-800/30'}`}
                  onClick={() => setOpenId(row.original.id)}
                >
                  {row.getVisibleCells().map(cell => {
                    const meta = cell.column.columnDef.meta as
                      | { cellClass?: string } | undefined
                    return (
                      <td
                        key={cell.id}
                        style={{ width: cell.column.getSize() }}
                        className={`px-3 py-1.5 truncate ${meta?.cellClass ?? ''}`}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
            {!games.isLoading && items.length === 0 && (
              <tr>
                <td colSpan={renderedColumns.length} className="px-3 py-12 text-center">
                  <div className="text-sm text-zinc-400">Нет игр {q && <>по запросу «{q}»</>}</div>
                  <div className="text-xs text-zinc-500 mt-1">Попробуй другой запрос или импортируй из BGG/Tesera</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {games.hasNextPage && (
        <Button
          variant="ghost"
          size="md"
          loading={games.isFetchingNextPage}
          onClick={() => games.fetchNextPage()}
          className="w-full justify-center"
        >
          {games.isFetchingNextPage
            ? 'загрузка…'
            : `Показать ещё (осталось ${remaining})`}
        </Button>
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
      <Button
        variant="secondary"
        size="sm"
        icon={Settings2}
        onClick={() => setOpen(o => !o)}
        title="Выбрать видимые колонки"
      >
        Колонки
      </Button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-full mt-1 z-50 w-64 bg-zinc-900 border border-zinc-700 rounded shadow-lg p-2 max-h-96 overflow-y-auto">
            <div className="text-xs text-zinc-500 px-2 py-1 mb-1">
              Видимые колонки таблицы
            </div>
            {COLUMNS.map(c => (
              <label
                key={c.id}
                className="flex items-center gap-2 px-2 py-1 rounded hover:bg-zinc-800 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={visible.includes(c.id)}
                  onChange={() => toggle(c.id)}
                  className="accent-indigo-500"
                />
                <span className="text-sm text-zinc-200">{c.label}</span>
                <span className="ml-auto text-xxs font-mono text-zinc-500">{c.id}</span>
              </label>
            ))}
            <div className="flex gap-2 mt-2 pt-2 border-t border-zinc-800 px-2">
              <Button variant="secondary" size="xs" onClick={() => reset()} className="flex-1 justify-center">
                Сбросить
              </Button>
              <Button variant="secondary" size="xs" onClick={() => showAll(ALL_COLUMN_IDS)} className="flex-1 justify-center">
                Все
              </Button>
            </div>
            <Button
              variant="ghost"
              size="xs"
              onClick={() => resetSizes()}
              title="Вернуть стандартные ширины колонок"
              className="w-full mt-2 justify-center"
            >
              Сбросить ширины
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

function SourceBadge({ source }: { source: string }) {
  // source — origin записи (bgg/tesera/manual), не статус pipeline.
  // Используем Tag через tone-map, цвета — кастомные классы (нет
  // подходящего tone в statusSystem для «BGG orange» и «Tesera blue»).
  const cls = source === 'bgg'
    ? 'bg-orange-500/15 text-orange-300 border-orange-500/30'
    : source === 'tesera'
      ? 'bg-blue-500/15 text-blue-300 border-blue-500/30'
      : 'bg-zinc-800/80 text-zinc-300 border-zinc-700'
  return (
    <span className={`inline-flex items-center h-4 px-1.5 text-xxs font-mono uppercase tracking-wider rounded border ${cls}`}>
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
              className={`px-2 py-0.5 text-xs rounded ${!storeFilter ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'}`}
            >
              все
            </button>
            {stores.map(s => (
              <button
                key={s.store_slug}
                onClick={() => { setStoreFilter(s.store_slug); setSelectedId(null) }}
                className={`px-2 py-0.5 text-xs rounded ${storeFilter === s.store_slug ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'}`}
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
                    : 'bg-zinc-600 text-white'
                  : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'}`}
              >
                {b} {stats.data?.by_bucket[b] ?? ''}
              </button>
            ))}
          </div>

          {/* Offer list */}
          <div className="flex-1 border border-zinc-800 rounded overflow-y-auto">
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
                <div className="border-t border-zinc-800" />
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
              <div className="px-3 py-8 text-center text-xs text-zinc-500">
                {queue.data?.total === 0
                  ? 'Очередь пуста — все офферы сматчены.'
                  : 'Нет офферов по текущему фильтру.'}
              </div>
            )}

            {queue.isLoading && (
              <div className="px-3 py-4 text-center text-xs text-zinc-500">загрузка…</div>
            )}
          </div>

          {/* Footer: load more + batch actions */}
          <div className="flex items-center gap-2 flex-wrap">
            {queue.data && queue.data.total > limit && (
              <button
                onClick={() => setLimit(l => l + 50)}
                className="px-2 py-1 text-xs bg-zinc-800 text-zinc-300 rounded hover:bg-zinc-700"
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
              className="ml-auto px-2 py-1 text-xs bg-indigo-800/60 text-indigo-200 rounded hover:bg-indigo-700 disabled:opacity-40"
            >
              {reassessBatch.isPending ? 'Пересчёт…' : 'Reassess всё'}
            </button>
          </div>
        </div>

        {/* ── Правая панель ────────────────────────────── */}
        <div className="flex-1 min-w-0 border border-zinc-800 rounded">
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
              <div className="h-full flex items-center justify-center text-sm text-zinc-500">
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
  const scoreColor = offer.match_score == null ? 'text-zinc-600'
    : offer.match_score >= autoThreshold ? 'text-emerald-400'
    : offer.match_score >= 0.3 ? 'text-amber-400'
    : 'text-zinc-500'

  return (
    <div
      onClick={onSelect}
      className={`flex items-start gap-2 px-2 py-1.5 border-b border-zinc-800/60 cursor-pointer transition-colors ${
        selected ? 'bg-indigo-900/30' : 'hover:bg-zinc-900'
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onClick={e => e.stopPropagation()}
        onChange={onToggleCheck}
        className="mt-0.5 shrink-0 accent-indigo-500"
      />
      <div className="flex-1 min-w-0">
        <div className="text-xs text-zinc-200 truncate" title={offer.title_raw}>
          {offer.title_raw}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] font-mono text-zinc-500">{offer.store_slug}</span>
          {offer.last_price != null && (
            <span className="text-[10px] text-zinc-400">
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
          <div className="text-sm text-zinc-100 font-medium leading-tight">{offer.title_raw}</div>
          <a href={offer.url} target="_blank" rel="noreferrer"
             className="text-zinc-500 hover:text-zinc-200 shrink-0 mt-0.5">
            <span className="text-[10px]">↗</span>
          </a>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-zinc-500">
          <span className="font-mono">{offer.store_slug}</span>
          {offer.last_price != null && (
            <span>{(offer.last_price / 100).toFixed(0)} ₽</span>
          )}
          {offer.match_score != null && (
            <span className={
              offer.match_score >= autoThreshold ? 'text-emerald-400'
              : offer.match_score >= candidateThreshold ? 'text-amber-400'
              : 'text-zinc-500'
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
        <div className="text-[10px] uppercase tracking-wide text-zinc-500">Поиск по каталогу</div>
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          className="w-full px-2 py-1.5 text-xs bg-zinc-900 border border-zinc-700 rounded text-zinc-200 focus:border-indigo-500 outline-none"
          placeholder="Название для поиска..."
        />
      </div>

      {/* Кандидаты */}
      <div className="flex-1 overflow-y-auto space-y-0.5 min-h-0">
        {candidates.isLoading && (
          <div className="text-xs text-zinc-500 text-center py-2">поиск…</div>
        )}
        {items.map(c => (
          <button
            key={c.game_id}
            type="button"
            disabled={isPending}
            onClick={() => link.mutate(c.game_id)}
            className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded hover:bg-zinc-800 disabled:opacity-50 transition-colors"
          >
            <ScoreBadge score={c.score} auto={autoThreshold} via={c.via} />
            <span className="text-xs text-zinc-200 truncate flex-1">{c.title}</span>
            {c.year != null && <span className="text-[10px] text-zinc-500 shrink-0">{c.year}</span>}
            {c.bgg_id && (
              <span className="text-[10px] text-orange-300/70 shrink-0 font-mono">BGG#{c.bgg_id}</span>
            )}
          </button>
        ))}
        {!candidates.isLoading && items.length === 0 && debouncedQ.trim() && (
          <div className="text-xs text-zinc-500 italic px-2 py-2">
            Кандидатов нет. Импортируй из BGG/Tesera или создай вручную.
          </div>
        )}
      </div>

      {/* Действия */}
      <div className="flex gap-2 pt-2 border-t border-zinc-800">
        <button
          type="button"
          onClick={() => {
            if (window.confirm(`Отклонить «${offer.title_raw}»?`)) reject.mutate()
          }}
          disabled={isPending}
          className="px-3 py-1 text-xs bg-zinc-800 text-zinc-300 rounded hover:bg-zinc-700 disabled:opacity-40"
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
      : 'bg-zinc-800 text-zinc-400'
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
