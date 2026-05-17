/**
 * JobView — единый view одного long-running job'а.
 *
 * Спека: `pages/04-jobui.md` § Layout. Шаблон reuse'ится для BGG/Tesera
 * импорта, reassess-all, suite-runs, dicefest-staging — везде где
 * фронт следит за progress + log.
 *
 * Принимает нормализованный `JobLike` — adapter каждый домен пишет под себя.
 * UI не зависит от backend-схемы (ImportJob, suite-run, ...).
 *
 * Структура:
 *   Header  · status badge · name · phase summary · elapsed · actions
 *   Progress · ProgressBar + meta (current item · ok / skip / fail)
 *   Stats   · rate · elapsed · eta · ok/fail (4-col grid)
 *   Phases  · PhaseStrip (если known)
 *   Log     · JobLogPanel (ui/)
 */
import type { ReactNode } from 'react'
import { Badge, Button, ProgressBar, JobLogPanel, type BadgeProps } from '../ui'
import { PhaseStrip } from './PhaseStrip'

export type JobLikeStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'

/**
 * Унифицированная форма job'а. Domain-специфичные данные передаются через
 * adapter, который маппит свой `ImportJob`/`SuiteRun`/etc. на этот тип.
 */
export interface JobLike {
  id: string | number
  name: string                       // 'bgg-top-1000', 'reassess-all-2026-05-17', ...
  status: JobLikeStatus
  phase?: string | null
  /** Список known phases для PhaseStrip; если backend их не отдаёт — undefined. */
  phases?: string[]
  /** current / total — для progress bar. total=0 → бар скрыт. */
  progress?: { current: number; total: number; current_item?: string | null }
  startedAt?: string | null
  endedAt?: string | null
  /** Human-readable rate из backend; если нет — UI считать не пробует. */
  rate?: string | null
  ok?: number
  fail?: number
  skip?: number
  log_lines?: string[]
  canCancel?: boolean
  canRestart?: boolean
}

export interface JobViewProps {
  job: JobLike
  onCancel?: () => void
  onRestart?: () => void
  /** Дополнительные actions (например «Skip current»). Слот справа в header. */
  extraActions?: ReactNode
  /** Можно скрыть log panel — для очень компактных списков. */
  showLog?: boolean
  className?: string
}

const STATUS_BADGE: Record<JobLikeStatus, BadgeProps['status']> = {
  pending:   'pending',
  running:   'processing',
  done:      'done',
  failed:    'failed',
  cancelled: 'skipped',
}

const PROGRESS_TONE: Record<JobLikeStatus, 'info' | 'ok' | 'danger' | 'neutral'> = {
  pending:   'neutral',
  running:   'info',
  done:      'ok',
  failed:    'danger',
  cancelled: 'neutral',
}

export function JobView({
  job, onCancel, onRestart, extraActions, showLog = true, className,
}: JobViewProps) {
  const elapsed = formatElapsed(job.startedAt, job.endedAt)
  const eta = formatEta(job)
  const progressPct = job.progress && job.progress.total > 0
    ? Math.min(100, (job.progress.current / job.progress.total) * 100)
    : null

  return (
    <div className={`space-y-3 ${className ?? ''}`}>
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <Badge status={STATUS_BADGE[job.status]} size="sm" />
        <span className="font-mono text-xs text-zinc-300">{job.name}</span>
        {job.phase && (
          <span className="text-xs text-zinc-500">
            · <span className="text-indigo-300">{job.phase}</span>
          </span>
        )}
        {elapsed && (
          <span className="text-xs text-zinc-500 font-mono tabular-nums">
            · {elapsed}
            {eta && job.status === 'running' && <> · ETA {eta}</>}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          {extraActions}
          {job.canCancel && onCancel && (
            <Button variant="danger" size="xs" onClick={onCancel}>Cancel</Button>
          )}
          {job.canRestart && onRestart && (
            <Button variant="secondary" size="xs" onClick={onRestart}>Restart</Button>
          )}
        </div>
      </div>

      {/* Progress */}
      {progressPct !== null && job.progress && (
        <div className="space-y-1">
          <ProgressBar
            value={progressPct}
            tone={PROGRESS_TONE[job.status]}
            withLabel
            label={`${job.progress.current} / ${job.progress.total}`}
          />
          {(job.progress.current_item || job.ok != null) && (
            <div className="text-xxs text-zinc-500 flex items-center gap-3">
              {job.progress.current_item && (
                <span>
                  current: <span className="font-mono text-zinc-300">{job.progress.current_item}</span>
                </span>
              )}
              {job.ok != null && (
                <span>
                  <span className="text-emerald-400 font-mono tabular-nums">ok {job.ok}</span>
                  {job.skip != null && job.skip > 0 && (
                    <> · <span className="text-zinc-500 font-mono tabular-nums">skip {job.skip}</span></>
                  )}
                  {job.fail != null && job.fail > 0 && (
                    <> · <span className="text-rose-400 font-mono tabular-nums">fail {job.fail}</span></>
                  )}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Stats group: rate · elapsed · eta · ok/fail */}
      {(job.rate || elapsed || eta || job.ok != null) && (
        <div className="grid grid-cols-4 border border-zinc-800 rounded divide-x divide-zinc-800">
          <StatCell label="rate" value={job.rate ?? '—'} />
          <StatCell label="elapsed" value={elapsed ?? '—'} />
          <StatCell label="eta" value={eta ?? '—'} />
          <StatCell
            label="ok / fail"
            value={
              job.ok != null
                ? `${job.ok} / ${job.fail ?? 0}`
                : '—'
            }
            tone={job.fail && job.fail > 0 ? 'danger' : 'ok'}
          />
        </div>
      )}

      {/* Phase strip — если известны фазы или одна current */}
      {(job.phases || job.phase) && (
        <PhaseStrip phases={job.phases} current={job.phase ?? null} />
      )}

      {/* Log panel */}
      {showLog && job.log_lines && (
        <JobLogPanel lines={job.log_lines} height="h-48" />
      )}
    </div>
  )
}

function StatCell({
  label, value, tone,
}: {
  label: string
  value: string
  tone?: 'ok' | 'danger'
}) {
  const color =
    tone === 'ok' ? 'text-emerald-300' :
    tone === 'danger' ? 'text-rose-300' :
    'text-zinc-200'
  return (
    <div className="px-3 py-2">
      <div className="text-xxs uppercase tracking-widest text-zinc-500 font-mono">{label}</div>
      <div className={`text-sm font-mono tabular-nums ${color}`}>{value}</div>
    </div>
  )
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatElapsed(start: string | null | undefined, end: string | null | undefined): string | null {
  if (!start) return null
  const startMs = new Date(start).getTime()
  const endMs = end ? new Date(end).getTime() : Date.now()
  const sec = Math.max(0, Math.round((endMs - startMs) / 1000))
  return formatSeconds(sec)
}

function formatEta(job: JobLike): string | null {
  // ETA = (remaining / rate) если rate числовой parsable или (elapsed / current * remaining).
  // Без backend rate fallback на linear extrapolation.
  if (!job.progress || job.progress.total === 0 || !job.startedAt) return null
  const done = job.progress.current
  const total = job.progress.total
  if (done <= 0 || done >= total) return null

  const elapsedMs = Date.now() - new Date(job.startedAt).getTime()
  const remainingMs = (elapsedMs / done) * (total - done)
  return formatSeconds(Math.round(remainingMs / 1000))
}

function formatSeconds(sec: number): string {
  if (sec < 60) return `${sec}s`
  if (sec < 3600) {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m}m ${s}s`
  }
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return `${h}h ${m}m`
}
