/**
 * ControlTab — главная вкладка `/matching → Контроль`.
 *
 * Содержит 4 секции с админскими действиями:
 *   1. KillSwitch — глобальный toggle `ml_enabled` (runtime_flags).
 *   2. ML-модели — bge-m3 + qwen2.5 с circuit_state + last_check + failures.
 *   3. Worker — JobCard для match_worker с trigger + interval-toggle.
 *   4. Warmup — кнопка прогрева эмбеддингов (фоновый ImportJob).
 *
 * Polling 5 сек: kill-switch + ml-status + worker job (мало данных, дёшево).
 *
 * Style direction: «operator console» — каждая карточка имеет верхний edge-light
 * через inset-shadow, монохромный header с uppercase tracking-wider, метрики
 * font-mono. Цветные акценты только для health states (green/amber/red).
 */
import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Power, PlayCircle, Loader2, Zap, Flame, Settings2,
  CheckCircle2, XCircle, AlertTriangle,
} from 'lucide-react'
import clsx from 'clsx'

import { fetchMlStatus, startWarmupEmbeddings } from '../../lib/catalog'
import {
  fetchRuntimeFlag, setRuntimeFlag,
  fetchWorkerJob, updateWorkerInterval, triggerMatchWorker,
  forceProbeModel,
  type SchedulerJobInfoWithHistory, type MlStatusWithMetrics,
} from '../../lib/matching'
import { useMatchingMetrics, selectLatencySeries } from '../../store/matching-metrics'
import { CircuitStateBadge, type CircuitState } from './CircuitStateBadge'
import { HowItWorks, TierChip } from './HowItWorks'
import { InfoTip } from './InfoTip'
import { HelpBox } from '../shared/HelpBox'
import type { TopicId } from '../../lib/help-topics'
import { MetricSpark } from './MetricSpark'
import { ConfirmPanel } from '../shared/ConfirmPanel'

// ── Small format helpers ───────────────────────────────────────────────────

function relativeTime(iso: string | null): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) {
    const fut = -ms
    if (fut < 60_000) return `через ${Math.round(fut / 1000)}с`
    if (fut < 3600_000) return `через ${Math.round(fut / 60_000)}м`
    return `через ${Math.round(fut / 3600_000)}ч`
  }
  if (ms < 5_000) return 'только что'
  if (ms < 60_000) return `${Math.round(ms / 1000)}с назад`
  if (ms < 3600_000) return `${Math.round(ms / 60_000)}м назад`
  if (ms < 86_400_000) return `${Math.round(ms / 3600_000)}ч назад`
  return `${Math.round(ms / 86_400_000)}д назад`
}

// ── Main component ─────────────────────────────────────────────────────────

export function ControlTab() {
  return (
    <div className="space-y-4">
      <HowItWorks title="Как работает ML pipeline" defaultOpen={false}>
        <PipelineExplainer />
      </HowItWorks>

      <KillSwitchCard />
      <ModelsCard />
      <WorkerCard />
      <WarmupCard />
    </div>
  )
}

// ── Pipeline explainer ─────────────────────────────────────────────────────

