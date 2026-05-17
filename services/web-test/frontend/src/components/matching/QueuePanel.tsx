/**
 * QueuePanel — вкладка `/matching → Очередь`.
 *
 * Содержит:
 *   1. Stats-strip (queue counts + offers unmatched breakdown).
 *   2. Re-enqueue панель — таблица skipped с multi-filter (store + reason) и
 *      bulk-actions. Это новое UI: до этого было только через прямой SQL.
 *   3. Ссылка на текущий `/catalog → Очередь матчинга` (manual review),
 *      потому что в Phase 5 этот раздел переедет сюда.
 *
 * Polling: stats каждые 5 сек, skipped-list по запросу.
 */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Loader2, RefreshCw, ChevronRight, Filter, X, ArrowUpRight,
  Plus, Trash2, AlertCircle, Power,
} from 'lucide-react'
import clsx from 'clsx'

import {
  fetchMatchingStatsExtended,
  fetchSkippedQueue,
  reEnqueueSkipped,
  fetchQueueDepthHistory,
  fetchAutoRecoveryRules,
  createAutoRecoveryRule,
  updateAutoRecoveryRule,
  deleteAutoRecoveryRule,
  type AutoRecoveryRule,
} from '../../lib/matching'
import { HowItWorks, TierChip } from './HowItWorks'
import { InfoTip } from './InfoTip'
import { MetricSpark } from './MetricSpark'
import { ConfirmPanel } from './ConfirmPanel'

// ── Main ──────────────────────────────────────────────────────────────────

export function QueuePanel() {
  return (
    <div className="space-y-4">
      <HowItWorks title="Что такое skipped и почему оффер тут">
        <SkippedExplainer />
      </HowItWorks>

      <QueueStrip />
      <DepthChartSection />
      <ReasonBreakdownSection />
      <AutoRecoveryRulesSection />
      <ReEnqueueSection />
      <ManualQueueLink />
    </div>
  )
}

// ── Stats strip ───────────────────────────────────────────────────────────

function QueueStrip() {
  const stats = useQuery({
    queryKey: ['matching', 'stats-extended'],
    queryFn: fetchMatchingStatsExtended,
    refetchInterval: 5000,
  })

  const q = stats.data?.queue
  const total = q ? q.pending + q.processing + q.skipped + q.failed + q.done : 0

  return (
    <section className={clsx(
      'rounded-lg border border-gray-800/80 bg-gray-900/40 overflow-hidden',
      'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
    )}>
      <header className="px-4 py-2.5 border-b border-gray-800/60 bg-black/20 flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-300 flex items-center gap-2">
          match_queue
          <InfoTip text="Outbox для асинхронных T2/T3. Воркер берёт pending → processing → done | skipped | failed. enqueue идёт из ingest при miss T0+T1 (если ml_enabled)." />
        </h3>
        <span className="text-[10px] font-mono text-gray-500">total {total}</span>
      </header>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-px bg-gray-800/40">
        <QueueCell label="pending" value={q?.pending} accent="amber"
          hint="Ждут следующего тика воркера" />
        <QueueCell label="processing" value={q?.processing} accent="violet"
          hint="Сейчас в работе у воркера" />
        <QueueCell label="skipped" value={q?.skipped} accent="gray"
          hint="ML дошёл до T4 — оператор должен ручно сматчить или re-enqueue" />
        <QueueCell label="failed" value={q?.failed} accent="red"
          hint="Исчерпан retry backoff — error_detail хранит последнюю ошибку" />
        <QueueCell label="done" value={q?.done} accent="green"
          hint="Авто-сматчены успешно" />
      </div>
    </section>
  )
}

function QueueCell({ label, value, accent, hint }: {
  label: string; value: number | undefined
  accent: 'amber' | 'violet' | 'gray' | 'red' | 'green'
  hint: string
}) {
  return (
    <div className="bg-gray-900/40 px-4 py-3 space-y-1 group">
      <div className="text-[9px] uppercase tracking-widest text-gray-500 font-mono flex items-center gap-1">
        {label}
        <InfoTip text={hint} side="bottom" />
      </div>
      <div className={clsx(
        'font-mono text-2xl tabular-nums',
        accent === 'amber'  && 'text-amber-300',
        accent === 'violet' && 'text-indigo-300',
        accent === 'gray'   && 'text-gray-300',
        accent === 'red'    && 'text-red-300',
        accent === 'green'  && 'text-green-300',
      )}>{value ?? '—'}</div>
    </div>
  )
}

