/**
 * JobHistoryTable — история ImportJob'ов с фильтрами type/status/trigger.
 *
 * Поддерживает оба источника:
 *   - manual (UI POST /import/bgg/...) — payload.trigger='manual' или отсутствует
 *   - scheduled (cron-сработка) — payload.trigger='scheduled'
 *
 * Polling 3 сек если есть pending/running, иначе 30 сек. Раскрытие строки —
 * shared `<JobView>` (см. components/jobs/) с прогрессом, phase strip и log.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ChevronRight, ChevronDown } from 'lucide-react'

import { fetchImportJobs, type ImportJobsFilter } from '../../lib/bgg-sync'
import type { ImportJob } from '../../lib/catalog'
import { Badge, type BadgeProps } from '../ui'
import { JobView, importJobToJobLike } from '../jobs'

const TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '',                 label: 'все типы' },
  { value: 'bgg-batch',        label: 'BGG batch (top sync)' },
  { value: 'bgg-mini-batch',   label: 'BGG mini-batch (daily)' },
  { value: 'bgg-hotness',      label: 'BGG Hotness' },
  { value: 'bgg-geeklist',     label: 'BGG GeekList' },
  { value: 'bgg',              label: 'BGG single' },
  { value: 'bgg-ranks',        label: 'BGG ranks CSV' },
  { value: 'tesera',           label: 'Tesera' },
  { value: 'dicefest',         label: 'Dicefest' },
]

const STATUS_OPTIONS = ['', 'pending', 'running', 'done', 'failed']
const TRIGGER_OPTIONS = ['', 'manual', 'scheduled', 'api']

/**
 * Mapping ImportJobStatus → Badge статус из tokens/status-system.
 * `running` маппится на `processing` (info tone) — это семантически
 * соответствует «job в работе» в единой системе.
 */
const STATUS_BADGE: Record<string, BadgeProps['status']> = {
  done:    'done',
  running: 'processing',
  pending: 'pending',
  failed:  'failed',
}

