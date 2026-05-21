/**
 * SchedulerHealth — карточки scheduler-job'ов с health-метриками.
 *
 * На каждой карточке:
 *   - title (display_name) + описание (collapsible).
 *   - status последнего запуска (цветной badge).
 *   - last_run_at / next_run_at.
 *   - кнопка «Запустить сейчас» (manual trigger через POST /trigger).
 *   - inline cron editor (раскрывается по кнопке «Изменить расписание»).
 *     — WT-F7: schema-driven форма по `params_schema` из API + cron-builder
 *       с пресетами и human-readable preview (cronstrue).
 *
 * Над списком — GlobalBggSettings (BGG token + cascade) и bulk-toolbar
 * (pause-all / resume-all / trigger-overdue).
 *
 * Polling каждые 10 сек — конфиги меняются редко, но last_run_status обновляется
 * при срабатывании cron'а. Если есть активный last_run_job_id со статусом
 * pending/running, polling ускоряется до 2 сек чтобы UI отразил движение.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Loader2, Play, ChevronDown, ChevronRight, Settings2,
  Pause, PlayCircle, Zap,
} from 'lucide-react'
import clsx from 'clsx'

import {
  fetchSchedulerJobs,
  rescheduleJob,
  triggerSchedulerJob,
  pauseAllJobs,
  resumeAllJobs,
  triggerOverdueJobs,
  type SchedulerJob,
  type RescheduleRequest,
  type SchedulerBulkActionResult,
} from '../../lib/bgg-sync'
import { CronInput } from './CronInput'
import { SchemaForm } from './SchemaForm'
import { GlobalBggSettings } from './GlobalBggSettings'
import { HelpBox } from '../shared/HelpBox'
import type { TopicId } from '../../lib/help-topics'

/**
 * Маппинг scheduler-job_id → help-topic. Не у каждого job'а есть HelpBox —
 * только у тех, чьи концепты неочевидны оператору. Список синхронизируется
 * с `HELP_TOPICS` в `lib/help-topics.tsx`.
 */
const JOB_HELP_TOPICS: Partial<Record<string, TopicId>> = {
  bgg_top_sync: 'bgg_sync.bgg_top_sync',
  bgg_hotness_sync: 'bgg_sync.bgg_hotness_sync',
  bgg_mini_batch: 'bgg_sync.bgg_mini_batch',
  bgg_family_refresh: 'bgg_sync.bgg_family_refresh',
  bgg_yearly_releases: 'bgg_sync.bgg_yearly_releases',
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) {
    // future — относительное «через …»
    const future = -ms
    if (future < 60_000) return 'через <1 мин'
    if (future < 3600_000) return `через ${Math.round(future / 60_000)} мин`
    if (future < 86400_000) return `через ${Math.round(future / 3600_000)} ч`
    return `через ${Math.round(future / 86400_000)} дн`
  }
  if (ms < 60_000) return 'только что'
  if (ms < 3600_000) return `${Math.round(ms / 60_000)} мин назад`
  if (ms < 86400_000) return `${Math.round(ms / 3600_000)} ч назад`
  return `${Math.round(ms / 86400_000)} дн назад`
}

const STATUS_COLOR: Record<string, string> = {
  done:    'bg-emerald-900/50 text-emerald-300',
  running: 'bg-indigo-900/50 text-indigo-300',
  pending: 'bg-amber-900/40 text-amber-300',
  failed:  'bg-red-950/30 text-red-300',
}

// ── Main component ───────────────────────────────────────────────────────────

