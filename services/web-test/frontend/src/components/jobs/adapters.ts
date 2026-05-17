/**
 * Adapter'ы: маппинг domain-job'ов на унифицированный `JobLike` для `<JobView>`.
 *
 * Каждый импортёр / suite-runner / reassess-runner отдаёт свой shape; здесь —
 * один маппер на домен, чтобы UI не зависел от backend-схем. См. JobView.tsx.
 */
import type { ImportJob } from '../../lib/catalog'
import type { JobLike, JobLikeStatus } from './JobView'

// ── ImportJob (BGG / Tesera / Dicefest) ──────────────────────────────────────

const IMPORT_PHASES_KNOWN: Record<string, string[]> = {
  // ImportProgress.phase ∈ {'collecting','parsing','done',...}.
  // Display фазы — те же, что приходят с backend. UI не угадывает порядок,
  // если фаза не в этом списке.
  default: ['collecting', 'parsing', 'done'],
}

export function importJobToJobLike(j: ImportJob): JobLike {
  const status: JobLikeStatus =
    j.status === 'pending' || j.status === 'running' || j.status === 'done' || j.status === 'failed'
      ? j.status
      : 'pending'

  const counters = countersFromResult(j.result)

  return {
    id: j.id,
    name: `${j.type} #${j.id}`,
    status,
    phase: j.progress?.phase ?? null,
    phases: IMPORT_PHASES_KNOWN.default,
    progress: j.progress
      ? {
          current: j.progress.current,
          total: j.progress.total,
          current_item: j.progress.current_title,
        }
      : undefined,
    startedAt: j.started_at,
    endedAt: j.finished_at,
    ok: counters.ok,
    fail: counters.fail,
    skip: counters.skip,
    log_lines: j.log_lines ?? undefined,
    canCancel: false, // backend пока не поддерживает (см. handoff CLAUDE.md §11)
    canRestart: status === 'done' || status === 'failed',
  }
}

function countersFromResult(r: ImportJob['result']): { ok: number; fail: number; skip: number } {
  if (!r) return { ok: 0, fail: 0, skip: 0 }
  const ok = (r.imported?.length ?? 0)
  const fail = (r.errors?.length ?? 0)
  // dicefest-импортёры пишут счётчик отдельно
  const skip = r.skipped_fresh ?? 0
  return { ok, fail, skip }
}
