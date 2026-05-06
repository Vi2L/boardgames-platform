import { useCallback, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, CheckCircle2, XCircle, AlertTriangle, Play, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { SuiteOut, SuiteRunMeta } from '../../types/api'
import { deleteSuite, fetchSuiteRuns } from '../../lib/api'
import { useSSE } from '../../lib/sse'

interface ItemState {
  idx: number
  total: number
  query: string
  status: 'pending' | 'running' | 'ok' | 'partial' | 'error'
  ms?: number
  snapshot_id?: number
  error?: string
}

interface Props {
  suite: SuiteOut
  onDeleted?: () => void
}

/**
 * Прогон test-сьюта с live-таблицей через SSE.
 *
 * Состояние строки query: pending → running → {ok, partial, error}.
 * Обновляется по событиям suite-item-start/done из бэкенда. Сводка
 * (`suite-summary`) фиксирует ms_total, passed/failed.
 */
export function SuiteRunner({ suite, onDeleted }: Props) {
  const [sseUrl, setSseUrl] = useState<string | null>(null)
  const [items, setItems] = useState<ItemState[]>([])
  const [summary, setSummary] = useState<SuiteRunMeta['summary'] | null>(null)
  const queryClient = useQueryClient()

  const { data: runs = [], refetch } = useQuery({
    queryKey: ['suite-runs', suite.id],
    queryFn: () => fetchSuiteRuns(suite.id, 10),
  })

  const handleEvent = useCallback((event: string, data: unknown) => {
    const d = data as Record<string, unknown>

    if (event === 'suite-item-start') {
      const idx = d.idx as number
      const total = d.total as number
      const query = d.query as string
      setItems(prev => {
        const existing = prev.find(it => it.idx === idx)
        if (existing) return prev.map(it => it.idx === idx ? { ...it, status: 'running' } : it)
        return [...prev, { idx, total, query, status: 'running' }]
      })
    } else if (event === 'suite-item-done') {
      const idx = d.idx as number
      setItems(prev => prev.map(it => it.idx === idx
        ? {
            ...it,
            status: d.status as ItemState['status'],
            ms: d.ms as number,
            snapshot_id: d.snapshot_id as number | undefined,
            error: d.error as string | undefined,
          }
        : it))
    } else if (event === 'suite-summary') {
      setSummary(d as SuiteRunMeta['summary'])
      setSseUrl(null)
      void queryClient.invalidateQueries({ queryKey: ['suite-runs', suite.id] })
      void refetch()
    }
  }, [queryClient, refetch, suite.id])

  useSSE(sseUrl, handleEvent)

  const start = () => {
    // Префилл pending-строк, чтобы пользователь сразу видел план прогона
    setItems(suite.queries.map((q, i) => ({
      idx: i + 1, total: suite.queries.length, query: q.q, status: 'pending',
    })))
    setSummary(null)
    setSseUrl(`/api/suites/${suite.id}/run`)
  }

  const remove = async () => {
    if (!confirm(`Удалить сьют «${suite.name}» со всеми прогонами?`)) return
    await deleteSuite(suite.id)
    onDeleted?.()
  }

  // При маунте сбрасываем live-state каждый раз при смене suite
  useEffect(() => {
    setItems([])
    setSummary(null)
    setSseUrl(null)
  }, [suite.id])

  const isRunning = sseUrl !== null

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold text-gray-100">{suite.name}</h2>
        <span className="text-xs text-gray-500">{suite.queries.length} запросов</span>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={start}
            disabled={isRunning}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium',
              isRunning
                ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                : 'bg-violet-700 hover:bg-violet-600 text-white',
            )}
          >
            {isRunning ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
            {isRunning ? 'Идёт прогон…' : 'Запустить'}
          </button>
          <button
            type="button"
            onClick={remove}
            className="p-1.5 rounded text-gray-500 hover:text-red-400 hover:bg-red-950/30"
            title="Удалить сьют"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {suite.description && (
        <p className="text-xs text-gray-500">{suite.description}</p>
      )}

      {items.length > 0 && <ItemsTable items={items} />}

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
          <Cell label="Всего" value={summary.total ?? 0} />
          <Cell label="OK" value={summary.passed ?? 0} accent="text-green-400" />
          <Cell label="Сбоев" value={summary.failed ?? 0} accent={summary.failed ? 'text-red-400' : 'text-gray-400'} />
          <Cell label="Σ ms" value={summary.ms_total ?? 0} />
          <Cell label="ms/req" value={summary.ms_per_query ?? 0} />
        </div>
      )}

      {runs.length >= 2 && <SuiteTrend runs={runs} />}
    </div>
  )
}

function Cell({ label, value, accent }: { label: string; value: number | string; accent?: string }) {
  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded px-2 py-1.5">
      <div className="text-gray-500">{label}</div>
      <div className={clsx('font-mono font-semibold', accent ?? 'text-gray-200')}>{value}</div>
    </div>
  )
}

function ItemsTable({ items }: { items: ItemState[] }) {
  return (
    <div className="border border-gray-800 rounded overflow-hidden">
      {items.map(it => (
        <div
          key={it.idx}
          className={clsx(
            'flex items-center gap-3 px-3 py-2 text-sm border-b border-gray-800/50 last:border-b-0',
            it.status === 'running' && 'bg-blue-950/20',
            it.status === 'ok'      && 'bg-green-950/10',
            it.status === 'partial' && 'bg-orange-950/15',
            it.status === 'error'   && 'bg-red-950/20',
          )}
        >
          <span className="w-8 text-xs text-gray-500 font-mono">{it.idx}/{it.total}</span>
          <StatusIcon status={it.status} />
          <span className="flex-1 text-gray-200 truncate">{it.query}</span>
          {it.ms != null && <span className="text-xs text-gray-400 font-mono">{it.ms}ms</span>}
          {it.error && (
            <span className="text-xs text-red-400 max-w-[40%] truncate" title={it.error}>
              {it.error}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

function StatusIcon({ status }: { status: ItemState['status'] }) {
  switch (status) {
    case 'pending': return <span className="w-3.5 h-3.5 rounded-full border border-gray-600" />
    case 'running': return <Loader2 size={14} className="text-blue-400 animate-spin" />
    case 'ok':      return <CheckCircle2 size={14} className="text-green-400" />
    case 'partial': return <AlertTriangle size={14} className="text-orange-400" />
    case 'error':   return <XCircle size={14} className="text-red-400" />
  }
}

function SuiteTrend({ runs }: { runs: SuiteRunMeta[] }) {
  // recharts ждёт массив, упорядоченный слева направо по времени
  const data = [...runs].reverse().map(r => ({
    when: new Date(r.started_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
    ms_total: r.summary.ms_total ?? 0,
    failed: r.summary.failed ?? 0,
  }))
  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded p-3">
      <div className="text-xs text-gray-500 mb-2">Тренд по последним прогонам</div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="when" tick={{ fill: '#9ca3af', fontSize: 10 }} />
          <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 11 }}
          />
          <Line type="monotone" dataKey="ms_total" stroke="#8b5cf6" strokeWidth={2} dot />
          <Line type="monotone" dataKey="failed" stroke="#ef4444" strokeWidth={1} dot />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
