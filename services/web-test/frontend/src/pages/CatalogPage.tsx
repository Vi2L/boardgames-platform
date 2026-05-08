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
import {
  fetchCatalogHealth,
  fetchMatchCandidates,
  fetchMatchingQueue,
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
import { useCatalogTableStore } from '../store/catalog'
import { Download, Plus, Settings2 } from 'lucide-react'

type Tab = 'catalog' | 'matching' | 'promotion'

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
        {(['catalog', 'matching', 'promotion'] as Tab[]).map(t => (
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
              : 'Промоушен Dicefest'}
          </button>
        ))}
      </div>

      {tab === 'catalog'  ? <CatalogSection />
        : tab === 'matching' ? <MatchingSection />
        : <PromotionPanel provider="dicefest" />}
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
        <input
          type="text"
          placeholder="Поиск по названиям (RU/EN aliases + fuzzy)"
          value={q}
          onChange={e => setQ(e.target.value)}
          className="flex-1 px-2 py-1 bg-gray-900 border border-gray-700 rounded text-xs text-gray-100 placeholder-gray-500 focus:border-violet-500 focus:outline-none"
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

// ─── Очередь матчинга ─────────────────────────────────────────────────────

function MatchingSection() {
  const queryClient = useQueryClient()
  const queue = useQuery({
    queryKey: ['catalog', 'matching-queue'],
    queryFn: () => fetchMatchingQueue(undefined, 100, 0),
  })

  const invalidateQueueAndStats = () => {
    queryClient.invalidateQueries({ queryKey: ['catalog', 'matching-queue'] })
    queryClient.invalidateQueries({ queryKey: ['catalog', 'matching-stats'] })
  }

  const reject = useMutation({
    mutationFn: rejectOffer,
    onSuccess: () => { toast.success('Оффер отклонён'); invalidateQueueAndStats() },
    onError: (e) => toast.error(`Не удалось отклонить: ${e}`),
  })

  const reassess = useMutation({
    mutationFn: reassessOffer,
    onSuccess: (o) => {
      const status = o.match_status === 'auto' ? 'auto-сматчен ✓' : 'остался unmatched'
      toast.success(`#${o.id}: ${status} (score ${o.match_score?.toFixed(2) ?? '—'})`)
      invalidateQueueAndStats()
    },
    onError: (e) => toast.error(`Reassess failed: ${e}`),
  })

  const reassessBatch = useMutation({
    mutationFn: () => reassessAll(),
    onSuccess: (r) => {
      toast.success(
        `Пересчитано ${r.scanned}: → auto ${r.promoted_to_auto}, ` +
        `улучшено ${r.score_improved}, без изменений ${r.unchanged}`,
      )
      invalidateQueueAndStats()
    },
    onError: (e) => toast.error(`Batch reassess failed: ${e}`),
  })

  return (
    <div className="space-y-3">
      <MatchingStatsHeader />
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">
          {queue.data
            ? `${queue.data.total} unmatched-оффер'ов в очереди (сортировка по match_score)`
            : 'загрузка...'}
        </div>
        <button
          type="button"
          onClick={() => {
            if (window.confirm(
              'Запустить batch-reassess для всех unmatched?\nЭто перепрогонит find_best_match по каждому offer и может «продвинуть» некоторые в auto.',
            )) reassessBatch.mutate()
          }}
          disabled={reassessBatch.isPending}
          className="px-3 py-1 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white rounded"
        >
          {reassessBatch.isPending ? 'Пересчёт…' : 'Reassess всё'}
        </button>
      </div>
      <div className="border border-gray-800 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2">store</th>
              <th className="px-3 py-2">title_raw</th>
              <th className="px-3 py-2">price</th>
              <th className="px-3 py-2">score</th>
              <th className="px-3 py-2">действия</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {queue.data?.items.map(o => (
              <OfferRow
                key={o.id}
                o={o}
                onLinked={invalidateQueueAndStats}
                onReject={() => reject.mutate(o.id)}
                onReassess={() => reassess.mutate(o.id)}
              />
            ))}
            {queue.data?.items.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-500">
                Очередь пуста — все оффер'ы сматчены или отклонены.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function OfferRow({
  o, onLinked, onReject, onReassess,
}: {
  o: CatalogOffer
  onLinked: () => void
  onReject: () => void
  onReassess: () => void
}) {
  const [linkOpen, setLinkOpen] = useState(false)
  return (
    <>
      <tr className="hover:bg-gray-900">
        <td className="px-3 py-2 text-xs font-mono text-gray-400">{o.store_slug}</td>
        <td className="px-3 py-2 text-gray-100">
          <a href={o.url} target="_blank" rel="noreferrer" className="hover:text-violet-300">
            {o.title_raw}
          </a>
        </td>
        <td className="px-3 py-2 text-gray-300">
          {o.last_price ? `${(o.last_price / 100).toFixed(0)} ₽` : '—'}
        </td>
        <td className="px-3 py-2 text-xs text-gray-400">
          {o.match_score != null ? o.match_score.toFixed(2) : '—'}
        </td>
        <td className="px-3 py-2 space-x-2">
          <button
            type="button"
            onClick={() => setLinkOpen(v => !v)}
            className="px-2 py-1 text-xs bg-violet-900/50 text-violet-200 rounded hover:bg-violet-900"
          >
            Связать
          </button>
          <button
            type="button"
            onClick={onReassess}
            title="Пересчитать score (после правки алиасов / импорта BGG)"
            className="px-2 py-1 text-xs bg-amber-900/50 text-amber-200 rounded hover:bg-amber-900"
          >
            ↻
          </button>
          <button
            type="button"
            onClick={onReject}
            className="px-2 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700"
          >
            Отклонить
          </button>
        </td>
      </tr>
      {linkOpen && (
        <tr className="bg-gray-950">
          <td colSpan={5} className="px-3 py-3 border-t border-gray-800">
            <LinkPicker offer={o} onLinked={() => { setLinkOpen(false); onLinked() }} />
          </td>
        </tr>
      )}
    </>
  )
}

function LinkPicker({ offer, onLinked }: { offer: CatalogOffer; onLinked: () => void }) {
  const [q, setQ] = useState(offer.title_raw)
  // По умолчанию query = title_raw, тогда запрос автоматически приносит
  // топ-N кандидатов через pg_trgm % similarity. Можно переписать руками,
  // если автомат проматчил не туда.
  const candidates = useQuery({
    queryKey: ['catalog', 'match-candidates', q],
    queryFn: () => fetchMatchCandidates(q, 10),
    enabled: !!q.trim(),
  })

  const link = useMutation({
    mutationFn: (gameId: number) => linkOffer(offer.id, gameId),
    onSuccess: () => { toast.success('Оффер связан с игрой'); onLinked() },
    onError: (e) => toast.error(`Не удалось связать: ${e}`),
  })

  const items: MatchCandidate[] = candidates.data?.items ?? []
  const auto = candidates.data?.auto_threshold ?? 0.6
  const minC = candidates.data?.candidate_threshold ?? 0.3

  return (
    <div className="space-y-2">
      <div className="text-xs text-gray-500">
        Автоматически связывается при score ≥ {auto.toFixed(2)};
        кандидаты ≥ {minC.toFixed(2)} попадают в очередь.
        Текущий offer: <span className="font-mono text-gray-300">«{offer.title_raw}»</span>
      </div>
      <input
        type="text"
        value={q}
        onChange={e => setQ(e.target.value)}
        placeholder="title_raw → автокандидаты, или ручной поиск..."
        className="w-full px-2 py-1 text-sm bg-gray-900 border border-gray-700 rounded text-gray-100"
      />
      {items.length > 0 ? (
        <div className="space-y-1">
          {items.map(c => (
            <button
              key={c.game_id}
              type="button"
              disabled={link.isPending}
              onClick={() => link.mutate(c.game_id)}
              className="w-full text-left px-2 py-1.5 text-sm bg-gray-900 hover:bg-gray-800 rounded text-gray-200 disabled:opacity-50 flex items-center gap-2"
            >
              <ScoreBadge score={c.score} auto={auto} via={c.via} />
              <span className="font-mono text-xs text-gray-500">#{c.game_id}</span>
              <span className="truncate flex-1">{c.title}</span>
              {c.year && <span className="text-xs text-gray-500 flex-shrink-0">({c.year})</span>}
              {c.bgg_id && <span className="text-xs text-orange-300/80 flex-shrink-0 font-mono">BGG#{c.bgg_id}</span>}
            </button>
          ))}
        </div>
      ) : (
        <div className="text-xs text-gray-500 px-2 py-1">
          {candidates.isLoading ? 'ищу кандидатов…'
            : `Кандидатов ≥ ${minC.toFixed(2)} нет. Импортируй из BGG/Tesera или создай вручную.`}
        </div>
      )}
    </div>
  )
}

function ScoreBadge({ score, auto, via }: { score: number; auto: number; via: 'title'|'alias' }) {
  const cls = score >= auto
    ? 'bg-emerald-900/60 text-emerald-200'
    : score >= 0.5
      ? 'bg-amber-900/60 text-amber-200'
      : 'bg-gray-800 text-gray-400'
  return (
    <span className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono ${cls}`}
          title={`similarity по ${via === 'title' ? 'title канона' : 'алиасу'}`}>
      {score.toFixed(2)}
      <span className="opacity-60 uppercase">{via}</span>
    </span>
  )
}
