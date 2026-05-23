/**
 * ReportTab — отчёт по матчингу (`/matching → Отчёт`, CAT-17).
 *
 * 4 секции в вертикальном стеке:
 *   1. Top unmatched — список title-групп без матча (что импортировать в catalog).
 *   2. Coverage by store — per-store: matched/unmatched/rejected % за период.
 *   3. Activity timeline — match_log GROUP BY day×action за период.
 *   4. SLA per tier — share T0/T1/T2/T3/unmatched + latency T2/T3 percentiles.
 *
 * Каждая секция:
 *   - Имеет фильтр по `days` (7 / 14 / 30 / 90).
 *   - Отдельный useQuery с TanStack Query, cache-key `['matching','report',name,days]`.
 *   - HelpBox рядом с заголовком — объясняет метрику и операторские действия.
 *
 * Не использует Recharts для всех графиков — Top unmatched и SLA — это таблицы
 * (точнее читаются), Coverage и Activity — stacked bar / line через простой
 * inline-SVG (не тянем зависимость). Это держит компонент компактным и
 * предсказуемым.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'

import { HelpBox } from '../shared/HelpBox'
import {
  fetchTopUnmatched,
  fetchCoverageByStore,
  fetchActivityTimeline,
  fetchSlaStats,
  type CoverageStoreItem,
  type ActivityRow,
} from '../../lib/matching-report'

// ─── Section wrapper ───────────────────────────────────────────────────────

function ReportSection({
  title,
  helpTopic,
  days,
  onDaysChange,
  daysOptions = [7, 14, 30],
  children,
  isLoading = false,
}: {
  title: string
  helpTopic: 'matching.report_top_unmatched' | 'matching.report_coverage' |
             'matching.report_activity' | 'matching.report_sla'
  days: number
  onDaysChange: (d: number) => void
  daysOptions?: number[]
  children: React.ReactNode
  isLoading?: boolean
}) {
  return (
    <section className="bg-gray-900/40 rounded border border-gray-800/60 p-4">
      <header className="flex items-center justify-between mb-3 pb-2 border-b border-gray-800/40">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-100">
          {title}
          <HelpBox topic={helpTopic} />
          {isLoading && (
            <RefreshCw size={12} className="text-violet-400 animate-spin" />
          )}
        </h3>
        <div className="flex items-center gap-1 text-[11px]">
          <span className="text-gray-500">период:</span>
          {daysOptions.map(d => (
            <button
              key={d}
              type="button"
              onClick={() => onDaysChange(d)}
              className={[
                'px-2 py-0.5 rounded font-mono transition-colors',
                d === days
                  ? 'bg-violet-700/30 text-violet-200 border border-violet-700/40'
                  : 'text-gray-500 hover:text-gray-200 border border-gray-800/40',
              ].join(' ')}
            >
              {d}д
            </button>
          ))}
        </div>
      </header>
      {children}
    </section>
  )
}

// ─── 1. Top unmatched ──────────────────────────────────────────────────────

function TopUnmatchedSection() {
  const [days, setDays] = useState(7)
  const [minCount, setMinCount] = useState(2)
  const query = useQuery({
    queryKey: ['matching', 'report', 'top-unmatched', days, minCount],
    queryFn: () => fetchTopUnmatched({ days, limit: 50, min_count: minCount }),
    // 60с stale — отчёт read-only, переключение между табами не должно
    // пере-фетчить агрегаты (которые в БД меняются только при ingest/manual).
    staleTime: 60_000,
  })

  return (
    <ReportSection
      title="Top unmatched — что чаще всего не сматчено"
      helpTopic="matching.report_top_unmatched"
      days={days}
      onDaysChange={setDays}
      isLoading={query.isFetching}
    >
      <div className="flex items-center gap-2 mb-3 text-[11px]">
        <span className="text-gray-500">мин. count:</span>
        {[1, 2, 5, 10].map(n => (
          <button
            key={n}
            type="button"
            onClick={() => setMinCount(n)}
            className={[
              'px-2 py-0.5 rounded font-mono transition-colors',
              n === minCount
                ? 'bg-violet-700/30 text-violet-200 border border-violet-700/40'
                : 'text-gray-500 hover:text-gray-200 border border-gray-800/40',
            ].join(' ')}
          >
            ≥{n}
          </button>
        ))}
      </div>

      {query.isError && (
        <div className="text-xs text-red-400">Ошибка загрузки: {String(query.error)}</div>
      )}
      {query.data && query.data.items.length === 0 && (
        <div className="text-xs text-gray-500 italic">
          Нет unmatched title с count ≥ {minCount} за период {days}д. Всё ок.
        </div>
      )}
      {query.data && query.data.items.length > 0 && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase text-gray-500 border-b border-gray-800/40">
              <th className="text-left py-1.5 px-2">title_norm</th>
              <th className="text-right py-1.5 px-2">count</th>
              <th className="text-left py-1.5 px-2">пример (raw)</th>
              <th className="text-left py-1.5 px-2">магазины</th>
              <th className="text-left py-1.5 px-2">последний раз</th>
            </tr>
          </thead>
          <tbody>
            {query.data.items.map(item => (
              <tr
                key={item.title_norm}
                className="border-b border-gray-900/40 hover:bg-gray-900/20"
              >
                <td className="py-1.5 px-2 font-mono text-indigo-300/90 max-w-[280px] truncate">
                  {item.title_norm}
                </td>
                <td className="py-1.5 px-2 text-right font-mono text-violet-300 font-semibold">
                  {item.count}
                </td>
                <td className="py-1.5 px-2 text-gray-300 max-w-[280px] truncate" title={item.sample_title_raw}>
                  {item.sample_title_raw}
                </td>
                <td className="py-1.5 px-2 text-gray-500 text-[10px] font-mono">
                  {item.stores.slice(0, 3).join(', ')}
                  {item.stores.length > 3 && ` +${item.stores.length - 3}`}
                </td>
                <td className="py-1.5 px-2 text-gray-500 text-[10px] font-mono">
                  {new Date(item.last_seen).toLocaleDateString('ru-RU')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ReportSection>
  )
}

// ─── 2. Coverage by store ──────────────────────────────────────────────────

function CoverageBar({ row }: { row: CoverageStoreItem }) {
  // Inline stacked bar — без Recharts.
  const segments: Array<{ key: string; value: number; color: string; label: string }> = [
    { key: 'matched_auto',   value: row.matched_auto,   color: 'bg-emerald-600',  label: 'auto' },
    { key: 'matched_manual', value: row.matched_manual, color: 'bg-emerald-400',  label: 'manual' },
    { key: 'pending_ml',     value: row.pending_ml,     color: 'bg-violet-500',   label: 'pending_ml' },
    { key: 'unmatched',      value: row.unmatched,      color: 'bg-amber-600',    label: 'unmatched' },
    { key: 'rejected',       value: row.rejected,       color: 'bg-rose-600',     label: 'rejected' },
  ]
  const total = row.total || 1  // защита от деления на 0

  return (
    <div className="flex h-2 rounded overflow-hidden border border-gray-800/40">
      {segments.map(s => {
        const pct = (100 * s.value) / total
        if (pct < 0.5) return null  // не рисуем сегменты <0.5%
        return (
          <div
            key={s.key}
            className={s.color}
            style={{ width: `${pct}%` }}
            title={`${s.label}: ${s.value} (${pct.toFixed(1)}%)`}
          />
        )
      })}
    </div>
  )
}

function CoverageSection() {
  const [days, setDays] = useState(7)
  const query = useQuery({
    queryKey: ['matching', 'report', 'coverage', days],
    queryFn: () => fetchCoverageByStore(days),
    staleTime: 60_000,
  })

  return (
    <ReportSection
      title="Coverage by store — % матча по магазинам"
      helpTopic="matching.report_coverage"
      days={days}
      onDaysChange={setDays}
      isLoading={query.isFetching}
    >
      {query.data && query.data.stores.length > 0 && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase text-gray-500 border-b border-gray-800/40">
              <th className="text-left py-1.5 px-2">магазин</th>
              <th className="text-right py-1.5 px-2">total</th>
              <th className="text-right py-1.5 px-2">auto</th>
              <th className="text-right py-1.5 px-2">manual</th>
              <th className="text-right py-1.5 px-2">unmatched</th>
              <th className="text-right py-1.5 px-2">rejected</th>
              <th className="text-right py-1.5 px-2 font-semibold">coverage</th>
              <th className="text-left py-1.5 px-2 w-[180px]">распределение</th>
            </tr>
          </thead>
          <tbody>
            {query.data.stores.map(row => (
              <tr key={row.store_slug} className="border-b border-gray-900/40 hover:bg-gray-900/20">
                <td className="py-1.5 px-2 font-mono text-gray-200">{row.store_slug}</td>
                <td className="py-1.5 px-2 text-right font-mono text-gray-400">{row.total}</td>
                <td className="py-1.5 px-2 text-right font-mono text-emerald-400">{row.matched_auto}</td>
                <td className="py-1.5 px-2 text-right font-mono text-emerald-300">{row.matched_manual}</td>
                <td className="py-1.5 px-2 text-right font-mono text-amber-400">{row.unmatched}</td>
                <td className="py-1.5 px-2 text-right font-mono text-rose-400">{row.rejected}</td>
                <td
                  className={[
                    'py-1.5 px-2 text-right font-mono font-semibold',
                    row.coverage_pct >= 80 ? 'text-emerald-300' :
                    row.coverage_pct >= 50 ? 'text-amber-300' :
                    'text-rose-300',
                  ].join(' ')}
                >
                  {row.coverage_pct.toFixed(1)}%
                </td>
                <td className="py-1.5 px-2">
                  <CoverageBar row={row} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {query.data && query.data.stores.length === 0 && (
        <div className="text-xs text-gray-500 italic">
          Нет офферов за период {days}д.
        </div>
      )}
    </ReportSection>
  )
}

// ─── 3. Activity timeline ──────────────────────────────────────────────────

function ActivitySection() {
  const [days, setDays] = useState(14)
  const query = useQuery({
    queryKey: ['matching', 'report', 'activity', days],
    queryFn: () => fetchActivityTimeline(days),
    staleTime: 60_000,
  })

  return (
    <ReportSection
      title="Activity timeline — link/reject/revert/reassess по дням"
      helpTopic="matching.report_activity"
      days={days}
      onDaysChange={setDays}
      daysOptions={[7, 14, 30, 90]}
      isLoading={query.isFetching}
    >
      {query.data && query.data.rows.length === 0 && (
        <div className="text-xs text-gray-500 italic">
          Нет операторской активности за период {days}д.
        </div>
      )}
      {query.data && query.data.rows.length > 0 && (
        <ActivityHeatmap rows={query.data.rows} />
      )}
    </ReportSection>
  )
}

function ActivityHeatmap({ rows }: { rows: ActivityRow[] }) {
  // Группируем по action — каждая action-строка отдельным рядом ячеек.
  // Это компактнее, чем full chart, и не требует Recharts.
  const byAction: Record<string, Record<string, number>> = {}
  const days = new Set<string>()
  for (const r of rows) {
    days.add(r.day)
    if (!byAction[r.action]) byAction[r.action] = {}
    byAction[r.action][r.day] = (byAction[r.action][r.day] ?? 0) + r.count
  }
  const sortedDays = Array.from(days).sort()
  const sortedActions = Object.keys(byAction).sort()

  // Max count для нормализации opacity ячеек.
  const maxByAction: Record<string, number> = {}
  for (const action of sortedActions) {
    maxByAction[action] = Math.max(...Object.values(byAction[action]))
  }

  return (
    <div className="overflow-x-auto">
      <table className="text-[10px] border-separate border-spacing-0.5">
        <thead>
          <tr>
            <th className="text-left text-gray-500 font-normal pr-2 sticky left-0 bg-gray-900/40 z-10">
              action
            </th>
            {sortedDays.map(day => (
              <th
                key={day}
                className="text-gray-500 font-normal font-mono"
                style={{ writingMode: 'vertical-rl', textOrientation: 'mixed' }}
              >
                {day.slice(5)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedActions.map(action => {
            const max = maxByAction[action]
            return (
              <tr key={action}>
                <td className="text-gray-300 font-mono pr-2 whitespace-nowrap sticky left-0 bg-gray-900/40">
                  {action}
                </td>
                {sortedDays.map(day => {
                  const v = byAction[action][day] ?? 0
                  const opacity = v === 0 ? 0 : 0.2 + (0.8 * v) / max
                  return (
                    <td
                      key={day}
                      className="w-5 h-5 text-center"
                      style={{
                        backgroundColor: v > 0
                          ? `rgba(167, 139, 250, ${opacity})`
                          : 'rgba(255, 255, 255, 0.02)',
                        borderRadius: 2,
                      }}
                      title={`${action} · ${day}: ${v}`}
                    >
                      {v > 0 ? v : ''}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── 4. SLA per tier ───────────────────────────────────────────────────────

const TIER_KEYS = ['t0', 't1', 't2', 't3', 'manual', 'unmatched', 'pending', 'rejected'] as const

const TIER_LABELS: Record<typeof TIER_KEYS[number], string> = {
  t0: 'T0 — cache hit',
  t1: 'T1 — pg_trgm',
  t2: 'T2 — embedding',
  t3: 'T3 — LLM',
  manual: 'manual',
  unmatched: 'unmatched',
  pending: 'pending_ml',
  rejected: 'rejected',
}

function SlaSection() {
  const [days, setDays] = useState(7)
  const query = useQuery({
    queryKey: ['matching', 'report', 'sla', days],
    queryFn: () => fetchSlaStats(days),
    staleTime: 60_000,
  })

  return (
    <ReportSection
      title="SLA per tier — распределение по tier'ам + latency T2/T3"
      helpTopic="matching.report_sla"
      days={days}
      onDaysChange={setDays}
      isLoading={query.isFetching}
    >
      {query.data && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Tier share */}
          <div>
            <div className="text-[11px] text-gray-500 mb-2">распределение офферов</div>
            <table className="w-full text-xs">
              <tbody>
                {TIER_KEYS.map(key => {
                  const share = query.data!.tier_share[key]
                  if (!share || share.count === 0) return null
                  return (
                    <tr key={key} className="border-b border-gray-900/40">
                      <td className="py-1 px-2 text-gray-300 text-[11px]">{TIER_LABELS[key]}</td>
                      <td className="py-1 px-2 text-right font-mono text-gray-400">{share.count}</td>
                      <td className="py-1 px-2 w-[80px]">
                        <div className="flex h-1.5 rounded overflow-hidden">
                          <div
                            className="bg-violet-500"
                            style={{ width: `${share.share_pct}%` }}
                          />
                        </div>
                      </td>
                      <td className="py-1 px-2 text-right font-mono text-violet-300 w-[60px]">
                        {share.share_pct.toFixed(1)}%
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Latency T2/T3 */}
          <div>
            <div className="text-[11px] text-gray-500 mb-2">latency воркера (мс)</div>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] uppercase text-gray-500 border-b border-gray-800/40">
                  <th className="text-left py-1 px-2">tier</th>
                  <th className="text-right py-1 px-2">p50</th>
                  <th className="text-right py-1 px-2">p95</th>
                  <th className="text-right py-1 px-2">p99</th>
                </tr>
              </thead>
              <tbody>
                {(['t2', 't3'] as const).map(tier => {
                  const l = query.data!.latency[tier]
                  return (
                    <tr key={tier} className="border-b border-gray-900/40">
                      <td className="py-1 px-2 text-gray-300">{TIER_LABELS[tier]}</td>
                      <td className="py-1 px-2 text-right font-mono text-gray-300">
                        {l?.p50_ms != null ? l.p50_ms.toFixed(0) : '—'}
                      </td>
                      <td className="py-1 px-2 text-right font-mono text-amber-300">
                        {l?.p95_ms != null ? l.p95_ms.toFixed(0) : '—'}
                      </td>
                      <td className="py-1 px-2 text-right font-mono text-rose-300">
                        {l?.p99_ms != null ? l.p99_ms.toFixed(0) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="mt-2 text-[10px] text-gray-500 leading-relaxed">
              Считается из match_queue (created_at → processed_at для status='done').
              «—» означает, что за период не было completed-записей нужного tier'а.
            </p>
          </div>
        </div>
      )}
    </ReportSection>
  )
}

// ─── Composition ───────────────────────────────────────────────────────────

export function ReportTab() {
  return (
    <div className="space-y-4">
      <div className="bg-gray-900/30 rounded border border-gray-800/40 p-3 text-[11px] text-gray-400 leading-relaxed">
        Отчёт по матчингу — operational visibility для оператора. Все секции
        обновляются по клику на «период», ничего не пишется в БД.
        Подробное руководство — в табе <strong className="text-violet-300">Help</strong>
        {' '}(нажми <kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[10px]">6</kbd>)
        раздел «Чтение отчёта».
      </div>

      <TopUnmatchedSection />
      <CoverageSection />
      <ActivitySection />
      <SlaSection />
    </div>
  )
}
