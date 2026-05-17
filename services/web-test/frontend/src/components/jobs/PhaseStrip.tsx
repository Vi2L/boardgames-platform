/**
 * PhaseStrip — горизонтальные phase pills для long-running job'ов.
 *
 * Спека: `pages/04-jobui.md` § Phase pills.
 *
 *   done    → emerald-tone   (`bg-emerald-500/10 text-emerald-300`)
 *   current → indigo-tone    (+ pulse-dot)
 *   pending → neutral-tone   (`bg-zinc-900 text-zinc-500`)
 *
 * Если phases unknown — рендерим только current в одном pill.
 */
import { ChevronRight } from 'lucide-react'
import { Fragment } from 'react'

export interface PhaseStripProps {
  /** Известные phases в порядке выполнения. Если undefined — рендерим только current. */
  phases?: string[]
  current?: string | null
  className?: string
}

export function PhaseStrip({ phases, current, className }: PhaseStripProps) {
  if (!phases || phases.length === 0) {
    return current ? (
      <div className={className}>
        <PhasePill state="current" label={current} />
      </div>
    ) : null
  }

  const currentIdx = current ? phases.indexOf(current) : -1

  return (
    <div className={`flex items-center gap-1 flex-wrap ${className ?? ''}`}>
      {phases.map((phase, i) => {
        const state: PhaseState =
          currentIdx === -1 ? 'pending' :
          i < currentIdx ? 'done' :
          i === currentIdx ? 'current' :
          'pending'
        return (
          <Fragment key={phase}>
            <PhasePill state={state} label={phase} />
            {i < phases.length - 1 && (
              <ChevronRight size={12} className="text-zinc-700" />
            )}
          </Fragment>
        )
      })}
    </div>
  )
}

type PhaseState = 'done' | 'current' | 'pending'

function PhasePill({ state, label }: { state: PhaseState; label: string }) {
  const cls =
    state === 'done'    ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' :
    state === 'current' ? 'bg-indigo-500/15 text-indigo-200 border-indigo-500/30' :
                          'bg-zinc-900 text-zinc-500 border-zinc-800'

  return (
    <span className={`inline-flex items-center gap-1.5 h-6 px-2 text-xxs font-mono uppercase tracking-wider border rounded ${cls}`}>
      {state === 'current' && (
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
      )}
      {label}
    </span>
  )
}