function PipelineExplainer() {
  return (
    <>
      <p>
        Каждый поступивший offer (от парсеров через <code className="text-indigo-300">/ingest/offers</code>)
        проходит цепочку tier'ов. Первый, который даёт уверенный матч, выигрывает —
        дальше не идём.
      </p>
      <div className="flex flex-wrap items-center gap-2 my-2">
        <span className="inline-flex items-center gap-1">
          <TierChip tier="T0" label="cache" />
          <HelpBox topic="matching.tier_t0" />
        </span>
        <span className="text-gray-600">→</span>
        <span className="inline-flex items-center gap-1">
          <TierChip tier="T1" label="pg_trgm ≥ 0.92" />
          <HelpBox topic="matching.tier_t1" />
        </span>
        <span className="text-gray-600">→</span>
        <span className="inline-flex items-center gap-1">
          <TierChip tier="T2" label="cosine ≥ 0.85" />
          <HelpBox topic="matching.tier_t2" />
        </span>
        <span className="text-gray-600">→</span>
        <span className="inline-flex items-center gap-1">
          <TierChip tier="T3" label="LLM ≥ 0.75 conf" />
          <HelpBox topic="matching.tier_t3" />
        </span>
        <span className="text-gray-600">→</span>
        <TierChip tier="T4" label="manual" />
      </div>
      <p>
        <span className="text-gray-400">T0+T1</span> работают <span className="text-green-300">синхронно</span>
        прямо в ingest-запросе. <span className="text-gray-400">T2+T3</span> — <span className="text-amber-300">асинхронно</span>
        : оффер кладётся в очередь <code className="text-indigo-300">match_queue</code>, воркер берёт батч и обрабатывает.
      </p>
      <p>
        <span className="text-red-300">Kill-switch</span> ниже отключает <strong>только T2+T3</strong> — T0/T1
        работают всегда (это синхронный код в ingest-роутере без Ollama).
      </p>
    </>
  )
}

// ── KillSwitch card ────────────────────────────────────────────────────────

