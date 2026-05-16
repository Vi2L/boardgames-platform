/**
 * HealthCard — компактная 200×140 карточка для /status и подсхем (ML, Ollama).
 *
 * Содержит:
 *   - name + sub (имя и тип)
 *   - StatusDot + label из status-system
 *   - details: 3 строки key→value (uptime, failures, last check)
 *   - optional sparkline (последние N значений)
 *
 * `onClick` открывает detail-modal / историю.
 */
import { useId, type MouseEvent } from 'react'
import clsx from 'clsx'

import { StatusDot } from './StatusDot'
import { statusSystem, type StatusKey } from '../../lib/design-tokens'

export interface HealthCardProps {
  name: string
  sub?: string
  status: StatusKey
  details?: Array<string | { label: string; value: string }>
  /** Числовые точки для inline-sparkline (0..1 или абсолютные — мы нормализуем). */
  sparkline?: number[]
  onClick?: (e: MouseEvent<HTMLDivElement>) => void
  className?: string
}

function Sparkline({ values, tone }: { values: number[]; tone: string }) {
  if (values.length === 0) return null
  const id = useId().replace(/:/g, '')
  const w = 168
  const h = 20
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const range = max - min || 1
  const step = values.length > 1 ? w / (values.length - 1) : 0
  const points = values
    .map((v, i) => {
      const x = i * step
      const y = h - ((v - min) / range) * h
      return `${x},${y}`
    })
    .join(' ')

  return (
    <svg width={w} height={h} className="overflow-visible">
      <defs>
        <linearGradient id={`sl-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.4" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className={tone}
      />
      <polygon
        points={`0,${h} ${points} ${w},${h}`}
        fill={`url(#sl-${id})`}
        className={tone}
      />
    </svg>
  )
}

const TONE_TEXT: Record<string, string> = {
  ok: 'text-emerald-400',
  warn: 'text-amber-400',
  danger: 'text-rose-400',
  info: 'text-indigo-400',
  neutral: 'text-zinc-500',
}

export function HealthCard({
  name, sub, status, details, sparkline, onClick, className,
}: HealthCardProps) {
  const ss = statusSystem[status]
  const toneCls = TONE_TEXT[ss.tone] ?? 'text-zinc-500'

  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={(e) => {
        if (!onClick) return
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick(e as unknown as MouseEvent<HTMLDivElement>)
        }
      }}
      className={clsx(
        'w-[200px] h-[140px] flex flex-col',
        'bg-zinc-900 border border-zinc-800 rounded-lg p-3',
        'transition-colors',
        onClick && 'cursor-pointer hover:border-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
        className,
      )}
    >
      <header className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-mono text-zinc-100 truncate">{name}</div>
          {sub && <div className="text-xxs text-zinc-500 mt-0.5 truncate">{sub}</div>}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <StatusDot status={status} animated={ss.tone === 'info' || ss.tone === 'warn'} />
          <span className={clsx('text-xxs font-mono uppercase tracking-wider', toneCls)}>
            {ss.label}
          </span>
        </div>
      </header>

      {details && details.length > 0 && (
        <ul className="space-y-0.5 text-xxs flex-1">
          {details.slice(0, 3).map((d, i) => {
            if (typeof d === 'string') {
              return <li key={i} className="text-zinc-400 truncate">{d}</li>
            }
            return (
              <li key={i} className="flex items-center justify-between gap-2 text-zinc-400">
                <span className="text-zinc-500 truncate">{d.label}</span>
                <span className="font-mono tabular-nums">{d.value}</span>
              </li>
            )
          })}
        </ul>
      )}

      {sparkline && sparkline.length > 0 && (
        <div className={clsx('mt-1 -mx-1', toneCls)}>
          <Sparkline values={sparkline} tone={toneCls} />
        </div>
      )}
    </div>
  )
}
