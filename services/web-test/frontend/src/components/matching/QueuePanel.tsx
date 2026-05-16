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
} from 'lucide-react'
import clsx from 'clsx'

import {
  fetchMatchingStatsExtended,
  fetchSkippedQueue,
  reEnqueueSkipped,
} from '../../lib/matching'
import { HowItWorks, TierChip } from './HowItWorks'
import { InfoTip } from './InfoTip'

// ── Main ──────────────────────────────────────────────────────────────────

export function QueuePanel() {
  return (
    <div className="space-y-4">
      <HowItWorks title="Что такое skipped и почему оффер тут">
        <SkippedExplainer />
      </HowItWorks>

      <QueueStrip />
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
        accent === 'violet' && 'text-violet-300',
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
                  selected.has(row.offer_id) && 'bg-violet-950/20',
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
          выбрано: <span className="font-mono text-violet-300">{selected.size}</span> из {items.length}
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
            onClick={() => {
              if (selected.size === 0) return
              const ok = window.confirm(`Re-enqueue ${selected.size} выбранных skipped → pending?`)
              if (ok) reEnqueueSelected.mutate(Array.from(selected))
            }}
            disabled={selected.size === 0 || reEnqueueSelected.isPending}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] rounded bg-violet-700 hover:bg-violet-600 disabled:opacity-30 text-white"
          >
            {reEnqueueSelected.isPending && <Loader2 size={10} className="animate-spin" />}
            re-enqueue выбранные ({selected.size})
          </button>
          <button
            type="button"
            onClick={() => {
              const ok = window.confirm(
                `Re-enqueue ВСЕХ ${total} skipped` +
                (hasFilters ? ' по текущему фильтру?' : '?') +
                '\n\nЭти записи вернутся в pending. Воркер обработает их в ближайшие тики.',
              )
              if (ok) reEnqueueAllFiltered.mutate()
            }}
            disabled={total === 0 || reEnqueueAllFiltered.isPending}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] rounded border border-amber-700/60 text-amber-300 hover:bg-amber-900/30 disabled:opacity-30"
          >
            {reEnqueueAllFiltered.isPending && <Loader2 size={10} className="animate-spin" />}
            re-enqueue ВСЕ ({total})
          </button>
        </div>
      </footer>
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
                  ? 'bg-violet-700 border-violet-600 text-white'
                  : 'bg-gray-900 border-gray-800 text-gray-400 hover:border-gray-700 hover:text-gray-200',
              )}
            >
              {opt.label}
              {opt.count !== undefined && (
                <span className={clsx(
                  'text-[9px]',
                  active ? 'text-violet-200' : 'text-gray-500',
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
        Типичные причины (поле <code className="text-violet-300">error_detail</code> в match_queue):
      </p>
      <ul className="ml-4 space-y-1 text-gray-300">
        <li><code className="text-violet-300">llm_unavailable</code> — qwen2.5 был оффлайн (Circuit Breaker open). После
          восстановления Ollama — re-enqueue их обратно.</li>
        <li><code className="text-violet-300">no_candidates</code> — T2 cosine search ничего не нашёл. Возможно
          в каталоге нет эмбеддинга такой игры. Сделай <TierChip tier="T2" /> warmup, потом re-enqueue.</li>
        <li><code className="text-violet-300">vec_below_threshold</code> — один кандидат, score 0.70-0.85. T3 не запускался
          (один слабый кандидат не стоит вызова LLM). Re-enqueue если каталог обновился.</li>
        <li><code className="text-violet-300">ml_no_match</code> — T3 LLM сказал что среди кандидатов совпадения нет.
          Обычно правильно — отдай оператору в manual review (<strong>/catalog → Очередь</strong>).</li>
        <li><code className="text-violet-300">llm_low_confidence</code> — T3 выбрал, но confidence &lt; 0.75. Скорее всего
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
