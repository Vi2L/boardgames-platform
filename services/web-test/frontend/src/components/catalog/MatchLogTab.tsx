import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Undo2, AlertTriangle, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  bulkRevertMatchLog,
  fetchMatchLog,
  invalidateDecision,
  normalizeTitle,
  revertMatchLog,
  type MatchLogEntry,
  type MatchLogFilters,
} from '../../lib/catalog'
import { TierBadge } from './TierBadge'

// action'ы, для которых имеет смысл инвалидировать T0 cache decision:
// reject (negative cache от оператора) и auto_t3 (часто 'not_a_boardgame'
// от LLM, который мог ошибочно сработать).
const INVALIDATE_ACTIONS = new Set(['reject', 'auto_t3'])

/**
 * Журнал матчинга: список MatchLog записей с фильтрами + bulk revert.
 *
 * Паттерн взят из PromotionLogList: chекбоксы + кнопка Bulk Revert + кнопка
 * Revert на каждой строке. Возможность удалить связанный auto-alias через
 * чекбокс «удалить также alias».
 */
export function MatchLogTab() {
  const qc = useQueryClient()
  const [filters, setFilters] = useState<MatchLogFilters>({
    only_active: false,
    limit: 50,
    offset: 0,
  })
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [deleteAlias, setDeleteAlias] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['catalog', 'match-log', filters],
    queryFn: () => fetchMatchLog(filters),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['catalog', 'match-log'] })
    qc.invalidateQueries({ queryKey: ['catalog', 'matching-queue'] })
    qc.invalidateQueries({ queryKey: ['catalog', 'matching-stats'] })
    qc.invalidateQueries({ queryKey: ['catalog', 'ml-status'] })
  }

  const oneRevert = useMutation({
    mutationFn: ({ id, withAlias }: { id: number; withAlias: boolean }) =>
      revertMatchLog(id, withAlias),
    onSuccess: () => {
      toast.success('Запись откатнута')
      invalidate()
    },
    onError: (e: Error) => toast.error(`Ошибка отката: ${e.message}`),
  })

  const invalidate_decision = useMutation({
    mutationFn: (titleNorm: string) => invalidateDecision(titleNorm),
    onSuccess: (res) => {
      if (res.deleted > 0) {
        toast.success(`Decision инвалидирован (${res.deleted}). Следующий ingest пройдёт T1/T2/T3 заново.`)
      } else {
        toast.warning('Decision не найден (возможно уже истёк по TTL).')
      }
      invalidate()
    },
    onError: (e: Error) => toast.error(`Ошибка инвалидации: ${e.message}`),
  })

  const bulkRevert = useMutation({
    mutationFn: ({ ids, withAlias }: { ids: number[]; withAlias: boolean }) =>
      bulkRevertMatchLog(ids, withAlias),
    onSuccess: (res) => {
      toast.success(`Откатнуто ${res.reverted}/${res.requested} записей`)
      setSelected(new Set())
      invalidate()
    },
    onError: (e: Error) => toast.error(`Ошибка bulk-отката: ${e.message}`),
  })

  const toggle = (id: number) =>
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const allSelected = items.length > 0 && items.every(i => selected.has(i.id))
  const toggleAll = () => {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(items.map(i => i.id)))
  }

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <FilterSelect
          label="action"
          value={filters.action ?? ''}
          options={[
            ['', 'все'],
            ['auto_t0', 'T0 cache'],
            ['auto_t1', 'T1 trgm'],
            ['auto_t2', 'T2 vec'],
            ['auto_t3', 'T3 llm'],
            ['manual', 'manual'],
            ['reject', 'reject'],
            ['unlink', 'unlink'],
            ['revert', 'revert'],
            ['invalidate', 'invalidate (T0 cache)'],
          ]}
          onChange={v => setFilters(f => ({ ...f, action: v || undefined, offset: 0 }))}
        />
        <FilterSelect
          label="tier"
          value={filters.tier?.toString() ?? ''}
          options={[
            ['', 'все'],
            ['0', 'T0'],
            ['1', 'T1'],
            ['2', 'T2'],
            ['3', 'T3'],
          ]}
          onChange={v => setFilters(f => ({ ...f, tier: v ? Number(v) : undefined, offset: 0 }))}
        />
        <FilterSelect
          label="who"
          value={filters.performed_by ?? ''}
          options={[
            ['', 'все'],
            ['system', 'system'],
            ['worker', 'worker'],
            ['operator', 'operator'],
          ]}
          onChange={v => setFilters(f => ({ ...f, performed_by: v || undefined, offset: 0 }))}
        />
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={filters.only_active ?? false}
            onChange={e => setFilters(f => ({ ...f, only_active: e.target.checked, offset: 0 }))}
            className="accent-indigo-500"
          />
          <span className="text-gray-300">только активные (не reverted)</span>
        </label>
        <span className="ml-auto text-gray-500 font-mono">total: {total}</span>
      </div>

      {/* Bulk-action bar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 px-3 py-2 bg-amber-900/20 border border-amber-800 rounded text-xs">
          <AlertTriangle size={13} className="text-amber-400" />
          <span className="text-amber-200">выбрано: {selected.size}</span>
          <label className="flex items-center gap-1.5 cursor-pointer ml-2">
            <input
              type="checkbox"
              checked={deleteAlias}
              onChange={e => setDeleteAlias(e.target.checked)}
              className="accent-amber-500"
            />
            <span className="text-amber-200">удалить также созданные алиасы</span>
          </label>
          <button
            type="button"
            disabled={bulkRevert.isPending}
            onClick={() => {
              if (!confirm(`Откатить ${selected.size} записей?`)) return
              bulkRevert.mutate({ ids: Array.from(selected), withAlias: deleteAlias })
            }}
            className="ml-auto px-3 py-1 text-xs bg-amber-700 hover:bg-amber-600 text-white rounded disabled:opacity-50"
          >
            {bulkRevert.isPending ? 'откатываю…' : 'Откатить выбранные'}
          </button>
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            className="px-2 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700"
          >
            снять
          </button>
        </div>
      )}

      {isLoading && <div className="text-sm text-gray-500 p-4">загрузка…</div>}
      {isError && <div className="text-sm text-red-400 p-4">ошибка загрузки</div>}

      {data && (
        <div className="border border-gray-800 rounded overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 text-gray-400">
              <tr>
                <th className="px-2 py-1.5 text-left w-8">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    className="accent-indigo-500"
                  />
                </th>
                <th className="px-2 py-1.5 text-left">tier</th>
                <th className="px-2 py-1.5 text-left">action</th>
                <th className="px-2 py-1.5 text-left">title_raw</th>
                <th className="px-2 py-1.5 text-left">store</th>
                <th className="px-2 py-1.5 text-left">prev → new</th>
                <th className="px-2 py-1.5 text-right">score</th>
                <th className="px-2 py-1.5 text-left">when</th>
                <th className="px-2 py-1.5 text-right">×</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {items.map(row => (
                <LogRow
                  key={row.id}
                  row={row}
                  selected={selected.has(row.id)}
                  onToggle={() => toggle(row.id)}
                  onRevert={(withAlias) =>
                    oneRevert.mutate({ id: row.id, withAlias })
                  }
                  onInvalidateDecision={(titleNorm) =>
                    invalidate_decision.mutate(titleNorm)
                  }
                />
              ))}
            </tbody>
          </table>
          {items.length === 0 && (
            <div className="text-center text-gray-500 py-8 text-sm">журнал пуст</div>
          )}
        </div>
      )}

      {/* Pagination */}
      {data && data.total > (filters.limit ?? 50) && (
        <div className="flex justify-between items-center text-xs text-gray-400">
          <button
            type="button"
            disabled={(filters.offset ?? 0) === 0}
            onClick={() => setFilters(f => ({
              ...f, offset: Math.max(0, (f.offset ?? 0) - (f.limit ?? 50)),
            }))}
            className="px-2 py-1 bg-gray-800 rounded disabled:opacity-30"
          >
            ← prev
          </button>
          <span>
            {(filters.offset ?? 0) + 1}–{Math.min(total, (filters.offset ?? 0) + items.length)} из {total}
          </span>
          <button
            type="button"
            disabled={(filters.offset ?? 0) + items.length >= total}
            onClick={() => setFilters(f => ({
              ...f, offset: (f.offset ?? 0) + (f.limit ?? 50),
            }))}
            className="px-2 py-1 bg-gray-800 rounded disabled:opacity-30"
          >
            next →
          </button>
        </div>
      )}
    </div>
  )
}

