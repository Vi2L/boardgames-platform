/**
 * MatchingPage — admin-панель управления ML-матчингом offers → games.
 *
 * Эволюция дизайна (handoff §A–§F):
 *   - **§A Header** — 6-section dense strip (title+kill | models with metrics
 *     | queue stats c delta | queue depth sparkline | worker tick countdown
 *     | + active jobs strip снизу).
 *   - **§B Tab strip** — live counters в табах, alert-dots, keyboard 1-5.
 *   - **§F Keyboard cheatsheet** — overlay по `?`.
 *
 * Style: gray-900 / violet-700 (как в текущей реализации), не zinc/indigo —
 * редизайн на новые design tokens — отдельный track (см. CLAUDE.md handoff'а).
 *
 * 5 вкладок:
 *   1. Контроль — kill-switch, ML-модели, worker, warmup, force-probe.
 *   2. Очередь — re-enqueue skipped + depth chart + auto-recovery rules.
 *   3. Журнал — переиспользует MatchLogTab.
 *   4. Штучный — прогон одного offer + queue position + live stages.
 *   5. Help — документация.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Cpu, ListChecks, ScrollText, Crosshair, HelpCircle, Keyboard, AlertTriangle,
  BarChart3,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'

import { fetchMlStatus } from '../lib/catalog'
import {
  fetchMatchingStatsExtended, fetchQueueDepthHistory,
  fetchWorkerJob, type MlStatusWithMetrics, type SchedulerJobInfoWithHistory,
} from '../lib/matching'
import { useMatchingMetrics, selectDrainageRate } from '../store/matching-metrics'

import { ControlTab } from '../components/matching/ControlTab'
import { QueuePanel } from '../components/matching/QueuePanel'
import { SingleMatchTab } from '../components/matching/SingleMatchTab'
import { MatchingHelpTab } from '../components/matching/MatchingHelpTab'
import { ReportTab } from '../components/matching/ReportTab'
import { MatchLogTab } from '../components/catalog/MatchLogTab'
import { CircuitStateBadge, type CircuitState } from '../components/matching/CircuitStateBadge'
import { MetricSpark } from '../components/matching/MetricSpark'
import { ActiveJobsStrip } from '../components/matching/ActiveJobsStrip'
import {
  KeyboardCheatsheet, MATCHING_SHORTCUT_GROUPS,
} from '../components/matching/KeyboardCheatsheet'

type Tab = 'control' | 'queue' | 'log' | 'single' | 'report' | 'help'

const TABS: Array<{ id: Tab; label: string; icon: LucideIcon; shortcut: string; hint: string }> = [
  { id: 'control', label: 'Контроль', icon: Cpu,        shortcut: '1', hint: 'Kill-switch, модели, воркер, warmup' },
  { id: 'queue',   label: 'Очередь',  icon: ListChecks, shortcut: '2', hint: 'match_queue: re-enqueue + breakdown' },
  { id: 'log',     label: 'Журнал',   icon: ScrollText, shortcut: '3', hint: 'match_log: история + revert' },
  { id: 'single',  label: 'Штучный',  icon: Crosshair,  shortcut: '4', hint: 'Прогон одного offer через v2' },
  { id: 'report',  label: 'Отчёт',    icon: BarChart3,  shortcut: '5', hint: 'Top unmatched, coverage, activity, SLA (CAT-17)' },
  { id: 'help',    label: 'Help',     icon: HelpCircle, shortcut: '6', hint: 'Документация + глоссарий' },
]

const TAB_SHORTCUTS: Record<string, Tab> = {
  '1': 'control', '2': 'queue', '3': 'log', '4': 'single', '5': 'report', '6': 'help',
}

export function MatchingPage() {
  const [tab, setTab] = useState<Tab>('control')
  const [cheatsheetOpen, setCheatsheetOpen] = useState(false)

  // Keyboard: 1-5 → tabs, ? → cheatsheet. Skipping когда фокус в input.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
      if (target?.isContentEditable) return

      if (e.key === '?' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        setCheatsheetOpen(true)
        return
      }
      const t = TAB_SHORTCUTS[e.key]
      if (t) {
        e.preventDefault()
        setTab(t)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="space-y-4">
      <PageHeader onCheatsheet={() => setCheatsheetOpen(true)} />

      <ActiveJobsStrip className="-mx-4 md:-mx-6 -mt-2" />

      <TabStrip active={tab} onSelect={setTab} />

      <div>
        {tab === 'control' && <ControlTab />}
        {tab === 'queue'   && <QueuePanel />}
        {tab === 'log'     && <MatchLogTab />}
        {tab === 'single'  && <SingleMatchTab />}
        {tab === 'report'  && <ReportTab />}
        {tab === 'help'    && <MatchingHelpTab />}
      </div>

      <KeyboardCheatsheet
        open={cheatsheetOpen}
        onClose={() => setCheatsheetOpen(false)}
        groups={MATCHING_SHORTCUT_GROUPS}
      />
    </div>
  )
}

// ── §B Tab strip — live counters + alert dots + KBD shortcuts ──────────────

function TabStrip({ active, onSelect }: { active: Tab; onSelect: (t: Tab) => void }) {
  const stats = useQuery({
    queryKey: ['matching', 'stats-extended'],
    queryFn: fetchMatchingStatsExtended,
    refetchInterval: 5000,
  })
  const mlStatus = useQuery({
    queryKey: ['catalog', 'ml-status'],
    queryFn: fetchMlStatus,
    refetchInterval: 5000,
  })

  const queueCounts = stats.data?.queue
  const mlData = mlStatus.data as MlStatusWithMetrics | undefined

  // Alert на Контроле: CB любой модели в open или half_open.
  const controlAlert = useMemo(() => {
    if (!mlData?.circuit_state) return null
    for (const state of Object.values(mlData.circuit_state)) {
      if (state === 'open') return 'critical' as const
      if (state === 'half_open') return 'warn' as const
    }
    return null
  }, [mlData])

  // Pending counter цвет: warn если > 100, critical > 500.
  const queueLevel: 'ok' | 'warn' | 'critical' = useMemo(() => {
    const p = queueCounts?.pending ?? 0
    if (p > 500) return 'critical'
    if (p > 100) return 'warn'
    return 'ok'
  }, [queueCounts])

  return (
    <nav
      className={clsx(
        'flex items-stretch border-b border-gray-800/80 -mx-4 md:-mx-6 px-4 md:px-6',
        'bg-gradient-to-b from-gray-900/40 to-transparent',
      )}
    >
      {TABS.map(t => {
        const Icon = t.icon
        const isActive = active === t.id

        // Counter & alert per-tab
        let counter: number | null = null
        let counterTone: 'ok' | 'warn' | 'critical' = 'ok'
        let alertDot: 'warn' | 'critical' | null = null

        if (t.id === 'queue') {
          counter = queueCounts?.pending ?? null
          counterTone = queueLevel
        } else if (t.id === 'log') {
          // Журнал 24h count — лежит в MatchLogTab' query, для tab-badge
          // делаем дешёвую отдельную query (или потом перенесём в общий store).
          // Пока показываем total operations = done из stats (упрощение).
          counter = queueCounts?.done ?? null
        } else if (t.id === 'control') {
          alertDot = controlAlert
        }

        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(t.id)}
            title={t.hint}
            className={clsx(
              'group relative inline-flex items-center gap-2 px-4 py-2.5 transition-all',
              'text-[11px] uppercase tracking-wider font-medium',
              'border-b-2 -mb-px',
              isActive
                ? 'border-violet-500 text-violet-200 bg-violet-950/20'
                : 'border-transparent text-gray-500 hover:text-gray-200 hover:bg-gray-900/40',
            )}
          >
            <Icon size={12} className={isActive ? 'text-violet-300' : ''} />
            {t.label}

            {/* Counter в табе */}
            {counter !== null && counter > 0 && (
              <span
                className={clsx(
                  'inline-flex items-center px-1 h-4 rounded text-[10px] font-mono tabular-nums',
                  counterTone === 'critical' && 'bg-rose-500/20 text-rose-300',
                  counterTone === 'warn' && 'bg-amber-500/20 text-amber-300',
                  counterTone === 'ok' && (isActive ? 'bg-violet-500/15 text-violet-300' : 'bg-gray-800 text-gray-400'),
                )}
              >
                {counter > 999 ? `${(counter / 1000).toFixed(1)}k` : counter}
              </span>
            )}

            {/* Alert dot */}
            {alertDot && (
              <span
                className={clsx(
                  'w-1.5 h-1.5 rounded-full',
                  alertDot === 'critical' ? 'bg-rose-500' : 'bg-amber-400 animate-pulse',
                )}
                aria-label={`alert: ${alertDot}`}
              />
            )}

            {/* KBD legend — справа от лейбла */}
            <kbd className={clsx(
              'ml-1 inline-flex items-center justify-center min-w-[14px] h-3.5 px-1',
              'border rounded font-mono text-[9px]',
              isActive
                ? 'border-violet-700/50 text-violet-300/70'
                : 'border-gray-800 text-gray-600',
            )}>
              {t.shortcut}
            </kbd>
          </button>
        )
      })}
    </nav>
  )
}