function formatDt(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function durationSec(start: string | null, end: string | null): string {
  if (!start) return '—'
  const startMs = new Date(start).getTime()
  const endMs = end ? new Date(end).getTime() : Date.now()
  const sec = Math.round((endMs - startMs) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
}

export function JobHistoryTable() {
  const [filter, setFilter] = useState<ImportJobsFilter>({})

  const jobs = useQuery({
    queryKey: ['bgg-sync', 'jobs', filter],
    queryFn: () => fetchImportJobs({ ...filter, limit: 50 }),
    // Polling по проектному паттерну: пока есть pending/running — обновляем,
    // как только все завершились — останавливаемся (false). При смене фильтра
    // queryKey меняется, TanStack Query сделает свежий fetch автоматически.
    refetchInterval: (q) => {
      const data = q.state.data as ImportJob[] | undefined
      if (!data) return 3_000
      const anyActive = data.some(j => j.status === 'pending' || j.status === 'running')
      return anyActive ? 3_000 : false
    },
  })

  return (
    <div className="space-y-3">
      {/* Фильтры */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xxs uppercase tracking-widest text-zinc-500 mb-1">Тип</label>
          <select
            value={filter.type ?? ''}
            onChange={e => setFilter(f => ({ ...f, type: e.target.value || undefined }))}
            className="w-full h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
          >
            {TYPE_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xxs uppercase tracking-widest text-zinc-500 mb-1">Статус</label>
          <select
            value={filter.status ?? ''}
            onChange={e => setFilter(f => ({ ...f, status: (e.target.value || undefined) as ImportJobsFilter['status'] }))}
            className="w-full h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
          >
            {STATUS_OPTIONS.map(s => (
              <option key={s} value={s}>{s || 'все статусы'}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xxs uppercase tracking-widest text-zinc-500 mb-1">Источник</label>
          <select
            value={filter.trigger ?? ''}
            onChange={e => setFilter(f => ({ ...f, trigger: (e.target.value || undefined) as ImportJobsFilter['trigger'] }))}
            className="w-full h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
          >
            {TRIGGER_OPTIONS.map(t => (
              <option key={t} value={t}>{t || 'любой'}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Таблица */}
      {jobs.isLoading ? (
        <div className="text-xs text-zinc-500 py-4 flex items-center gap-2">
          <Loader2 size={12} className="animate-spin" /> Загружаю историю…
        </div>
      ) : jobs.isError ? (
        <div className="text-xs text-rose-400 py-4">{(jobs.error as Error).message}</div>
      ) : (jobs.data ?? []).length === 0 ? (
        <div className="text-xs text-zinc-500 py-6 text-center">
          Нет job'ов с такими фильтрами.
        </div>
      ) : (
        <div className="border border-zinc-800 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-zinc-900 border-b border-zinc-800 text-xs text-zinc-400">
              <tr>
                <th className="text-left px-3 py-2 font-normal w-8"></th>
                <th className="text-left px-3 py-2 font-normal">ID</th>
                <th className="text-left px-3 py-2 font-normal">Тип</th>
                <th className="text-left px-3 py-2 font-normal">Источник</th>
                <th className="text-left px-3 py-2 font-normal">Статус</th>
                <th className="text-left px-3 py-2 font-normal">Создан</th>
                <th className="text-left px-3 py-2 font-normal">Длит.</th>
              </tr>
            </thead>
            <tbody>
              {(jobs.data ?? []).map(job => <JobRow key={job.id} job={job} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function JobRow({ job }: { job: ImportJob }) {
  const [open, setOpen] = useState(false)
  const trigger = (job.payload?.trigger as string) ?? '—'
  const badgeStatus = STATUS_BADGE[job.status]

  return (
    <>
      <tr
        className="border-b border-zinc-800 last:border-b-0 hover:bg-zinc-800/30 cursor-pointer"
        onClick={() => setOpen(o => !o)}
      >
        <td className="px-3 py-2 text-zinc-500">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </td>
        <td className="px-3 py-2 font-mono text-xs text-zinc-400">#{job.id}</td>
        <td className="px-3 py-2 text-xs text-zinc-300">{job.type}</td>
        <td className="px-3 py-2 text-xs text-zinc-400">{trigger}</td>
        <td className="px-3 py-2">
          {badgeStatus
            ? <Badge status={badgeStatus} size="xs" />
            : <span className="text-xs text-zinc-500">{job.status}</span>}
        </td>
        <td className="px-3 py-2 text-xs text-zinc-500 font-mono tabular-nums">
          {formatDt(job.created_at)}
        </td>
        <td className="px-3 py-2 text-xs text-zinc-500 font-mono tabular-nums">
          {durationSec(job.started_at, job.finished_at)}
        </td>
      </tr>
      {open && (
        <tr className="bg-zinc-950/40">
          <td colSpan={7} className="px-4 py-3 border-b border-zinc-800">
            <JobView job={importJobToJobLike(job)} showLog />
            {job.error && (
              <div className="mt-3">
                <div className="text-xxs uppercase tracking-widest text-rose-400">Ошибка</div>
                <pre className="mt-1 text-xxs font-mono text-rose-300 break-all whitespace-pre-wrap">
                  {job.error}
                </pre>
              </div>
            )}
            {job.result && (
              <details className="mt-3 text-zinc-400">
                <summary className="cursor-pointer text-xxs hover:text-zinc-200">
                  Результат (JSON)
                </summary>
                <pre className="mt-1 max-h-40 overflow-y-auto text-xxs font-mono text-zinc-500 bg-zinc-950 p-2 rounded border border-zinc-800">
                  {JSON.stringify(job.result, null, 2)}
                </pre>
              </details>
            )}
          </td>
        </tr>
      )}
    </>
  )
}