// ── Skipped re-enqueue ─────────────────────────────────────────────────────

const REASON_OPTIONS = [
  { value: 'llm_unavailable',     label: 'llm_unavailable',     hint: 'qwen2.5 был недоступен на момент обработки' },
  { value: 'no_candidates',       label: 'no_candidates',       hint: 'T2 вообще не нашёл похожих в эмбеддингах' },
  { value: 'vec_below_threshold', label: 'vec_below_threshold', hint: '1 кандидат, но score ниже 0.85 — слабый, не пускали к T3' },
  { value: 'ml_no_match',         label: 'ml_no_match',         hint: 'T3 LLM сказал "нет совпадения"' },
  { value: 'llm_low_confidence',  label: 'llm_low_confidence',  hint: 'T3 LLM выбрал кандидата, но confidence < 0.75' },
  { value: 'llm_parse_failed',    label: 'llm_parse_failed',    hint: 'LLM вернул невалидный JSON (rare)' },
]

function ReEnqueueSection() {
  const qc = useQueryClient()
  const [storeFilter, setStoreFilter] = useState<string[]>([])
  const [reasonFilter, setReasonFilter] = useState<string[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [page, setPage] = useState(0)
  const limit = 50

  const skipped = useQuery({
    queryKey: ['matching', 'skipped', storeFilter, reasonFilter, page],
    queryFn: () => fetchSkippedQueue({
      store_slug: storeFilter,
      reason: reasonFilter,
      limit,
      offset: page * limit,
    }),
    refetchInterval: 15_000,
  })

  const allStores = Object.keys(skipped.data?.stores ?? {}).sort()

  const reEnqueueSelected = useMutation({
    mutationFn: (ids: number[]) => reEnqueueSkipped({ offer_ids: ids }),
    onSuccess: (data) => {
      toast.success(`Re-enqueued ${data.re_enqueued} из ${data.requested}`)
      setSelected(new Set())
      qc.invalidateQueries({ queryKey: ['matching', 'skipped'] })
      qc.invalidateQueries({ queryKey: ['matching', 'stats-extended'] })
      qc.invalidateQueries({ queryKey: ['catalog', 'ml-status'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const reEnqueueAllFiltered = useMutation({
    mutationFn: () => reEnqueueSkipped({
      store_slug: storeFilter.length > 0 ? storeFilter : undefined,
      reason: reasonFilter.length > 0 ? reasonFilter : undefined,
    }),
    onSuccess: (data) => {
      toast.success(`Re-enqueued ВСЕХ ${data.re_enqueued} skipped по фильтру`)
      setSelected(new Set())
      qc.invalidateQueries({ queryKey: ['matching', 'skipped'] })
      qc.invalidateQueries({ queryKey: ['matching', 'stats-extended'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  // §G inline confirms — заменяют window.confirm для двух bulk-операций.
  const [confirmSelected, setConfirmSelected] = useState(false)
  const [confirmAll, setConfirmAll] = useState(false)

  const handleSelectAll = () => {
    if (!skipped.data) return
    const allIds = skipped.data.items.map(x => x.offer_id)
    if (allIds.every(id => selected.has(id))) {
      setSelected(new Set())
    } else {
      setSelected(new Set(allIds))
    }
  }

  const toggleSelect = (id: number) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  const total = skipped.data?.total ?? 0
  const items = skipped.data?.items ?? []
  const hasFilters = storeFilter.length > 0 || reasonFilter.length > 0

  return (
    <section className={clsx(
      'rounded-lg border border-gray-800/80 bg-gray-900/40 overflow-hidden',
      'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
    )}>
      <header className="px-4 py-2.5 border-b border-gray-800/60 bg-black/20 flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-300 flex items-center gap-2">
          <RefreshCw size={11} />
          re-enqueue skipped
          <InfoTip text="Возвращает skipped → pending. После этого воркер обработает их в следующем тике. Поможет, например, после ollama pull qwen2.5 — все llm_unavailable станут сматчатся." />
        </h3>
        <span className="text-[10px] font-mono text-gray-500">
          {total} skipped {hasFilters && '(по фильтру)'}
        </span>
      </header>

      {/* Filters */}
      <div className="px-4 py-3 space-y-2.5 border-b border-gray-800/60 bg-black/10">
        <ChipGroup
          icon={<Filter size={10} />}
          label="store"
          options={allStores.map(s => ({
            value: s,
            label: s,
            count: skipped.data?.stores[s],
          }))}
          selected={storeFilter}
          onChange={(v) => { setStoreFilter(v); setPage(0) }}
        />
        <ChipGroup
          icon={<Filter size={10} />}
          label="reason"
          options={REASON_OPTIONS.map(r => ({
            value: r.value,
            label: r.label,
            count: skipped.data?.reasons[r.value],
            hint: r.hint,
          }))}
          selected={reasonFilter}
          onChange={(v) => { setReasonFilter(v); setPage(0) }}
        />
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        {skipped.isLoading && (
          <div className="px-4 py-8 text-center text-xs text-gray-500">
            <Loader2 size={14} className="animate-spin inline mr-2" />
            загружаю skipped…
          </div>
        )}
        {!skipped.isLoading && items.length === 0 && (
          <div className="px-4 py-8 text-center text-xs text-gray-500">
            нет skipped с такими фильтрами
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-xs">
            <thead className="bg-gray-900/60 text-[10px] uppercase tracking-wider text-gray-500 font-mono">
              <tr>
                <th className="px-3 py-2 text-left w-8">
                  <input
                    type="checkbox"
                    onChange={handleSelectAll}
                    checked={items.length > 0 && items.every(x => selected.has(x.offer_id))}
                    className="cursor-pointer"
                  />
                </th>
                <th className="px-3 py-2 text-left">offer_id</th>
                <th className="px-3 py-2 text-left">store</th>
                <th className="px-3 py-2 text-left">title</th>
                <th className="px-3 py-2 text-left">reason</th>
                <th className="px-3 py-2 text-right">attempts</th>
                <th className="px-3 py-2 text-right">processed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {items.map(row => (
                <tr key={row.id} className={clsx(
                  'hover:bg-gray-800/30 transition-colors',
                  selected.has(row.offer_id) && 'bg-indigo-950/20',
                )}>
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selected.has(row.offer_id)}
                      onChange={() => toggleSelect(row.offer_id)}
                      className="cursor-pointer"
                    />
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-400">#{row.offer_id}</td>
                  <td className="px-3 py-2 font-mono text-gray-500">{row.store_slug}</td>
                  <td className="px-3 py-2 text-gray-200 max-w-xs truncate" title={row.title_raw}>
                    {row.title_raw}
                  </td>
                  <td className="px-3 py-2 font-mono text-[10px] text-amber-300/80">
                    {row.error_detail ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-500">{row.attempts}</td>
                  <td className="px-3 py-2 text-right text-[10px] text-gray-500 font-mono">
                    {row.processed_at ? new Date(row.processed_at).toLocaleString('ru-RU') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer */}
      <footer className="px-4 py-3 border-t border-gray-800/60 bg-black/20 flex items-center justify-between gap-3">
        <div className="text-[11px] text-gray-400">
          выбрано: <span className="font-mono text-indigo-300">{selected.size}</span> из {items.length}
          {' · '}
          page {page + 1} / {Math.max(1, Math.ceil(total / limit))}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-2 py-1 text-[11px] text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded disabled:opacity-30"
          >
            ←
          </button>
          <button
            type="button"
            onClick={() => setPage(p => p + 1)}
            disabled={(page + 1) * limit >= total}
            className="px-2 py-1 text-[11px] text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded disabled:opacity-30"
          >
            →
          </button>
          <div className="w-px h-5 bg-gray-700 mx-1" />
          <button
            type="button"
            onClick={() => setConfirmSelected(true)}
            disabled={selected.size === 0 || reEnqueueSelected.isPending}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-30 text-white"
          >
            {reEnqueueSelected.isPending && <Loader2 size={10} className="animate-spin" />}
            re-enqueue выбранные ({selected.size})
          </button>
          <button
            type="button"
            onClick={() => setConfirmAll(true)}
            disabled={total === 0 || reEnqueueAllFiltered.isPending}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] rounded border border-amber-700/60 text-amber-300 hover:bg-amber-900/30 disabled:opacity-30"
          >
            {reEnqueueAllFiltered.isPending && <Loader2 size={10} className="animate-spin" />}
            re-enqueue ВСЕ ({total})
          </button>
        </div>
      </footer>

      {/* §G inline confirms */}
      <ConfirmPanel
        open={confirmSelected}
        variant="amber"
        title={`re-enqueue ${selected.size} выбранных`}
        description="Выбранные skipped будут возвращены в pending. Воркер обработает их в ближайший тик."
        impact={[
          `${selected.size} skipped → pending · attempts=0`,
          'обработка начнётся в течение 10 сек',
        ]}
        confirmLabel={`re-enqueue ${selected.size}`}
        loading={reEnqueueSelected.isPending}
        onConfirm={() => {
          reEnqueueSelected.mutate(Array.from(selected))
          setConfirmSelected(false)
        }}
        onCancel={() => setConfirmSelected(false)}
        className="mx-4 mb-4"
      />
      <ConfirmPanel
        open={confirmAll}
        variant="amber"
        title={`re-enqueue ВСЕ ${total} skipped`}
        description={hasFilters
          ? 'Все skipped по текущему фильтру → pending.'
          : 'Все skipped в системе → pending. Это много — учитывай нагрузку на воркер.'}
        filterSummary={hasFilters ? [
          ...(storeFilter.length > 0 ? [{ tone: 'neutral' as const, label: `store · ${storeFilter.join(', ')}` }] : []),
          ...(reasonFilter.length > 0 ? [{ tone: 'amber' as const, label: `reason · ${reasonFilter.join(', ')}` }] : []),
        ] : undefined}
        impact={[
          `${total} skipped → pending`,
          hasFilters
            ? 'Только с текущим фильтром (store/reason)'
            : 'Без фильтров — это все skipped в БД',
        ]}
        confirmLabel={`re-enqueue ${total}`}
        loading={reEnqueueAllFiltered.isPending}
        onConfirm={() => {
          reEnqueueAllFiltered.mutate()
          setConfirmAll(false)
        }}
        onCancel={() => setConfirmAll(false)}
        className="mx-4 mb-4"
      />
    </section>
  )
}

// ── Chip filter group ──────────────────────────────────────────────────────

function ChipGroup({ icon, label, options, selected, onChange }: {
  icon: React.ReactNode
  label: string
  options: Array<{ value: string; label: string; count?: number; hint?: string }>
  selected: string[]
  onChange: (v: string[]) => void
}) {
  const toggle = (v: string) => {
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v])
  }
  return (
    <div className="flex items-start gap-3">
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-gray-500 font-mono pt-1 w-16 flex-shrink-0">
        {icon}{label}
      </div>
      <div className="flex flex-wrap gap-1.5 flex-1">
        {options.length === 0 && (
          <span className="text-[10px] text-gray-600 italic py-1">нет данных</span>
        )}
        {options.map(opt => {
          const active = selected.includes(opt.value)
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => toggle(opt.value)}
              title={opt.hint}
              className={clsx(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded font-mono text-[10px] border transition-colors',
                active
                  ? 'bg-indigo-700 border-indigo-600 text-white'
                  : 'bg-gray-900 border-gray-800 text-gray-400 hover:border-gray-700 hover:text-gray-200',
              )}
            >
              {opt.label}
              {opt.count !== undefined && (
                <span className={clsx(
                  'text-[9px]',
                  active ? 'text-indigo-200' : 'text-gray-500',
                )}>
                  · {opt.count}
                </span>
              )}
              {active && <X size={9} className="ml-0.5" />}
            </button>
          )
        })}
        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="text-[10px] text-gray-500 hover:text-gray-300 px-2 py-0.5"
          >
            очистить
          </button>
        )}
      </div>
    </div>
  )
}

// ── §D.1 Depth chart 24h ───────────────────────────────────────────────────

function DepthChartSection() {
  const depthQ = useQuery({
    queryKey: ['matching', 'queue-depth-24h'],
    queryFn: () => fetchQueueDepthHistory({ range_hours: 24, bucket_minutes: 60 }),
    refetchInterval: 60_000,
    retry: false,
  })

  const depth = depthQ.data
  if (!depth || depth.points.length === 0) {
    return null  // ничего не показываем если backend не отдал — gracefully degrade
  }

  // ETA пустоты: при положительном drainage_rate_per_min — через сколько pending → 0.
  const etaMinutes = depth.drainage_rate_per_min > 0
    ? Math.ceil(depth.current / depth.drainage_rate_per_min)
    : null

  return (
    <section className={clsx(
      'rounded-lg border border-gray-800/80 bg-gray-900/40 overflow-hidden',
      'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
    )}>
      <header className="px-4 py-2.5 border-b border-gray-800/60 bg-black/20 flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-300 flex items-center gap-2">
          depth · 24h
          <InfoTip text="Глубина очереди (pending+processing) за последние 24 часа. Реконструкция на основе created_at / processed_at — не точный snapshot. Drainage rate показывает изменение pending за последний bucket." />
        </h3>
        <div className="flex items-center gap-3 text-[10px] font-mono">
          <span className="text-gray-500">peak <span className="text-gray-300 tabular-nums">{depth.peak}</span></span>
          <span className="text-gray-500">now <span className="text-gray-300 tabular-nums">{depth.current}</span></span>
          {depth.drainage_rate_per_min !== 0 && (
            <span className={clsx(
              'tabular-nums',
              depth.drainage_rate_per_min > 0 ? 'text-emerald-400' : 'text-rose-400',
            )}>
              {depth.drainage_rate_per_min > 0 ? '↓' : '↑'} {Math.abs(depth.drainage_rate_per_min).toFixed(1)}/мин
            </span>
          )}
          {etaMinutes !== null && etaMinutes < 1440 && (
            <span className="text-gray-500">
              ETA пустоты <span className="text-emerald-400 tabular-nums">~{etaMinutes}м</span>
            </span>
          )}
        </div>
      </header>
      <div className="p-4">
        <MetricSpark
          values={depth.points.map(p => p.depth)}
          tone={depth.current > 100 ? 'warn' : 'info'}
          width={900}
          height={48}
        />
      </div>
    </section>
  )
}

// ── §D.2 Reason breakdown — horizontal bars + click re-enqueue ─────────────

const REASON_HINTS: Record<string, string> = {
  llm_unavailable: 'qwen2.5 был оффлайн — re-enqueue после ollama pull',
  no_candidates: 'T2 не нашёл похожих — попробовать warmup эмбеддингов',
  vec_below_threshold: '1 кандидат с score 0.70-0.85 — слабый, не пускали к T3',
  ml_no_match: 'T3 LLM сказал "нет совпадения"',
  llm_low_confidence: 'T3 LLM выбрал кандидата, но confidence < 0.75',
  llm_disabled: 'legacy — было до hardening 2026-05-16',
  llm_parse_failed: 'LLM вернул невалидный JSON (rare)',
}

function ReasonBreakdownSection() {
  const qc = useQueryClient()
  const skippedQ = useQuery({
    queryKey: ['matching', 'skipped', [], [], 0],
    queryFn: () => fetchSkippedQueue({ limit: 1 }),
    refetchInterval: 15_000,
  })

  const [confirmReason, setConfirmReason] = useState<string | null>(null)

  const reenqueueByReason = useMutation({
    mutationFn: (reason: string) => reEnqueueSkipped({ reason: [reason] }),
    onSuccess: (data, reason) => {
      toast.success(`Re-enqueued ${data.re_enqueued} офферов с reason=${reason}`)
      qc.invalidateQueries({ queryKey: ['matching', 'skipped'] })
      qc.invalidateQueries({ queryKey: ['matching', 'stats-extended'] })
      setConfirmReason(null)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const reasons = skippedQ.data?.reasons ?? {}
  const total = Object.values(reasons).reduce((a, b) => a + b, 0)
  if (total === 0) return null
  const sorted = Object.entries(reasons).sort(([, a], [, b]) => b - a).slice(0, 8)

  return (
    <section className={clsx(
      'rounded-lg border border-gray-800/80 bg-gray-900/40 overflow-hidden',
      'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
    )}>
      <header className="px-4 py-2.5 border-b border-gray-800/60 bg-black/20 flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-300 flex items-center gap-2">
          breakdown · skipped reasons
          <InfoTip text="Распределение skipped по reasons. Клик на строку — inline confirm для re-enqueue всех офферов с этим reason." />
        </h3>
        <span className="text-[10px] font-mono text-gray-500">total {total}</span>
      </header>
      <div className="p-4 space-y-1.5">
        {sorted.map(([reason, count]) => {
          const pct = total > 0 ? (count / total) * 100 : 0
          const hint = REASON_HINTS[reason]
          return (
            <div key={reason} className="space-y-1">
              <button
                type="button"
                onClick={() => setConfirmReason(reason)}
                className="w-full group flex items-center gap-2 text-left hover:bg-gray-800/40 rounded px-1.5 py-1 transition-colors"
              >
                <code className="font-mono text-[11px] text-amber-300/90 w-44 truncate shrink-0">
                  {reason}
                </code>
                <div className="flex-1 h-2 bg-gray-800/60 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-amber-500/60 transition-[width] duration-300"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="font-mono tabular-nums text-xs text-gray-300 w-12 text-right shrink-0">{count}</span>
                <span className="font-mono tabular-nums text-[10px] text-gray-500 w-10 text-right shrink-0">{pct.toFixed(0)}%</span>
                <span className="opacity-0 group-hover:opacity-100 transition-opacity text-[10px] text-indigo-300 shrink-0">
                  re-enqueue →
                </span>
              </button>
              {hint && (
                <p className="ml-[12.5rem] text-[10px] text-gray-500">{hint}</p>
              )}

              <ConfirmPanel
                open={confirmReason === reason}
                variant="amber"
                title={`re-enqueue all by reason='${reason}'`}
                description={`Вернуть в pending все ${count} офферов с этим reason.`}
                filterSummary={[
                  { tone: 'amber', label: `reason · ${reason}` },
                  { tone: 'neutral', label: `count · ${count}` },
                ]}
                impact={[
                  `${count} skipped → pending · attempts=0`,
                  'воркер обработает в ближайшие тики',
                  hint || 'смотри handoff §D-skipped reasons',
                ]}
                confirmLabel={`re-enqueue ${count}`}
                loading={reenqueueByReason.isPending}
                onConfirm={() => reenqueueByReason.mutate(reason)}
                onCancel={() => setConfirmReason(null)}
              />
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ── §D.3 Auto-recovery rules CRUD ──────────────────────────────────────────

function AutoRecoveryRulesSection() {
  const qc = useQueryClient()
  const rulesQ = useQuery({
    queryKey: ['matching', 'auto-recovery-rules'],
    queryFn: fetchAutoRecoveryRules,
    refetchInterval: 30_000,
    retry: false,
  })

  const toggleRule = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      updateAutoRecoveryRule(id, { enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['matching', 'auto-recovery-rules'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const removeRule = useMutation({
    mutationFn: (id: number) => deleteAutoRecoveryRule(id),
    onSuccess: () => {
      toast.success('Правило удалено')
      qc.invalidateQueries({ queryKey: ['matching', 'auto-recovery-rules'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const [showCreate, setShowCreate] = useState(false)

  const rules = rulesQ.data ?? []

  return (
    <section className={clsx(
      'rounded-lg border border-gray-800/80 bg-gray-900/40 overflow-hidden',
      'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
    )}>
      <header className="px-4 py-2.5 border-b border-gray-800/60 bg-black/20 flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-300 flex items-center gap-2">
          auto-recovery rules
          <InfoTip text="Правила автоматического восстановления. Реагируют на события (модель закрылась после downtime) и выполняют действия (re-enqueue all llm_unavailable). Runner-job выполняет правила раз в минуту." />
        </h3>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono text-indigo-300 hover:text-indigo-200 hover:bg-indigo-950/30"
        >
          <Plus size={11} /> add
        </button>
      </header>

      <div className="p-3 space-y-1.5">
        {rulesQ.isLoading && (
          <div className="text-xs text-gray-500 py-2 text-center">загружаю…</div>
        )}
        {!rulesQ.isLoading && rules.length === 0 && !showCreate && (
          <div className="text-xs text-gray-500 py-3 text-center">
            нет правил. <button onClick={() => setShowCreate(true)} className="text-indigo-300 hover:text-indigo-200">создать первое</button>
          </div>
        )}
        {rules.map(rule => (
          <RuleRow
            key={rule.id}
            rule={rule}
            onToggle={(e) => toggleRule.mutate({ id: rule.id, enabled: e })}
            onDelete={() => removeRule.mutate(rule.id)}
          />
        ))}
        {showCreate && (
          <RuleCreateForm
            onCancel={() => setShowCreate(false)}
            onCreated={() => {
              setShowCreate(false)
              qc.invalidateQueries({ queryKey: ['matching', 'auto-recovery-rules'] })
            }}
          />
        )}
      </div>
    </section>
  )
}

function RuleRow({
  rule, onToggle, onDelete,
}: {
  rule: AutoRecoveryRule
  onToggle: (enabled: boolean) => void
  onDelete: () => void
}) {
  return (
    <div className={clsx(
      'flex items-center gap-2 px-2 py-1.5 rounded border text-xs',
      rule.enabled ? 'border-gray-800 bg-gray-900/40' : 'border-gray-800/50 bg-gray-900/20 opacity-60',
    )}>
      <button
        type="button"
        onClick={() => onToggle(!rule.enabled)}
        title={rule.enabled ? 'disable' : 'enable'}
        className={clsx(
          'shrink-0 inline-flex items-center justify-center w-4 h-4 rounded-full border',
          rule.enabled
            ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300'
            : 'bg-gray-800 border-gray-700 text-gray-600',
        )}
      >
        <Power size={9} />
      </button>
      <code className="font-mono text-indigo-300 w-32 truncate shrink-0" title={rule.name}>
        {rule.name}
      </code>
      <span className="font-mono text-[10px] text-gray-500 truncate flex-1" title={JSON.stringify(rule.condition)}>
        if: {JSON.stringify(rule.condition)}
      </span>
      <span className="font-mono text-[10px] text-gray-500 truncate flex-1" title={JSON.stringify(rule.action)}>
        then: {JSON.stringify(rule.action)}
      </span>
      <span className={clsx(
        'text-[10px] font-mono font-semibold uppercase shrink-0',
        rule.enabled ? 'text-emerald-400' : 'text-gray-600',
      )}>
        {rule.enabled ? '● armed' : '○ off'}
      </span>
      <button
        type="button"
        onClick={onDelete}
        className="shrink-0 text-gray-600 hover:text-rose-300 p-0.5"
        title="удалить"
      >
        <Trash2 size={11} />
      </button>
    </div>
  )
}

function RuleCreateForm({
  onCancel, onCreated,
}: { onCancel: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [conditionText, setConditionText] = useState(
    '{"type":"circuit_state","model":"qwen2.5:7b-instruct","becomes":"closed"}',
  )
  const [actionText, setActionText] = useState(
    '{"type":"re_enqueue_skipped","filters":{"reason":["llm_unavailable"]}}',
  )

  const create = useMutation({
    mutationFn: () => {
      let condition: Record<string, unknown>
      let action: Record<string, unknown>
      try {
        condition = JSON.parse(conditionText)
        action = JSON.parse(actionText)
      } catch (e) {
        throw new Error(`Невалидный JSON: ${(e as Error).message}`)
      }
      return createAutoRecoveryRule({ name, condition, action, enabled: true })
    },
    onSuccess: () => {
      toast.success(`Правило ${name} создано`)
      onCreated()
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <div className="p-3 rounded border border-indigo-900/40 bg-indigo-950/20 space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-gray-500 uppercase tracking-wider font-mono w-16">name</span>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="qwen-recovery"
          className="flex-1 px-2 py-1 bg-gray-900 border border-gray-800 rounded font-mono text-indigo-300"
        />
      </div>
      <div className="flex items-start gap-2">
        <span className="text-[10px] text-gray-500 uppercase tracking-wider font-mono w-16 mt-1">if</span>
        <textarea
          value={conditionText}
          onChange={e => setConditionText(e.target.value)}
          rows={2}
          className="flex-1 px-2 py-1 bg-gray-900 border border-gray-800 rounded font-mono text-xs text-gray-200"
        />
      </div>
      <div className="flex items-start gap-2">
        <span className="text-[10px] text-gray-500 uppercase tracking-wider font-mono w-16 mt-1">then</span>
        <textarea
          value={actionText}
          onChange={e => setActionText(e.target.value)}
          rows={2}
          className="flex-1 px-2 py-1 bg-gray-900 border border-gray-800 rounded font-mono text-xs text-gray-200"
        />
      </div>
      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          onClick={() => create.mutate()}
          disabled={!name.trim() || create.isPending}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 text-white"
        >
          {create.isPending && <Loader2 size={11} className="animate-spin" />}
          создать
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-2.5 py-1 text-xs text-gray-500 hover:text-gray-200"
        >
          отмена
        </button>
        <span className="text-[10px] text-gray-500 ml-auto">
          <AlertCircle size={9} className="inline mr-0.5" />
          runner ещё не реализован — правила сохраняются, но пока не выполняются
        </span>
      </div>
    </div>
  )
}

// ── Manual queue link ──────────────────────────────────────────────────────

function ManualQueueLink() {
  return (
    <div className={clsx(
      'rounded-lg border border-dashed border-gray-700/60 bg-gray-900/20',
      'px-4 py-3 flex items-center justify-between gap-3',
    )}>
      <div className="text-xs text-gray-400 flex items-center gap-2">
        <ChevronRight size={12} className="text-gray-600" />
        <span>
          Ручной матчинг unmatched offers (выбор кандидата вручную) — пока на странице{' '}
          <strong className="text-gray-300">/catalog → Очередь матчинга</strong>.
          Перенос сюда — в WT-F11 (roadmap).
        </span>
      </div>
      <Link
        to="/catalog"
        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] rounded border border-gray-700 text-gray-400 hover:text-gray-200 hover:bg-gray-800"
      >
        перейти <ArrowUpRight size={11} />
      </Link>
    </div>
  )
}

// ── Skipped explainer ──────────────────────────────────────────────────────

function SkippedExplainer() {
  return (
    <>
      <p>
        Если воркер прогнал оффер через T2/T3, но не получил confident-результат —
        запись финализируется как <span className="font-mono text-amber-300">skipped</span>.
        Это конечный статус: воркер сам её не подберёт, пока кто-то не вернёт её в pending.
      </p>
      <p className="text-gray-400">
        Типичные причины (поле <code className="text-indigo-300">error_detail</code> в match_queue):
      </p>
      <ul className="ml-4 space-y-1 text-gray-300">
        <li><code className="text-indigo-300">llm_unavailable</code> — qwen2.5 был оффлайн (Circuit Breaker open). После
          восстановления Ollama — re-enqueue их обратно.</li>
        <li><code className="text-indigo-300">no_candidates</code> — T2 cosine search ничего не нашёл. Возможно
          в каталоге нет эмбеддинга такой игры. Сделай <TierChip tier="T2" /> warmup, потом re-enqueue.</li>
        <li><code className="text-indigo-300">vec_below_threshold</code> — один кандидат, score 0.70-0.85. T3 не запускался
          (один слабый кандидат не стоит вызова LLM). Re-enqueue если каталог обновился.</li>
        <li><code className="text-indigo-300">ml_no_match</code> — T3 LLM сказал что среди кандидатов совпадения нет.
          Обычно правильно — отдай оператору в manual review (<strong>/catalog → Очередь</strong>).</li>
        <li><code className="text-indigo-300">llm_low_confidence</code> — T3 выбрал, но confidence &lt; 0.75. Скорее всего
          действительно неоднозначно. Manual review.</li>
      </ul>
      <p className="text-gray-400">
        Re-enqueue имеет смысл когда что-то изменилось: загрузил новую модель, обогатил эмбеддинги,
        добавил алиасы. Иначе результат будет тот же.
      </p>
    </>
  )
}

void useMemo