export function SchedulerHealth() {
  const jobs = useQuery({
    queryKey: ['bgg-sync', 'scheduler', 'jobs'],
    queryFn: fetchSchedulerJobs,
    // Если хотя бы у одного job'а есть active run — учащаем polling.
    refetchInterval: (q) => {
      const data = q.state.data
      if (!data) return 10_000
      const anyActive = data.some(
        j => j.last_run_status === 'pending' || j.last_run_status === 'running'
      )
      return anyActive ? 2_000 : 10_000
    },
  })

  if (jobs.isLoading) {
    return <div className="text-xs text-gray-500 py-4">Загружаю scheduler…</div>
  }
  if (jobs.isError) {
    return (
      <div className="text-xs text-red-400 py-4">
        Ошибка: {(jobs.error as Error).message}
      </div>
    )
  }

  const data = jobs.data ?? []
  if (data.length === 0) {
    return (
      <div className="text-xs text-gray-500 py-4">
        Scheduled-job'ы не зарегистрированы. Накатите миграцию 0010
        (она сидит дефолтные конфиги).
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <GlobalBggSettings />
      <BulkActionsToolbar jobs={data} />
      {data.map(job => <JobCard key={job.job_id} job={job} />)}
    </div>
  )
}

// ── Bulk actions toolbar (WT-F7) ─────────────────────────────────────────────

function BulkActionsToolbar({ jobs }: { jobs: SchedulerJob[] }) {
  const qc = useQueryClient()
  const enabledCount = jobs.filter(j => j.enabled).length
  const disabledCount = jobs.length - enabledCount
  const now = Date.now()
  const overdueCount = jobs.filter(j => {
    if (!j.enabled || !j.next_run_at) return false
    return new Date(j.next_run_at).getTime() < now
  }).length

  const onSuccess = (label: string) => (res: SchedulerBulkActionResult) => {
    const errs = res.errors.length
    toast.success(
      `${label}: затронуто ${res.affected.length}` +
      (res.triggered_import_job_ids.length ? `, запущено ${res.triggered_import_job_ids.length}` : '') +
      (errs ? `, ошибок ${errs}` : ''),
    )
    qc.invalidateQueries({ queryKey: ['bgg-sync', 'scheduler', 'jobs'] })
    qc.invalidateQueries({ queryKey: ['bgg-sync', 'jobs'] })
  }
  const onError = (e: Error) => toast.error(e.message)

  const pause = useMutation({ mutationFn: pauseAllJobs, onSuccess: onSuccess('Pause all'), onError })
  const resume = useMutation({ mutationFn: resumeAllJobs, onSuccess: onSuccess('Resume all'), onError })
  const overdue = useMutation({ mutationFn: triggerOverdueJobs, onSuccess: onSuccess('Trigger overdue'), onError })

  const anyPending = pause.isPending || resume.isPending || overdue.isPending

  return (
    <div className="border border-gray-800 bg-gray-900/40 rounded-lg p-3 flex items-center gap-2">
      <div className="text-[10px] uppercase tracking-wide text-gray-500 mr-1">Bulk actions</div>
      <BulkButton
        icon={<Pause size={11} />}
        label={`Pause all (${enabledCount})`}
        disabled={anyPending || enabledCount === 0}
        loading={pause.isPending}
        onClick={() => {
          if (!confirm(`Disable ${enabledCount} enabled-job(ы)? Это остановит все scheduled-запуски до Resume.`)) return
          pause.mutate()
        }}
      />
      <BulkButton
        icon={<PlayCircle size={11} />}
        label={`Resume all (${disabledCount})`}
        disabled={anyPending || disabledCount === 0}
        loading={resume.isPending}
        onClick={() => resume.mutate()}
      />
      <BulkButton
        icon={<Zap size={11} />}
        label={`Trigger overdue (${overdueCount})`}
        disabled={anyPending || overdueCount === 0}
        loading={overdue.isPending}
        onClick={() => overdue.mutate()}
      />
      <div className="text-[10px] text-gray-500 ml-auto">
        Всего {jobs.length} · enabled {enabledCount} · overdue {overdueCount}
      </div>
    </div>
  )
}

function BulkButton({
  icon, label, loading, disabled, onClick,
}: {
  icon: React.ReactNode
  label: string
  loading?: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded',
        'bg-gray-800 hover:bg-gray-700 text-gray-200',
        'disabled:opacity-40 disabled:cursor-not-allowed',
      )}
    >
      {loading ? <Loader2 size={11} className="animate-spin" /> : icon}
      {label}
    </button>
  )
}

// ── Single job card ──────────────────────────────────────────────────────────

