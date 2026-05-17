/**
 * RunDiffDrawer — превью изменений выбранного run + apply/discard.
 *
 * Структура:
 *  - Header: кнопки apply (по выбранному фильтру) и discard.
 *  - Сводка: 3 чипа new/updated/unchanged + applied/errors.
 *  - Список items: фильтр по change_type, текстовый поиск по slug.
 *  - Item: для updated раскрываем field_diffs (before/after).
 *
 * Apply-стратегия: оператор выбирает change_types (`new` / `updated`), backend
 * пишет UPSERT'ом только эти. unchanged по умолчанию никогда не применяются —
 * у них content_hash совпадает, перезапись бессмысленна.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { X } from 'lucide-react'
import {
  applySourceRun,
  discardSourceRun,
  fetchSourceRun,
  fetchSourceRunItems,
  type ScrapeChangeType,
  type ScrapeItem,
} from '../../lib/sources'

type Props = {
  provider: string
  runId: number | null
  onClose: () => void
}

const CHANGE_COLORS: Record<ScrapeChangeType, string> = {
  new: 'text-emerald-300 bg-emerald-900/40',
  updated: 'text-amber-300 bg-amber-900/40',
  unchanged: 'text-gray-400 bg-gray-800',
}

export function RunDiffDrawer({ provider, runId, onClose }: Props) {
  const [changeFilter, setChangeFilter] = useState<ScrapeChangeType | 'all'>('all')
  const [search, setSearch] = useState('')
  const qc = useQueryClient()

  const runQuery = useQuery({
    queryKey: ['sources', provider, 'runs', runId],
    queryFn: () => fetchSourceRun(provider, runId!),
    enabled: runId != null,
    refetchInterval: q => {
      const status = q.state.data?.status
      // Поллим до тех пор, пока run не «остановился».
      return status === 'running' ? 2000 : false
    },
  })

  const itemsQuery = useQuery({
    queryKey: ['sources', provider, 'runs', runId, 'items', changeFilter, search],
    queryFn: () =>
      fetchSourceRunItems(provider, runId!, {
        changeType: changeFilter === 'all' ? undefined : changeFilter,
        search: search || undefined,
        limit: 200,
      }),
    enabled: runId != null && runQuery.data?.status === 'ready',
  })

  const applyMutation = useMutation({
    mutationFn: (changeTypes: ScrapeChangeType[]) =>
      applySourceRun(provider, runId!, { change_types: changeTypes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources', provider] })
    },
  })

  const discardMutation = useMutation({
    mutationFn: () => discardSourceRun(provider, runId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources', provider] })
      onClose()
    },
  })

  if (runId == null) return null

  const run = runQuery.data
  const items = itemsQuery.data?.items ?? []

  return (
    <div className="fixed inset-0 z-30 flex" onClick={onClose}>
      <div className="flex-1 bg-black/40" />
      <aside
        className="w-full max-w-3xl bg-gray-950 border-l border-gray-800 flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <header className="border-b border-gray-800 px-5 py-3 flex items-center justify-between">
          <div>
            <div className="text-sm text-gray-400">Run</div>
            <h3 className="text-base font-semibold text-gray-100">
              #{run?.id} · {run?.status ?? '…'}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded"
          >
            <X size={16} />
          </button>
        </header>

        <div className="px-5 py-3 space-y-3 border-b border-gray-800">
          {/* Сводка */}
          <div className="flex flex-wrap gap-2 text-sm">
            <Chip label="new" value={run?.totals.new} color="emerald" />
            <Chip label="updated" value={run?.totals.updated} color="amber" />
            <Chip label="unchanged" value={run?.totals.unchanged} color="gray" />
            {run?.totals.errors ? <Chip label="errors" value={run.totals.errors} color="red" /> : null}
            {run?.totals.applied ? (
              <Chip label="applied" value={run.totals.applied} color="violet" />
            ) : null}
          </div>

          {/* Действия */}
          {run?.status === 'ready' && (
            <div className="flex gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => applyMutation.mutate(['new'])}
                disabled={applyMutation.isPending}
                className="px-3 py-1.5 text-sm rounded-md bg-emerald-700/70 text-white hover:bg-emerald-600 disabled:opacity-50"
              >
                Применить только new
              </button>
              <button
                type="button"
                onClick={() => applyMutation.mutate(['new', 'updated'])}
                disabled={applyMutation.isPending}
                className="px-3 py-1.5 text-sm rounded-md bg-indigo-700 text-white hover:bg-indigo-600 disabled:opacity-50"
              >
                Применить new + updated
              </button>
              <button
                type="button"
                onClick={() => {
                  if (confirm('Отбросить run? Items сохранятся в архиве, но в staging ничего не уйдёт.')) {
                    discardMutation.mutate()
                  }
                }}
                disabled={discardMutation.isPending}
                className="px-3 py-1.5 text-sm rounded-md bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-50"
              >
                Отбросить
              </button>
            </div>
          )}
          {applyMutation.isSuccess && (
            <div className="text-sm text-emerald-400">
              Применено: {applyMutation.data.applied}
            </div>
          )}

          {/* Фильтры */}
          {run?.status === 'ready' && (
            <div className="flex gap-2 items-center text-sm">
              <select
                value={changeFilter}
                onChange={e => setChangeFilter(e.target.value as ScrapeChangeType | 'all')}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-100"
              >
                <option value="all">все изменения</option>
                <option value="new">new</option>
                <option value="updated">updated</option>
                <option value="unchanged">unchanged</option>
              </select>
              <input
                type="text"
                placeholder="поиск по slug…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-100"
              />
            </div>
          )}
        </div>

        {/* Items */}
        <div className="flex-1 overflow-y-auto px-5 py-3 space-y-2">
          {run?.status === 'running' && (
            <div className="text-gray-400 text-sm">
              Прогон ещё идёт. Лог обновляется автоматически.
            </div>
          )}
          {run?.status === 'failed' && (
            <div className="text-red-400 text-sm">
              Прогон упал: {run.error_message}
            </div>
          )}
          {items.map(it => (
            <ItemRow key={it.id} item={it} />
          ))}
          {run?.status === 'ready' && items.length === 0 && !itemsQuery.isLoading && (
            <div className="text-sm text-gray-500">
              Нет items по текущему фильтру.
            </div>
          )}
        </div>

        {/* Live log tail */}
        {run && run.log_lines.length > 0 && (
          <details className="border-t border-gray-800 px-5 py-2 text-xs">
            <summary className="cursor-pointer text-gray-400">
              лог ({run.log_lines.length} строк)
            </summary>
            <pre className="mt-2 max-h-40 overflow-y-auto text-gray-500 font-mono whitespace-pre-wrap">
              {run.log_lines.slice(-50).join('\n')}
            </pre>
          </details>
        )}
      </aside>
    </div>
  )
}