// ── §A PageHeader — 6-section dense strip + active jobs ────────────────────

interface PageHeaderProps {
  onCheatsheet: () => void
}

function PageHeader({ onCheatsheet }: PageHeaderProps) {
  // Главные источники данных
  const mlStatus = useQuery({
    queryKey: ['catalog', 'ml-status'],
    queryFn: fetchMlStatus,
    refetchInterval: 5000,
  })
  const statsQ = useQuery({
    queryKey: ['matching', 'stats-extended'],
    queryFn: fetchMatchingStatsExtended,
    refetchInterval: 5000,
  })
  const workerQ = useQuery({
    queryKey: ['matching', 'worker-job'],
    queryFn: () => fetchWorkerJob('match_worker'),
    refetchInterval: 5000,
  })
  const depthQ = useQuery({
    queryKey: ['matching', 'queue-depth-24h'],
    queryFn: () => fetchQueueDepthHistory({ range_hours: 24, bucket_minutes: 60 }),
    refetchInterval: 60_000, // depth обновляем реже — 1 раз в минуту
    retry: false, // backend может вернуть 5xx — деградируем graceful
  })

  // Push snapshot в client-side ring-buffer для drainage rate.
  // useRef чтобы избежать infinite update'ов при изменении объекта query data.
  const pushSnapshot = useMatchingMetrics(s => s.pushSnapshot)
  const lastPushedTs = useRef<number>(0)
  useEffect(() => {
    if (!statsQ.data?.queue) return
    const now = Date.now()
    if (now - lastPushedTs.current < 4500) return  // debounce 4.5s — close to poll interval
    lastPushedTs.current = now
    const md = mlStatus.data as MlStatusWithMetrics | undefined
    pushSnapshot({
      ts: now,
      pending: statsQ.data.queue.pending,
      processing: statsQ.data.queue.processing,
      skipped: statsQ.data.queue.skipped,
      failed: statsQ.data.queue.failed,
      done: statsQ.data.queue.done,
      models: md?.metrics
        ? Object.fromEntries(
            Object.entries(md.metrics).map(([k, m]) => [k, {
              available: md.models[k] ?? false,
              p50_ms: m.p50_ms,
              p95_ms: m.p95_ms,
              rps_1m: m.rps_1m,
              failures: md.failures[k] ?? 0,
            }]),
          )
        : {},
    })
  }, [statsQ.data, mlStatus.data, pushSnapshot])

  const snapshots = useMatchingMetrics(s => s.snapshots)

  const mlData = mlStatus.data as MlStatusWithMetrics | undefined
  const models = mlData?.models ?? {}
  const cb = mlData?.circuit_state ?? {}
  const metrics = mlData?.metrics ?? {}
  const failures = mlData?.failures ?? {}

  const queue = statsQ.data?.queue
  const depth = depthQ.data

  return (
    <header className={clsx(
      'rounded-lg border border-gray-800/80 bg-black/40 overflow-hidden',
      'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]',
    )}>
      <div className="flex items-stretch divide-x divide-gray-800/60">

        {/* §A.1 · Title block */}
        <div className="px-4 py-3 min-w-0 w-[280px] shrink-0">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[10px] uppercase tracking-widest text-violet-400/80">
              [ ML ]
            </span>
            <h1 className="text-sm font-semibold text-gray-100 tracking-wide truncate">
              Матчинг — ML pipeline
            </h1>
          </div>
          <p className="text-[10px] text-gray-500 mt-0.5 truncate">
            T0→T3 · kill-switch · queue · log · revert
          </p>
          <button
            type="button"
            onClick={onCheatsheet}
            className="mt-1.5 inline-flex items-center gap-1 text-[10px] font-mono text-gray-500 hover:text-violet-300"
          >
            <Keyboard size={10} />
            shortcuts · <kbd className="px-1 border border-gray-700 rounded text-[9px]">?</kbd>
          </button>
        </div>

        {/* §A.2 · Models — per-model row с CB state + p50/p95/rps */}
        <div className="px-4 py-3 flex-1 min-w-[280px]">
          <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono mb-1">
            ollama models
          </div>
          {Object.keys(models).length === 0 ? (
            <span className="text-[10px] text-gray-600 font-mono italic">no data</span>
          ) : (
            <div className="space-y-1">
              {Object.entries(models).map(([name, available]) => {
                const state = (cb[name] ?? (available ? 'closed' : 'open')) as CircuitState
                const m = metrics[name]
                const f = failures[name] ?? 0
                const shortName = name.replace(':latest', '').replace(':7b-instruct', '')
                return (
                  <div key={name} className="flex items-center gap-2 text-[11px]">
                    <CircuitStateBadge state={state} compact />
                    <span className="font-mono text-gray-300 w-[60px] truncate" title={name}>
                      {shortName}
                    </span>
                    {m && m.p50_ms !== null && (
                      <span className="font-mono text-gray-500 tabular-nums">
                        p50 <span className="text-gray-300">{Math.round(m.p50_ms)}</span>ms
                      </span>
                    )}
                    {m && m.p95_ms !== null && (
                      <span className="font-mono text-gray-500 tabular-nums">
                        p95 <span className="text-gray-300">{Math.round(m.p95_ms)}</span>ms
                      </span>
                    )}
                    {m && m.rps_1m > 0 && (
                      <span className="font-mono text-gray-500 tabular-nums">
                        rps <span className="text-gray-300">{m.rps_1m.toFixed(1)}</span>
                      </span>
                    )}
                    {f > 0 && (
                      <span className="font-mono text-rose-300 tabular-nums">
                        fail <span>{f}</span>
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* §A.3 · Queue stats grid с delta-метками */}
        <div className="px-4 py-3 w-[260px] shrink-0">
          <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono mb-1">
            queue
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            <QueueStat label="pending" value={queue?.pending} accent="amber"
                       delta={computeDelta(snapshots, 'pending')} />
            <QueueStat label="proc." value={queue?.processing} accent="violet" />
            <QueueStat label="skipped" value={queue?.skipped} accent="gray"
                       delta={computeDelta(snapshots, 'skipped')} />
            <QueueStat label="failed" value={queue?.failed} accent="rose" />
          </div>
        </div>

        {/* §A.4 · Depth chart 24h + drainage rate */}
        <div className="px-4 py-3 w-[260px] shrink-0">
          <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono mb-1">
            depth · 24h
          </div>
          {depth && depth.points.length > 0 ? (
            <>
              <MetricSpark
                values={depth.points.map(p => p.depth)}
                tone={depth.current > 100 ? 'warn' : 'info'}
                width={180}
                height={28}
              />
              <div className="flex items-center gap-2 text-[10px] font-mono mt-0.5">
                <span className="text-gray-500">peak <span className="text-gray-300 tabular-nums">{depth.peak}</span></span>
                <span className="text-gray-500">now <span className="text-gray-300 tabular-nums">{depth.current}</span></span>
                {depth.drainage_rate_per_min !== 0 && (
                  <span className={clsx(
                    'font-mono tabular-nums',
                    depth.drainage_rate_per_min > 0 ? 'text-emerald-400' : 'text-rose-400',
                  )}>
                    {depth.drainage_rate_per_min > 0 ? '↓' : '↑'} {Math.abs(depth.drainage_rate_per_min).toFixed(1)}/мин
                  </span>
                )}
              </div>
            </>
          ) : (
            <FallbackDepth snapshots={snapshots} />
          )}
        </div>

        {/* §A.5 · Worker tick countdown */}
        <div className="px-4 py-3 w-[180px] shrink-0">
          <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono mb-1">
            worker tick
          </div>
          <WorkerCountdown job={workerQ.data as SchedulerJobInfoWithHistory | undefined} />
        </div>
      </div>
    </header>
  )
}

function computeDelta(
  snapshots: ReturnType<typeof useMatchingMetrics.getState>['snapshots'],
  field: 'pending' | 'skipped',
): number | null {
  if (snapshots.length < 2) return null
  // Δ за последние ~5 минут (60 snapshots × 5s = 5 min). Берём первый и последний.
  const tail = snapshots.slice(-60)
  if (tail.length < 2) return null
  return tail[tail.length - 1][field] - tail[0][field]
}

function QueueStat({
  label, value, accent, delta,
}: {
  label: string
  value: number | undefined
  accent: 'amber' | 'violet' | 'gray' | 'rose'
  delta?: number | null
}) {
  const accentCls = {
    amber: 'text-amber-300',
    violet: 'text-violet-300',
    gray: 'text-gray-400',
    rose: 'text-rose-300',
  }[accent]

  return (
    <div className="flex items-baseline gap-1.5 min-w-0">
      <span className={clsx('text-base font-mono tabular-nums leading-none', accentCls)}>
        {value ?? '—'}
      </span>
      <span className="text-[9px] uppercase tracking-wider text-gray-600 truncate">
        {label}
      </span>
      {delta != null && delta !== 0 && (
        <span className={clsx(
          'text-[9px] font-mono tabular-nums',
          delta < 0 ? 'text-emerald-400' : 'text-rose-400',
        )}>
          {delta < 0 ? '−' : '+'}{Math.abs(delta)}
        </span>
      )}
    </div>
  )
}

function FallbackDepth({ snapshots }: { snapshots: ReturnType<typeof useMatchingMetrics.getState>['snapshots'] }) {
  if (snapshots.length === 0) {
    return <span className="text-[10px] text-gray-600 font-mono italic">собираем данные…</span>
  }
  const values = snapshots.map(s => s.pending + s.processing)
  const drainage = selectDrainageRate(snapshots)
  return (
    <>
      <MetricSpark values={values} width={180} height={28} tone="info" />
      <div className="text-[10px] font-mono text-gray-500 mt-0.5">
        client-buffer · {snapshots.length} точек
        {drainage !== 0 && (
          <span className={clsx(
            'ml-2',
            drainage > 0 ? 'text-emerald-400' : 'text-rose-400',
          )}>
            {drainage > 0 ? '↓' : '↑'}{Math.abs(drainage).toFixed(1)}/мин
          </span>
        )}
      </div>
    </>
  )
}

// ── Worker tick countdown — клиентский 250ms tick ──────────────────────────

function useTickCountdown(nextRunAt: string | null | undefined, intervalSec: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!nextRunAt) return
    const id = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(id)
  }, [nextRunAt])
  if (!nextRunAt) return { secondsLeft: 0, progress: 0 }
  const target = new Date(nextRunAt).getTime()
  const secondsLeft = Math.max(0, (target - now) / 1000)
  const progress = intervalSec > 0
    ? Math.min(1, 1 - secondsLeft / intervalSec)
    : 0
  return { secondsLeft: Math.ceil(secondsLeft), progress }
}

function WorkerCountdown({ job }: { job: SchedulerJobInfoWithHistory | undefined }) {
  const intervalSec = (job?.params?.interval_sec as number) ?? 10
  const nextRunAt = job?.next_run_at ?? null
  const { secondsLeft, progress } = useTickCountdown(nextRunAt, intervalSec)

  // Last tick duration sparkline из tick_history
  const tickHistory = job?.tick_history ?? []
  const lastDuration = tickHistory.length > 0
    ? tickHistory[tickHistory.length - 1].duration_ms
    : null

  if (!job) {
    return <span className="text-[10px] text-gray-600 font-mono italic">no data</span>
  }

  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-1">
        <span className="text-base font-mono tabular-nums text-violet-300 leading-none">
          {secondsLeft}
        </span>
        <span className="text-[9px] uppercase tracking-wider text-gray-600">
          sec до next
        </span>
      </div>
      {/* Progress bar 0→100% между тиками */}
      <div className="h-1 bg-gray-800/60 rounded-full overflow-hidden">
        <div
          className="h-full bg-violet-500/80 transition-[width] duration-150"
          style={{ width: `${progress * 100}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-[10px] font-mono">
        <span className="text-gray-500">
          interval <span className="text-gray-300">{intervalSec}s</span>
        </span>
        {lastDuration !== null && (
          <span className="text-gray-500">
            last <span className="text-gray-300 tabular-nums">{(lastDuration / 1000).toFixed(1)}s</span>
          </span>
        )}
      </div>
    </div>
  )
}

void AlertTriangle  // satisfy unused-import