function JobCard({ job }: { job: SchedulerJob }) {
  const qc = useQueryClient()
  const [editingCron, setEditingCron] = useState(false)
  const [showDescription, setShowDescription] = useState(false)

  const trigger = useMutation({
    mutationFn: () => triggerSchedulerJob(job.job_id),
    onSuccess: (importJob) => {
      toast.success(`${job.display_name ?? job.job_id} запущен (job #${importJob.id})`)
      qc.invalidateQueries({ queryKey: ['bgg-sync', 'scheduler', 'jobs'] })
      qc.invalidateQueries({ queryKey: ['bgg-sync', 'jobs'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const isActive = job.last_run_status === 'pending' || job.last_run_status === 'running'
  const statusClass = job.last_run_status
    ? STATUS_COLOR[job.last_run_status] ?? 'bg-gray-800 text-gray-400'
    : 'bg-gray-800 text-gray-500'

  return (
    <div
      className={clsx(
        'border rounded-lg p-4 transition-colors',
        job.enabled
          ? 'border-gray-800 bg-gray-900/40'
          : 'border-gray-800/50 bg-gray-900/20 opacity-60',
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-semibold text-gray-100 inline-flex items-center gap-1.5">
              {job.display_name ?? job.job_id}
              {JOB_HELP_TOPICS[job.job_id] && (
                <HelpBox topic={JOB_HELP_TOPICS[job.job_id]!} />
              )}
            </h3>
            {!job.enabled && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">
                disabled
              </span>
            )}
            <span className={clsx(
              'text-[10px] px-1.5 py-0.5 rounded',
              statusClass,
            )}>
              {job.last_run_status ?? 'never run'}
            </span>
          </div>

          <div className="text-[11px] text-gray-500 font-mono">
            {job.job_id} · cron: <span className="text-gray-400">{job.cron_expr}</span>
          </div>

          {job.description && (
            <button
              type="button"
              onClick={() => setShowDescription(s => !s)}
              className="mt-1 flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-300"
            >
              {showDescription ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
              описание
            </button>
          )}
          {showDescription && job.description && (
            <p className="mt-1 text-[11px] text-gray-400 leading-relaxed">
              {job.description}
            </p>
          )}
        </div>

        <div className="flex flex-col items-end gap-1.5">
          <button
            type="button"
            onClick={() => trigger.mutate()}
            disabled={trigger.isPending || isActive}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 text-white rounded"
          >
            {trigger.isPending || isActive
              ? <Loader2 size={11} className="animate-spin" />
              : <Play size={11} />}
            Запустить
          </button>
          <button
            type="button"
            onClick={() => setEditingCron(s => !s)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded"
          >
            <Settings2 size={11} />
            {editingCron ? 'Скрыть' : 'Настроить'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mt-3 text-[11px]">
        <Stat label="Последний запуск" value={
          job.last_run_at
            ? `${formatDateTime(job.last_run_at)} (${timeAgo(job.last_run_at)})`
            : '—'
        } />
        <Stat label="Следующий запуск" value={
          job.next_run_at
            ? `${formatDateTime(job.next_run_at)} (${timeAgo(job.next_run_at)})`
            : (job.enabled ? '—' : 'не запланирован')
        } />
      </div>

      {editingCron && <CronEditor job={job} onClose={() => setEditingCron(false)} />}
    </div>
  )
}

// ── Stat row ─────────────────────────────────────────────────────────────────

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className="text-gray-300 font-mono text-[11px]">{value}</div>
    </div>
  )
}

// ── Cron editor (inline, WT-F7 schema-driven) ────────────────────────────────

function CronEditor({ job, onClose }: { job: SchedulerJob; onClose: () => void }) {
  const qc = useQueryClient()
  const [cron, setCron] = useState(job.cron_expr)
  const [enabled, setEnabled] = useState(job.enabled)

  // WT-F7: если у job'а есть зарегистрированная схема — рендерим SchemaForm.
  // Иначе — fallback на raw JSON-textarea (backward-compat для job'ов без схемы).
  const hasSchema = Array.isArray(job.params_schema)
  const [schemaValues, setSchemaValues] = useState<Record<string, unknown>>(job.params)
  const [paramsText, setParamsText] = useState(JSON.stringify(job.params, null, 2))

  const save = useMutation({
    mutationFn: () => {
      let parsedParams: Record<string, unknown> | undefined
      if (hasSchema) {
        parsedParams = schemaValues
      } else {
        try {
          parsedParams = JSON.parse(paramsText)
        } catch (e) {
          throw new Error(`params: невалидный JSON (${(e as Error).message})`)
        }
      }
      const payload: RescheduleRequest = {
        cron_expr: cron !== job.cron_expr ? cron : undefined,
        enabled: enabled !== job.enabled ? enabled : undefined,
        params: parsedParams,
      }
      return rescheduleJob(job.job_id, payload)
    },
    onSuccess: () => {
      toast.success(`Конфиг ${job.job_id} обновлён`)
      qc.invalidateQueries({ queryKey: ['bgg-sync', 'scheduler', 'jobs'] })
      onClose()
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <div className="mt-3 pt-3 border-t border-gray-800 space-y-3">
      <div className="grid grid-cols-[2fr_1fr] gap-3 items-start">
        <div>
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Cron expression (UTC)
          </label>
          <CronInput value={cron} onChange={setCron} />
        </div>

        <div>
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Состояние
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer py-1.5">
            <input
              type="checkbox"
              checked={enabled}
              onChange={e => setEnabled(e.target.checked)}
            />
            {enabled ? 'enabled' : 'disabled'}
          </label>
          <div className="mt-1 text-[10px] text-gray-500">
            disabled → scheduler паузит этот job
          </div>
        </div>
      </div>

      <div>
        <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1.5 inline-flex items-center gap-1.5">
          Параметры
          <HelpBox topic="bgg_sync.retention_params" />
        </label>
        {hasSchema ? (
          <SchemaForm
            schema={job.params_schema!}
            values={schemaValues}
            onChange={setSchemaValues}
          />
        ) : (
          <textarea
            value={paramsText}
            onChange={e => setParamsText(e.target.value)}
            rows={3}
            className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs font-mono text-gray-200 focus:outline-none focus:border-indigo-500"
          />
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 text-white rounded"
        >
          {save.isPending && <Loader2 size={11} className="animate-spin" />}
          Сохранить
        </button>
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
        >
          Отмена
        </button>
      </div>
    </div>
  )
}
