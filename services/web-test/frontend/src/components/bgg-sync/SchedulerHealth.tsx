/**
 * SchedulerHealth — карточки трёх scheduled-job'ов с health-метриками.
 *
 * На каждой карточке:
 *   - title (display_name) + описание (collapsible).
 *   - status последнего запуска (цветной badge).
 *   - last_run_at / next_run_at.
 *   - кнопка «Запустить сейчас» (manual trigger через POST /trigger).
 *   - inline cron editor (раскрывается по кнопке «Изменить расписание»).
 *
 * Polling каждые 10 сек — конфиги меняются редко, но last_run_status обновляется
 * при срабатывании cron'а. Если есть активный last_run_job_id со статусом
 * pending/running, polling ускоряется до 2 сек чтобы UI отразил движение.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, Play, ChevronDown, ChevronRight, Settings2 } from 'lucide-react'
import clsx from 'clsx'

import {
  fetchSchedulerJobs,
  rescheduleJob,
  triggerSchedulerJob,
  type SchedulerJob,
  type RescheduleRequest,
} from '../../lib/bgg-sync'

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
  running: 'bg-violet-900/50 text-violet-300',
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
      {data.map(job => <JobCard key={job.job_id} job={job} />)}
    </div>
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
            <h3 className="text-sm font-semibold text-gray-100">
              {job.display_name ?? job.job_id}
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
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white rounded"
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

// ── Cron editor (inline) ─────────────────────────────────────────────────────

function CronEditor({ job, onClose }: { job: SchedulerJob; onClose: () => void }) {
  const qc = useQueryClient()
  const [cron, setCron] = useState(job.cron_expr)
  const [enabled, setEnabled] = useState(job.enabled)
  // Params как JSON-текст, пользователь редактирует напрямую. Простота вместо
  // per-job динамической формы — сейчас параметров мало (1-3 на job).
  const [paramsText, setParamsText] = useState(JSON.stringify(job.params, null, 2))

  const save = useMutation({
    mutationFn: () => {
      let parsedParams: Record<string, unknown> | undefined
      try {
        parsedParams = JSON.parse(paramsText)
      } catch (e) {
        throw new Error(`params: невалидный JSON (${(e as Error).message})`)
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
    <div className="mt-3 pt-3 border-t border-gray-800 space-y-2.5">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Cron expression (UTC)
          </label>
          <input
            type="text"
            value={cron}
            onChange={e => setCron(e.target.value)}
            className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs font-mono text-gray-200 focus:outline-none focus:border-violet-500"
            placeholder="0 3 * * 1"
          />
          <div className="mt-1 text-[10px] text-gray-500">
            формат: «мин час день_мес мес день_нед»
          </div>
        </div>

        <div>
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer mt-5">
            <input
              type="checkbox"
              checked={enabled}
              onChange={e => setEnabled(e.target.checked)}
            />
            Enabled
          </label>
          <div className="mt-1 text-[10px] text-gray-500">
            disabled → scheduler паузит этот job
          </div>
        </div>
      </div>

      <div>
        <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
          Params (JSON)
        </label>
        <textarea
          value={paramsText}
          onChange={e => setParamsText(e.target.value)}
          rows={3}
          className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs font-mono text-gray-200 focus:outline-none focus:border-violet-500"
        />
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white rounded"
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
