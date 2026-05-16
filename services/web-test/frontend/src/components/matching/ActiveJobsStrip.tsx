/**
 * ActiveJobsStrip — persistent индикатор активных long-running jobs.
 *
 * До этого warmup запускался → toast → исчезал. Оператор забывал что job
 * вообще идёт. Теперь — закреплённая полоса под header'ом /matching с
 * прогрессом каждого активного ImportJob.
 *
 * Источник данных: TanStack Query `/api/catalog/import/jobs?status=active`
 * (либо клиентский filter из /import/jobs по status). На этом этапе делаем
 * простой polling 3s — лишний оверхед минимален.
 *
 * Card per-job: progress + current item + ETA + клик → переход на /bgg-sync
 * с filter по job id (или /matching → Журнал для warmup).
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Flame, ArrowRight, Loader2 } from 'lucide-react'
import clsx from 'clsx'

// Прямой fetch — этот endpoint catalog'а уже есть (через web-test proxy
// /api/catalog/import/jobs). Filter по статусу делаем на клиенте — backend
// эндпоинт может не поддерживать ?status=, но проксирует существующий.

interface ImportJob {
  id: number
  type: string
  status: 'pending' | 'running' | 'done' | 'failed'
  created_at: string
  started_at: string | null
  finished_at: string | null
  progress: {
    phase?: string
    current?: number
    total?: number
    current_title?: string
  } | null
}

async function fetchActiveJobs(): Promise<ImportJob[]> {
  // Reuse существующего endpoint'а: GET /api/catalog/import/jobs?limit=N
  // фильтруем на клиенте — backend может не поддерживать ?status=.
  const r = await fetch('/api/catalog/import/jobs?limit=20')
  if (!r.ok) throw new Error(`${r.status}`)
  const data = await r.json() as { items: ImportJob[] }
  return data.items.filter(j => j.status === 'running' || j.status === 'pending')
}

export function ActiveJobsStrip({ className }: { className?: string }) {
  const navigate = useNavigate()
  const jobsQ = useQuery({
    queryKey: ['matching', 'active-jobs'],
    queryFn: fetchActiveJobs,
    refetchInterval: 3_000,
    // Endpoint может не существовать в текущей сборке — UI деградирует через
    // catch (showing nothing). NOT showing error toast — это операционная
    // деталь, не нужна оператору в каждой сессии.
    retry: false,
  })

  const jobs = jobsQ.data ?? []
  if (jobsQ.isLoading || jobs.length === 0) {
    return null
  }

  const handleClick = (job: ImportJob) => {
    // BGG-job → /bgg-sync, warmup → /matching → Контроль (warmup ImportJob
    // обычно type=warmup-embeddings). Простой routing на основе типа.
    if (job.type.startsWith('warmup')) {
      navigate('/matching')
    } else {
      navigate('/bgg-sync')
    }
  }

  return (
    <div className={clsx(
      'flex items-center gap-3 px-4 py-2 overflow-x-auto',
      'bg-amber-500/5 border-y border-amber-500/20',
      className,
    )}>
      <span className="text-xxs font-mono uppercase tracking-widest text-amber-300 shrink-0">
        active jobs
      </span>
      <div className="flex items-center gap-2 flex-1 min-w-0">
        {jobs.map(job => (
          <JobCard key={job.id} job={job} onClick={() => handleClick(job)} />
        ))}
      </div>
    </div>
  )
}

function JobCard({ job, onClick }: { job: ImportJob; onClick: () => void }) {
  const p = job.progress
  const pct = p?.total && p?.current != null
    ? Math.min(100, Math.round((p.current / p.total) * 100))
    : null

  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'flex items-center gap-2 px-2.5 py-1.5 rounded',
        'bg-zinc-900/60 border border-zinc-800',
        'hover:border-amber-500/40 hover:bg-zinc-900',
        'text-xs text-zinc-300 transition-colors',
        'shrink-0 max-w-md',
      )}
    >
      <Loader2 size={11} className="animate-spin text-amber-400 shrink-0" />
      <span className="font-mono text-zinc-500 shrink-0">{job.type} #{job.id}</span>
      {p?.current_title && (
        <span className="truncate text-zinc-400 max-w-[160px]" title={p.current_title}>
          {p.current_title}
        </span>
      )}
      {pct !== null && (
        <span className="font-mono tabular-nums text-amber-300 shrink-0">
          {p?.current}/{p?.total} · {pct}%
        </span>
      )}
      <ArrowRight size={11} className="text-zinc-600 shrink-0" />
    </button>
  )
}

void Flame  // future: badge icon