function KillSwitchCard() {
  const qc = useQueryClient()
  const flagQuery = useQuery({
    queryKey: ['matching', 'runtime-flag', 'ml_enabled'],
    queryFn: () => fetchRuntimeFlag('ml_enabled'),
    refetchInterval: 5000,
  })

  const setFlag = useMutation({
    mutationFn: (value: boolean) => setRuntimeFlag('ml_enabled', value),
    onSuccess: (data) => {
      toast.success(
        data.value_bool ? 'ML включён — воркер возобновит работу' : 'ML выключен — воркер пропустит следующие тики',
      )
      qc.invalidateQueries({ queryKey: ['matching', 'runtime-flag', 'ml_enabled'] })
      qc.invalidateQueries({ queryKey: ['catalog', 'ml-status'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const enabled = flagQuery.data?.value_bool ?? null
  const [confirmOff, setConfirmOff] = useState(false)

  const queueQ = useQuery({
    queryKey: ['matching', 'stats-extended'],
    queryFn: async () => (await import('../../lib/matching')).fetchMatchingStatsExtended(),
    refetchInterval: 5000,
  })

  const handleToggle = () => {
    if (enabled === null) return
    if (enabled) {
      // §G inline confirm вместо window.confirm — показываем impact preview.
      setConfirmOff(true)
    } else {
      // Включение — без confirm (positive action).
      setFlag.mutate(true)
    }
  }

  const handleConfirmOff = () => {
    setFlag.mutate(false)
    setConfirmOff(false)
  }

  return (
    <Card
      title="ML pipeline"
      tooltip="Глобальный kill-switch. Хранится в таблице runtime_flags (миграция 0013). После PATCH значение пропагируется в инстансы catalog'а через TTL-кэш (≤5с)."
      helpTopic="matching.kill_switch"
      right={
        <span className={clsx(
          'font-mono text-[10px] uppercase tracking-wider',
          enabled === true && 'text-green-300',
          enabled === false && 'text-red-300',
          enabled === null && 'text-gray-500',
        )}>
          {enabled === true && '● ENABLED'}
          {enabled === false && '○ DISABLED'}
          {enabled === null && '… loading'}
        </span>
      }
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-6">
          <div className="space-y-1">
            <div className="text-sm text-gray-200">
              {enabled === true && 'Воркер работает, ingest пушит в match_queue при miss T0+T1.'}
              {enabled === false && 'Воркер пропускает циклы. Все unmatched идут в manual T4.'}
              {enabled === null && 'Загружаю состояние флага…'}
            </div>
            <div className="text-[11px] text-gray-500 font-mono">
              updated_by={flagQuery.data?.updated_by ?? '—'} · {relativeTime(flagQuery.data?.updated_at ?? null)}
            </div>
          </div>
          <ToggleSwitch
            checked={enabled === true}
            onChange={handleToggle}
            loading={setFlag.isPending || flagQuery.isLoading}
          />
        </div>

        <ConfirmPanel
          open={confirmOff}
          variant="red"
          title="Выключить ML-pipeline?"
          description="T2 (vector) и T3 (LLM) перестанут запускаться. T0 cache и T1 trgm продолжат работать."
          impact={[
            `${queueQ.data?.queue?.pending ?? '—'} pending → останутся ждать (воркер пропустит циклы)`,
            `${queueQ.data?.queue?.processing ?? '—'} processing → завершат batch, потом стоп`,
            'Новые offers с miss T0+T1 → status="unmatched", reason="ml_disabled"',
            'Active background-jobs (warmup, reassess) НЕ остановятся',
          ]}
          confirmLabel="Выключить ML"
          loading={setFlag.isPending}
          onConfirm={handleConfirmOff}
          onCancel={() => setConfirmOff(false)}
        />
      </div>
    </Card>
  )
}

// Большой физический-feel toggle. Стандартный paddingless track + thumb со shadow.
function ToggleSwitch({
  checked, onChange, loading,
}: { checked: boolean; onChange: () => void; loading: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onChange}
      disabled={loading}
      className={clsx(
        'relative inline-flex w-20 h-10 rounded-full transition-colors duration-300',
        'shadow-[inset_0_1px_2px_rgba(0,0,0,0.6)]',
        'border',
        checked
          ? 'bg-green-700/40 border-green-600/50'
          : 'bg-gray-800 border-gray-700',
        loading && 'opacity-60 cursor-wait',
      )}
    >
      <span
        className={clsx(
          'absolute top-1 w-8 h-8 rounded-full transition-all duration-300',
          'shadow-lg shadow-black/40 flex items-center justify-center',
          checked
            ? 'left-11 bg-green-400 text-green-900'
            : 'left-1 bg-gray-600 text-gray-900',
        )}
      >
        {loading
          ? <Loader2 size={14} className="animate-spin" />
          : checked ? <CheckCircle2 size={14} /> : <Power size={14} />}
      </span>
    </button>
  )
}

// ── Models card — с rps/p50/p95/fail + sparkline + force-probe ─────────────

function ModelsCard() {
  const qc = useQueryClient()
  const mlStatus = useQuery({
    queryKey: ['catalog', 'ml-status'],
    queryFn: fetchMlStatus,
    refetchInterval: 5000,
  })

  const probe = useMutation({
    mutationFn: (name: string) => forceProbeModel(name),
    onSuccess: (data) => {
      toast.success(`probe ${data.model}: ${data.circuit_state}`)
      qc.invalidateQueries({ queryKey: ['catalog', 'ml-status'] })
    },
    onError: (e: Error) => toast.error(`probe failed: ${e.message}`),
  })

  const data = mlStatus.data as MlStatusWithMetrics | undefined
  const models = data?.models ?? {}
  const circuitState = data?.circuit_state ?? {}
  const failures = data?.failures ?? {}
  const metrics = data?.metrics ?? {}

  const lastCheckRel = relativeTime(data?.last_check_at ?? null)
  const lastSuccessRel = relativeTime(data?.last_success_at ?? null)

  const snapshots = useMatchingMetrics(s => s.snapshots)

  return (
    <Card
      title="ML-модели · Ollama"
      tooltip="OllamaHealth polling раз в 30 сек через scheduler-job ml_health_check. Circuit Breaker: closed → open после 3 подряд провалов; open → half-open через recovery_timeout (60с). p50/p95/rps — rolling-buffer последних ~60 успешных вызовов."
      helpTopic="matching.circuit_breaker"
      right={
        <div className="flex items-center gap-3 text-[10px] uppercase tracking-wider text-gray-500 font-mono">
          <span>last_check {lastCheckRel}</span>
          <span className="opacity-50">·</span>
          <span>last_success {lastSuccessRel}</span>
        </div>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Object.entries(models).length === 0 && (
          <div className="col-span-2 text-xs text-gray-500 py-4 text-center">
            нет данных от OllamaHealth — scheduler не запускался?
          </div>
        )}
        {Object.entries(models).map(([name, available]) => {
          const cb = (circuitState[name] ?? (available ? 'closed' : 'open')) as CircuitState
          const fails = failures[name] ?? 0
          const m = metrics[name]
          const latencySeries = selectLatencySeries(snapshots, name)
          const canProbe = cb === 'open' || cb === 'half_open'

          return (
            <div
              key={name}
              className={clsx(
                'rounded-md border p-3 space-y-2',
                'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
                cb === 'closed' && 'bg-green-950/10 border-green-900/30',
                cb === 'half_open' && 'bg-amber-950/15 border-amber-900/40',
                cb === 'open' && 'bg-red-950/20 border-red-900/40',
                cb === 'unknown' && 'bg-gray-900/40 border-gray-800',
              )}
            >
              <div className="flex items-baseline justify-between gap-2">
                <code className="text-sm text-gray-100 font-mono truncate">{name}</code>
                <CircuitStateBadge state={cb} />
              </div>

              {/* Расширенные метрики rps / p50 / p95 / fail */}
              <dl className="grid grid-cols-4 gap-2 text-[11px]">
                <Metric
                  label="rps"
                  value={m && m.rps_1m > 0 ? m.rps_1m.toFixed(1) : '—'}
                  accent="neutral"
                />
                <Metric
                  label="p50"
                  value={m?.p50_ms != null ? `${Math.round(m.p50_ms)}ms` : '—'}
                  accent="neutral"
                />
                <Metric
                  label="p95"
                  value={m?.p95_ms != null ? `${Math.round(m.p95_ms)}ms` : '—'}
                  accent={m?.p95_ms != null && m.p95_ms > 1000 ? 'amber' : 'neutral'}
                />
                <Metric
                  label="fail"
                  value={String(fails)}
                  accent={fails > 0 ? 'red' : 'neutral'}
                />
              </dl>

              {/* Latency sparkline (если есть точек) */}
              {latencySeries.length >= 2 && (
                <MetricSpark
                  values={latencySeries}
                  tone={cb === 'closed' ? 'ok' : cb === 'half_open' ? 'warn' : 'danger'}
                  width={200}
                  height={20}
                  label={`latency p50 · ${latencySeries.length} точек`}
                />
              )}

              {/* Last error text */}
              {m?.last_error_text && (
                <div
                  className="text-[10px] text-rose-300/80 font-mono truncate"
                  title={m.last_error_text}
                >
                  err: {m.last_error_text}
                </div>
              )}

              {/* CB state hints */}
              {cb === 'half_open' && (
                <div className="text-[10px] text-amber-300 font-mono flex items-center gap-1">
                  <AlertTriangle size={10} />
                  следующий запрос — probe
                </div>
              )}
              {cb === 'open' && (
                <div className="text-[10px] text-red-300 font-mono flex items-center gap-1">
                  <XCircle size={10} />
                  цепь открыта
                </div>
              )}

              {/* Force-probe button — только когда цепь нездорова */}
              {canProbe && (
                <button
                  type="button"
                  onClick={() => probe.mutate(name)}
                  disabled={probe.isPending}
                  className={clsx(
                    'mt-1 inline-flex items-center gap-1 px-2 py-1 rounded',
                    'bg-indigo-700/80 hover:bg-indigo-600 disabled:opacity-50',
                    'text-[10px] font-mono text-white',
                  )}
                >
                  {probe.isPending
                    ? <Loader2 size={10} className="animate-spin" />
                    : <Zap size={10} />}
                  force probe
                </button>
              )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function Metric({ label, value, accent }: {
  label: string; value: string; accent?: 'green' | 'red' | 'amber' | 'neutral'
}) {
  return (
    <div>
      <dt className="text-[9px] uppercase tracking-widest text-gray-500 font-mono">{label}</dt>
      <dd className={clsx(
        'font-mono text-xs',
        accent === 'green'   && 'text-green-300',
        accent === 'red'     && 'text-red-300',
        accent === 'amber'   && 'text-amber-300',
        accent === 'neutral' && 'text-gray-300',
      )}>{value}</dd>
    </div>
  )
}

// ── Worker card ────────────────────────────────────────────────────────────

const WORKER_INTERVAL_OPTIONS = [10, 30, 60]

function WorkerCard() {
  const qc = useQueryClient()
  const workerQuery = useQuery({
    queryKey: ['matching', 'worker-job'],
    queryFn: () => fetchWorkerJob('match_worker'),
    refetchInterval: 5000,
  })

  const trigger = useMutation({
    mutationFn: triggerMatchWorker,
    onSuccess: () => {
      toast.success('Воркер запущен — обработка батча начнётся через 1-2 сек')
      qc.invalidateQueries({ queryKey: ['matching', 'worker-job'] })
      qc.invalidateQueries({ queryKey: ['catalog', 'ml-status'] })
    },
    onError: (e: Error) => toast.error(`Не удалось запустить воркер: ${e.message}`),
  })

  // Renamed: `setInterval` локальное имя конфликтовало с глобальным window.setInterval.
  const setIntervalMut = useMutation({
    mutationFn: (sec: number) => updateWorkerInterval(sec),
    onSuccess: (data) => {
      toast.success(`Интервал обновлён: ${data.params.interval_sec}с`)
      qc.invalidateQueries({ queryKey: ['matching', 'worker-job'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const job = workerQuery.data as SchedulerJobInfoWithHistory | undefined
  const intervalSec = (job?.params?.interval_sec as number) ?? 10
  const tickHistory = job?.tick_history ?? []

  // Tick countdown — 250ms client tick для прогресс-бара
  const { secondsLeft, progress } = useWorkerTickCountdown(job?.next_run_at ?? null, intervalSec)

  // 3 mini-sparklines: durations, throughput (durations за интервал), fail rate.
  // throughput тут грубо — proxy через durations.
  const durations = tickHistory.map(t => t.duration_ms)
  const errorRate = tickHistory.length > 0
    ? tickHistory.filter(t => t.error).length / tickHistory.length
    : 0

  return (
    <Card
      title="match_worker · обработка очереди"
      tooltip="APScheduler interval-job. Каждые N сек берёт batch из match_queue (FOR UPDATE SKIP LOCKED), прогоняет через T2 и/или T3, финализирует offers. max_instances=1 — параллельные тики невозможны."
      helpTopic="matching.worker_interval"
      right={<JobStatusPill job={job} />}
    >
      <div className="space-y-3">
        {/* Главный визуал — tick countdown + progress между тиками */}
        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-mono tabular-nums text-indigo-300 leading-none">
                {secondsLeft}
              </span>
              <span className="text-[10px] uppercase tracking-wider text-gray-600">
                sec до next tick
              </span>
            </div>
            <div className="text-[10px] font-mono text-gray-500">
              interval <span className="text-gray-300">{intervalSec}s</span>
            </div>
          </div>
          <div className="h-1.5 bg-gray-800/60 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500/80 transition-[width] duration-150"
              style={{ width: `${progress * 100}%` }}
            />
          </div>
        </div>

        {/* Run-history: 3 mini sparklines */}
        {durations.length >= 2 && (
          <div className="grid grid-cols-3 gap-3 pt-2 border-t border-gray-800/50">
            <div>
              <div className="text-[9px] uppercase tracking-widest text-gray-500 font-mono mb-0.5">
                tick duration
              </div>
              <MetricSpark
                values={durations}
                tone={Math.max(...durations) > intervalSec * 1000 ? 'warn' : 'ok'}
                width={120}
                height={20}
                label={`${(durations[durations.length - 1] / 1000).toFixed(1)}s last`}
              />
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-widest text-gray-500 font-mono mb-0.5">
                error rate
              </div>
              <div className="flex items-center gap-2">
                <span className={clsx(
                  'text-base font-mono tabular-nums',
                  errorRate > 0.1 ? 'text-rose-300' : 'text-gray-400',
                )}>
                  {(errorRate * 100).toFixed(0)}%
                </span>
                <span className="text-[9px] text-gray-600">
                  {tickHistory.filter(t => t.error).length}/{tickHistory.length}
                </span>
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-widest text-gray-500 font-mono mb-0.5">
                history
              </div>
              <div className="text-[10px] font-mono text-gray-500">
                {tickHistory.length} тиков (~{Math.round((tickHistory.length * intervalSec) / 60)}мин)
              </div>
            </div>
          </div>
        )}

        {/* Static info row */}
        <div className="grid grid-cols-3 gap-3 text-xs pt-2 border-t border-gray-800/50">
          <KV label="last_run_at" value={relativeTime(job?.last_run_at ?? null)} mono />
          <KV label="next_run_at" value={relativeTime(job?.next_run_at ?? null)} mono />
          <KV label="status" value={job?.last_run_status ?? '—'} mono />
        </div>

        {/* Controls: interval + trigger */}
        <div className="flex items-center justify-between gap-3 pt-2 border-t border-gray-800/50">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">
              interval
            </span>
            <InfoTip text="Как часто воркер тикает. Дефолт 10с. Поставь 30с если хочется снизить нагрузку, или 5с для быстрой обработки бэклога." />
            <div className="flex bg-gray-900 border border-gray-800 rounded overflow-hidden">
              {WORKER_INTERVAL_OPTIONS.map(sec => (
                <button
                  key={sec}
                  type="button"
                  onClick={() => sec !== intervalSec && setIntervalMut.mutate(sec)}
                  disabled={setIntervalMut.isPending}
                  className={clsx(
                    'px-2.5 py-1 text-[11px] font-mono transition-colors',
                    sec === intervalSec
                      ? 'bg-indigo-700/80 text-white'
                      : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200',
                  )}
                >
                  {sec}s
                </button>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={() => trigger.mutate()}
            disabled={trigger.isPending}
            className={clsx(
              'inline-flex items-center gap-1.5 px-3 py-1.5 rounded',
              'bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50',
              'text-white text-xs font-medium',
              'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.15)]',
            )}
          >
            {trigger.isPending
              ? <Loader2 size={12} className="animate-spin" />
              : <PlayCircle size={12} />}
            Запустить тик сейчас (R)
          </button>
        </div>

        <p className="text-[10px] text-gray-500">
          Кнопка полезна сразу после re-enqueue или для дебага. Иначе воркер сам тикнет через {intervalSec}с.
        </p>
      </div>
    </Card>
  )
}

// Локальный clientside countdown — обновляется каждые 250ms пока есть next_run_at.
function useWorkerTickCountdown(nextRunAt: string | null, intervalSec: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!nextRunAt) return
    const id = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(id)
  }, [nextRunAt])
  if (!nextRunAt) return { secondsLeft: 0, progress: 0 }
  const target = new Date(nextRunAt).getTime()
  const secondsLeft = Math.max(0, (target - now) / 1000)
  const progress = intervalSec > 0
    ? Math.min(1, 1 - secondsLeft / intervalSec)
    : 0
  return { secondsLeft: Math.ceil(secondsLeft), progress }
}

function JobStatusPill({ job }: { job: SchedulerJobInfoWithHistory | undefined }) {
  if (!job) return null
  const status = job.last_run_status
  const enabled = job.enabled
  if (!enabled) {
    return <Pill className="bg-zinc-800/50 text-zinc-500 border-zinc-700/50">disabled</Pill>
  }
  if (!status) return <Pill className="bg-zinc-800/40 text-zinc-500 border-zinc-700/50">не запускался</Pill>
  if (status === 'done')    return <Pill className="bg-emerald-500/15 text-emerald-300 border-emerald-500/30">done</Pill>
  if (status === 'running') return <Pill className="bg-indigo-500/15 text-indigo-300 border-indigo-500/30">running</Pill>
  if (status === 'pending') return <Pill className="bg-amber-500/15 text-amber-300 border-amber-500/30">pending</Pill>
  if (status === 'failed')  return <Pill className="bg-rose-500/15 text-rose-300 border-rose-500/30">failed</Pill>
  return <Pill className="bg-zinc-800/40 text-zinc-400 border-zinc-700/50">{status}</Pill>
}

// ── Warmup card ────────────────────────────────────────────────────────────

function WarmupCard() {
  const [lastJobId, setLastJobId] = useState<number | null>(null)

  const warmup = useMutation({
    mutationFn: () => startWarmupEmbeddings({}),
    onSuccess: (data) => {
      setLastJobId(data.job_id)
      toast.success(`Warmup запущен (job #${data.job_id}). Следи через /bgg-sync → История.`)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <Card
      title="Warmup эмбеддингов"
      tooltip="Прогон через bge-m3 для всех записей в games/game_aliases. Заполняет таблицу game_embeddings — основа T2 cosine search. Полный прогон по 162К игр ~1.5-4 часа, фоновый ImportJob."
      right={lastJobId !== null && (
        <span className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
          last job_id={lastJobId}
        </span>
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs text-gray-400 leading-relaxed">
          Запускай после <code className="text-indigo-300">ollama pull bge-m3</code>, после массового импорта BGG,
          или периодически (раз в месяц) чтобы покрыть новые алиасы.
        </p>
        <button
          type="button"
          onClick={() => warmup.mutate()}
          disabled={warmup.isPending}
          className={clsx(
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded',
            'bg-amber-700/70 hover:bg-amber-600/80 disabled:opacity-50',
            'text-white text-xs font-medium flex-shrink-0',
            'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.15)]',
          )}
        >
          {warmup.isPending
            ? <Loader2 size={12} className="animate-spin" />
            : <Flame size={12} />}
          Прогреть эмбеддинги
        </button>
      </div>
    </Card>
  )
}

// ── Shared layout primitives ───────────────────────────────────────────────

function Card({ title, tooltip, helpTopic, right, children }: {
  title: string
  /** Короткий InfoTip (hover) — для быстрого пояснения концепта. */
  tooltip?: string
  /** Полный HelpBox (click-popup) — для подробного объяснения концепта. */
  helpTopic?: TopicId
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section
      className={clsx(
        'rounded-lg border border-gray-800/80 bg-gray-900/40 overflow-hidden',
        'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
      )}
    >
      <header className="flex items-center justify-between gap-4 px-4 py-2.5 border-b border-gray-800/60 bg-black/20">
        <h3 className="flex items-center gap-2 text-[11px] uppercase tracking-wider font-semibold text-gray-300">
          {title}
          {tooltip && <InfoTip text={tooltip} />}
          {helpTopic && <HelpBox topic={helpTopic} />}
        </h3>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  )
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-widest text-gray-500 font-mono">{label}</div>
      <div className={clsx('text-gray-300', mono && 'font-mono text-[11px]')}>{value}</div>
    </div>
  )
}

function Pill({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={clsx('inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono border tracking-wider uppercase', className)}>
      {children}
    </span>
  )
}

// satisfy unused-import linter — Zap/Settings2 may be needed in future polish
void Zap; void Settings2;
