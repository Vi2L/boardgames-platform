/**
 * JobHistoryTable — история ImportJob'ов с фильтрами type/status/trigger.
 *
 * Поддерживает оба источника:
 *   - manual (UI POST /import/bgg/...) — payload.trigger='manual' или отсутствует
 *   - scheduled (cron-сработка) — payload.trigger='scheduled'
 *
 * Polling 3 сек если есть pending/running, иначе 30 сек. Раскрытие строки —
 * лог-строки + result в JSON-блоке.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ChevronRight, ChevronDown } from 'lucide-react'
import clsx from 'clsx'

import { fetchImportJobs, type ImportJobsFilter } from '../../lib/bgg-sync'
import type { ImportJob } from '../../lib/catalog'

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

const STATUS_COLOR: Record<string, string> = {
  done:    'bg-emerald-900/50 text-emerald-300',
  running: 'bg-indigo-900/50 text-indigo-300',
  pending: 'bg-amber-900/40 text-amber-300',
  failed:  'bg-red-950/30 text-red-300',
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
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">Тип</label>
          <select
            value={filter.type ?? ''}
            onChange={e => setFilter(f => ({ ...f, type: e.target.value || undefined }))}
            className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            {TYPE_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">Статус</label>
          <select
            value={filter.status ?? ''}
            onChange={e => setFilter(f => ({ ...f, status: (e.target.value || undefined) as ImportJobsFilter['status'] }))}
            className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            {STATUS_OPTIONS.map(s => (
              <option key={s} value={s}>{s || 'все статусы'}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">Источник</label>
          <select
            value={filter.trigger ?? ''}
            onChange={e => setFilter(f => ({ ...f, trigger: (e.target.value || undefined) as ImportJobsFilter['trigger'] }))}
            className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            {TRIGGER_OPTIONS.map(t => (
              <option key={t} value={t}>{t || 'любой'}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Таблица */}
      {jobs.isLoading ? (
        <div className="text-xs text-gray-500 py-4 flex items-center gap-2">
          <Loader2 size={12} className="animate-spin" /> Загружаю историю…
        </div>
      ) : jobs.isError ? (
        <div className="text-xs text-red-400 py-4">{(jobs.error as Error).message}</div>
      ) : (jobs.data ?? []).length === 0 ? (
        <div className="text-xs text-gray-500 py-6 text-center">
          Нет job'ов с такими фильтрами.
        </div>
      ) : (
        <div className="border border-gray-800 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 border-b border-gray-800 text-xs text-gray-400">
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

  return (
    <>
      <tr
        className="border-b border-gray-800 last:border-b-0 hover:bg-gray-900/40 cursor-pointer"
        onClick={() => setOpen(o => !o)}
      >
        <td className="px-3 py-2 text-gray-500">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </td>
        <td className="px-3 py-2 font-mono text-xs text-gray-400">#{job.id}</td>
        <td className="px-3 py-2 text-xs text-gray-300">{job.type}</td>
        <td className="px-3 py-2 text-xs text-gray-400">{trigger}</td>
        <td className="px-3 py-2">
          <span className={clsx(
            'text-[10px] px-1.5 py-0.5 rounded',
            STATUS_COLOR[job.status] ?? 'bg-gray-800 text-gray-400',
          )}>
            {job.status}
          </span>
        </td>
        <td className="px-3 py-2 text-xs text-gray-500 font-mono">
          {formatDt(job.created_at)}
        </td>
        <td className="px-3 py-2 text-xs text-gray-500 font-mono">
          {durationSec(job.started_at, job.finished_at)}
        </td>
      </tr>
      {open && (
        <tr className="bg-gray-950/40">
          <td colSpan={7} className="px-4 py-3 border-b border-gray-800">
            <JobDetails job={job} />
          </td>
        </tr>
      )}
    </>
  )
}

function JobDetails({ job }: { job: ImportJob }) {
  const progress = job.progress
  return (
    <div className="space-y-2 text-xs">
      {progress && progress.total > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Прогресс
          </div>
          <div className="text-gray-400 mb-1">
            <span className="text-indigo-300">{progress.phase}</span>
            {' '}· {progress.current} / {progress.total}
            {progress.current_title && (
              <span className="ml-2 text-gray-500">— {progress.current_title}</span>
            )}
          </div>
          <div className="w-full bg-gray-800 rounded-full h-1 overflow-hidden">
            <div
              className="bg-indigo-500 h-full transition-all"
              style={{ width: `${Math.min(100, (progress.current / progress.total) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {job.result && (
        <details className="text-gray-400">
          <summary className="cursor-pointer text-[11px] hover:text-gray-200">
            Результат
          </summary>
          <pre className="mt-1 max-h-40 overflow-y-auto text-[10px] font-mono text-gray-500 bg-gray-950 p-2 rounded border border-gray-800">
            {JSON.stringify(job.result, null, 2)}
          </pre>
        </details>
      )}

      {job.error && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-red-400">Ошибка</div>
          <pre className="mt-1 text-[10px] font-mono text-red-300 break-all whitespace-pre-wrap">
            {job.error}
          </pre>
        </div>
      )}

      {job.log_lines && job.log_lines.length > 0 && (
        <details className="text-gray-400" open={job.status === 'running'}>
          <summary className="cursor-pointer text-[11px] hover:text-gray-200">
            Лог ({job.log_lines.length} строк)
          </summary>
          <pre className="mt-1 max-h-60 overflow-y-auto text-[10px] font-mono text-gray-500 bg-gray-950 p-2 rounded border border-gray-800 whitespace-pre-wrap">
            {job.log_lines.slice(-100).join('\n')}
          </pre>
        </details>
      )}
    </div>
  )
}