function FilterSelect({
  label, value, options, onChange,
}: {
  label: string
  value: string
  options: [string, string][]
  onChange: (v: string) => void
}) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="text-gray-500 font-mono">{label}:</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="bg-gray-900 border border-gray-700 text-gray-200 rounded px-1.5 py-0.5"
      >
        {options.map(([v, label]) => (
          <option key={v} value={v}>{label}</option>
        ))}
      </select>
    </label>
  )
}

function LogRow({
  row, selected, onToggle, onRevert, onInvalidateDecision,
}: {
  row: MatchLogEntry
  selected: boolean
  onToggle: () => void
  onRevert: (withAlias: boolean) => void
  onInvalidateDecision: (titleNorm: string) => void
}) {
  const isReverted = row.reverted_at != null
  const isRevertAction = row.action === 'revert'
  // T0 кэш можно инвалидировать только если у записи есть title_raw
  // и action соответствует «решающим» T0-источникам.
  const canInvalidate = !!row.title_raw && INVALIDATE_ACTIONS.has(row.action)

  return (
    <tr className={clsx(
      'hover:bg-gray-900/50',
      (isReverted || isRevertAction) && 'opacity-50',
    )}>
      <td className="px-2 py-1.5">
        <input
          type="checkbox"
          checked={selected}
          disabled={isReverted || isRevertAction}
          onChange={onToggle}
          className="accent-indigo-500"
        />
      </td>
      <td className="px-2 py-1.5">
        <TierBadge tier={row.tier} compact />
      </td>
      <td className="px-2 py-1.5 font-mono text-gray-300">
        <div className="flex items-center gap-1.5">
          <span>{row.action}</span>
          {canInvalidate && (
            <button
              type="button"
              title="Инвалидировать decision в T0 cache — следующий ingest пройдёт T1/T2/T3 заново"
              onClick={(e) => {
                e.stopPropagation()
                if (!row.title_raw) return
                const norm = normalizeTitle(row.title_raw)
                if (!confirm(
                  `Инвалидировать decision для:\n  «${row.title_raw}»\n\nСледующий ingest того же title прогонит matching заново.`,
                )) return
                onInvalidateDecision(norm)
              }}
              className="px-1 py-0.5 text-[9px] bg-amber-900/30 hover:bg-amber-900/60 text-amber-300 rounded inline-flex items-center gap-0.5"
            >
              <Trash2 size={9} />
              cache
            </button>
          )}
        </div>
      </td>
      <td className="px-2 py-1.5 max-w-[200px]">
        <span className="truncate block text-gray-200" title={row.title_raw ?? ''}>
          {row.title_raw ?? '—'}
        </span>
      </td>
      <td className="px-2 py-1.5 text-gray-500 font-mono">{row.store_slug ?? '—'}</td>
      <td className="px-2 py-1.5">
        <div className="flex items-center gap-1 text-gray-300">
          <span className="text-gray-500">{row.prev_status ?? '∅'}</span>
          <span className="text-gray-600">→</span>
          <span className={clsx(
            row.new_status === 'auto' && 'text-indigo-300',
            row.new_status === 'manual' && 'text-emerald-300',
            row.new_status === 'rejected' && 'text-red-300',
            row.new_status === 'unmatched' && 'text-amber-300',
          )}>
            {row.new_status}
          </span>
        </div>
        {row.new_game_title && (
          <div className="text-[10px] text-gray-500 truncate max-w-[160px]" title={row.new_game_title}>
            → {row.new_game_title}
          </div>
        )}
      </td>
      <td className="px-2 py-1.5 text-right font-mono text-gray-300">
        {row.score != null ? row.score.toFixed(2) : '—'}
      </td>
      <td className="px-2 py-1.5 text-gray-500 font-mono">
        {new Date(row.performed_at).toLocaleString('ru-RU', { hour12: false }).slice(0, 16)}
        <div className="text-[10px] text-gray-600">{row.performed_by ?? '?'}</div>
      </td>
      <td className="px-2 py-1.5 text-right">
        {!isReverted && !isRevertAction ? (
          <button
            type="button"
            title="Откатить запись"
            onClick={(e) => {
              e.stopPropagation()
              const alias = e.shiftKey  // Shift-click → удалить alias
              if (!confirm(alias ? 'Откатить + удалить алиас?' : 'Откатить запись?')) return
              onRevert(alias)
            }}
            className="px-1.5 py-0.5 text-[10px] bg-red-900/40 hover:bg-red-900 text-red-300 rounded"
          >
            <Undo2 size={11} />
          </button>
        ) : (
          <span className="text-[10px] text-gray-600 font-mono">
            {isReverted ? 'reverted' : 'revert'}
          </span>
        )}
      </td>
    </tr>
  )
}
