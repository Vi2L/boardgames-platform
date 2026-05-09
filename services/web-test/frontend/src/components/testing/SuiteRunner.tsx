import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Loader2, CheckCircle2, XCircle, AlertTriangle, Play, Trash2, Pin, X, Check,
} from 'lucide-react'
import clsx from 'clsx'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { SuiteOut, SuiteRunMeta } from '../../types/api'
import {
  deleteSuite, deleteSuiteBaseline, fetchSuiteBaselines, fetchSuiteRuns,
  upsertSuiteBaseline,
  type SuiteBaseline,
} from '../../lib/api'
import { useSSE } from '../../lib/sse'

interface ItemState {
  idx: number
  total: number
  query: string
  status: 'pending' | 'running' | 'ok' | 'partial' | 'error'
  ms?: number
  snapshot_id?: number
  error?: string
  product_count?: number
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

  // Baselines (F4.4) — мапа query → baseline для быстрого lookup в строках.
  const baselinesQ = useQuery({
    queryKey: ['suite-baselines', suite.id],
    queryFn: () => fetchSuiteBaselines(suite.id),
  })
  const baselineMap = new Map<string, SuiteBaseline>()
  for (const b of baselinesQ.data ?? []) baselineMap.set(b.query, b)

  const upsertBL = useMutation({
    mutationFn: (payload: { query: string; baseline: SuiteBaseline['baseline'] }) =>
      upsertSuiteBaseline(suite.id, payload),
    onSuccess: () => {
      toast.success('Baseline сохранён')
      void queryClient.invalidateQueries({ queryKey: ['suite-baselines', suite.id] })
    },
    onError: (e) => toast.error(`Не сохранён: ${e}`),
  })
  const deleteBL = useMutation({
    mutationFn: (id: number) => deleteSuiteBaseline(suite.id, id),
    onSuccess: () => {
      toast.success('Baseline удалён')
      void queryClient.invalidateQueries({ queryKey: ['suite-baselines', suite.id] })
    },
    onError: (e) => toast.error(`Не удалён: ${e}`),
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
            product_count: d.product_count as number | undefined,
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

      {items.length > 0 && (
        <ItemsTable
          items={items}
          baselines={baselineMap}
          onSetBaseline={(q, baseline) => upsertBL.mutate({ query: q, baseline })}
          onClearBaseline={(id) => deleteBL.mutate(id)}
        />
      )}

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

function ItemsTable({
  items, baselines, onSetBaseline, onClearBaseline,
}: {
  items: ItemState[]
  baselines: Map<string, SuiteBaseline>
  onSetBaseline: (query: string, baseline: SuiteBaseline['baseline']) => void
  onClearBaseline: (id: number) => void
}) {
  return (
    <div className="border border-gray-800 rounded overflow-hidden">
      {items.map(it => {
        const bl = baselines.get(it.query)
        return (
          <BaselineRow
            key={it.idx} item={it}
            baseline={bl}
            onSetBaseline={onSetBaseline}
            onClearBaseline={onClearBaseline}
          />
        )
      })}
    </div>
  )
}

function getPassFail(
  item: ItemState,
  baseline: SuiteBaseline | undefined,
): 'pass' | 'fail' | null {
  if (!baseline || baseline.baseline.min_count == null) return null
  if (item.product_count == null) return null
  return item.product_count >= baseline.baseline.min_count ? 'pass' : 'fail'
}

function BaselineRow({
  item, baseline, onSetBaseline, onClearBaseline,
}: {
  item: ItemState
  baseline?: SuiteBaseline
  onSetBaseline: (query: string, baseline: SuiteBaseline['baseline']) => void
  onClearBaseline: (id: number) => void
}) {
  const verdict = getPassFail(item, baseline)
  const hasBaseline = !!baseline

  return (
    <div
      className={clsx(
        'flex items-center gap-3 px-3 py-2 text-sm border-b border-gray-800/50 last:border-b-0',
        // pass/fail перекрывает стандартные статус-цвета строки
        verdict === 'pass' ? 'bg-emerald-950/30' :
        verdict === 'fail' ? 'bg-red-950/30' :
        item.status === 'running' ? 'bg-blue-950/20' :
        item.status === 'ok'      ? 'bg-green-950/10' :
        item.status === 'partial' ? 'bg-orange-950/15' :
        item.status === 'error'   ? 'bg-red-950/20' : '',
      )}
    >
      <span className="w-8 text-xs text-gray-500 font-mono">{item.idx}/{item.total}</span>
      <StatusIcon status={item.status} />
      <span className="flex-1 text-gray-200 truncate">{item.query}</span>
      {item.ms != null && <span className="text-xs text-gray-400 font-mono">{item.ms}ms</span>}
      {item.error && (
        <span className="text-xs text-red-400 max-w-[40%] truncate" title={item.error}>
          {item.error}
        </span>
      )}

      {/* Baseline-controls */}
      {hasBaseline ? (
        <span className="flex items-center gap-1.5 text-xs">
          <BaselineBadge item={item} baseline={baseline!} verdict={verdict} />
          <button
            type="button"
            onClick={() => {
              if (window.confirm(`Удалить baseline для «${item.query}»?`))
                onClearBaseline(baseline!.id)
            }}
            className="p-0.5 text-gray-500 hover:text-red-400 hover:bg-red-950/30 rounded"
            title="удалить baseline"
          >
            <X size={11} />
          </button>
        </span>
      ) : (
        item.status !== 'pending' && item.status !== 'running' && (
          <button
            type="button"
            onClick={() => {
              const suggested = item.product_count != null ? String(item.product_count) : '5'
              const minCountStr = window.prompt(
                `Baseline для «${item.query}»\n\nМинимальное число товаров (целое):`,
                suggested,
              )
              if (minCountStr == null) return
              const minCount = parseInt(minCountStr, 10)
              if (Number.isNaN(minCount)) {
                toast.error('Нужно целое число')
                return
              }
              onSetBaseline(item.query, { min_count: minCount })
            }}
            className="p-1 text-gray-500 hover:text-violet-300 hover:bg-violet-950/40 rounded"
            title={item.product_count != null
              ? `Зафиксировать как baseline (сейчас ${item.product_count} товаров)`
              : 'Зафиксировать как baseline'}
          >
            <Pin size={12} />
          </button>
        )
      )}
    </div>
  )
}

function BaselineBadge({
  item, baseline, verdict,
}: {
  item: ItemState
  baseline: SuiteBaseline
  verdict: 'pass' | 'fail' | null
}): ReactNode {
  const minCount = baseline.baseline.min_count

  const cls = verdict === 'pass'
    ? 'bg-emerald-900/60 text-emerald-200'
    : verdict === 'fail'
      ? 'bg-red-900/60 text-red-200'
      : 'bg-violet-900/40 text-violet-200'

  const label = minCount != null
    ? item.product_count != null
      ? `${item.product_count} / ≥${minCount}`
      : `≥${minCount}`
    : 'baseline'

  return (
    <span
      className={clsx('flex items-center gap-1 px-1.5 py-0.5 rounded font-mono', cls)}
      title={verdict === 'pass'
        ? `Pass: ${item.product_count} ≥ ${minCount}`
        : verdict === 'fail'
          ? `Fail: ${item.product_count} < ${minCount}`
          : 'есть baseline'}
    >
      {verdict === 'pass' && <Check size={9} />}
      {verdict === 'fail' && <X size={9} />}
      {verdict === null   && <Pin size={9} />}
      {label}
    </span>
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