function Chip({
  label,
  value,
  color,
}: {
  label: string
  value: number | undefined | null
  color: 'emerald' | 'amber' | 'gray' | 'red' | 'violet'
}) {
  const COLOR: Record<typeof color, string> = {
    emerald: 'bg-emerald-900/40 text-emerald-300',
    amber: 'bg-amber-900/40 text-amber-300',
    gray: 'bg-gray-800 text-gray-400',
    red: 'bg-red-900/40 text-red-300',
    violet: 'bg-indigo-900/40 text-indigo-300',
  }
  return (
    <span className={clsx('px-2 py-0.5 rounded text-xs', COLOR[color])}>
      {label}: <span className="tabular-nums font-medium">{value ?? '—'}</span>
    </span>
  )
}

function ItemRow({ item }: { item: ScrapeItem }) {
  const [open, setOpen] = useState(false)
  const title =
    (item.payload.title_ru as string | undefined) ??
    (item.payload.title_en as string | undefined) ??
    item.slug

  const hasDiffs = item.field_diffs && Object.keys(item.field_diffs).length > 0

  return (
    <div className="rounded-md border border-gray-800/60 bg-gray-900/40">
      <button
        type="button"
        onClick={() => hasDiffs && setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-3 py-2 text-left text-sm"
        disabled={!hasDiffs}
      >
        <span className={clsx('px-1.5 py-0.5 rounded text-[11px]', CHANGE_COLORS[item.change_type])}>
          {item.change_type}
        </span>
        <span className="font-mono text-xs text-gray-500 flex-shrink-0">
          {item.slug}
        </span>
        <span className="text-gray-200 truncate">{title}</span>
      </button>
      {open && hasDiffs && (
        <div className="px-3 pb-3 border-t border-gray-800/60 space-y-1.5 text-xs">
          {Object.entries(item.field_diffs!).map(([field, d]) => (
            <div key={field} className="grid grid-cols-[8rem_1fr_1fr] gap-2 items-start py-1">
              <div className="font-mono text-gray-400">{field}</div>
              <div className="text-red-300/80 font-mono break-words">
                <span className="text-gray-500 text-[10px] uppercase mr-1">было</span>
                {fmt(d.before)}
              </div>
              <div className="text-emerald-300/80 font-mono break-words">
                <span className="text-gray-500 text-[10px] uppercase mr-1">стало</span>
                {fmt(d.after)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '∅'
  if (typeof v === 'string') return v
  return JSON.stringify(v, null, 0)
}
