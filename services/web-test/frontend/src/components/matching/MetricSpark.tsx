/**
 * MetricSpark — тонкая sparkline + опциональный label / min-max аннотации.
 *
 * Использование в `/matching`:
 *   - Header: queue-depth 24h
 *   - ControlTab: latency per-model, worker throughput
 *
 * Inline SVG без recharts (тяжёлая dep для одного маленького элемента).
 * Цвет берётся от tone — соответствует системе из status-system.md.
 */
import { useId } from 'react'
import clsx from 'clsx'

export interface MetricSparkProps {
  /** Численная серия. Пустой массив → ничего не рендерится (return null). */
  values: number[]
  width?: number
  height?: number
  /** tone определяет цвет линии + градиент-заливку. */
  tone?: 'info' | 'ok' | 'warn' | 'danger' | 'neutral'
  /** Опциональный label слева (например `min 120 · peak 251 · now 124`). */
  label?: string
  /** Showmin/max/now annotations. */
  showAnnotations?: boolean
  className?: string
}

const TONE_COLOR: Record<string, string> = {
  info: '#818cf8',     // indigo-400
  ok: '#34d399',       // emerald-400
  warn: '#fbbf24',     // amber-400
  danger: '#fb7185',   // rose-400
  neutral: '#a1a1aa',  // zinc-400
}

const TONE_TEXT: Record<string, string> = {
  info: 'text-indigo-300',
  ok: 'text-emerald-300',
  warn: 'text-amber-300',
  danger: 'text-rose-300',
  neutral: 'text-zinc-400',
}

export function MetricSpark({
  values, width = 120, height = 28, tone = 'info',
  label, showAnnotations = false, className,
}: MetricSparkProps) {
  const id = useId().replace(/:/g, '')
  if (values.length === 0) {
    return (
      <div className={clsx('flex items-center gap-2 text-xxs text-zinc-600 font-mono', className)}>
        <span style={{ width, height }} className="border border-dashed border-zinc-800 rounded flex items-center justify-center">
          no data
        </span>
        {label && <span>{label}</span>}
      </div>
    )
  }

  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const range = max - min || 1
  const step = values.length > 1 ? width / (values.length - 1) : 0
  const points = values
    .map((v, i) => `${i * step},${height - ((v - min) / range) * height}`)
    .join(' ')

  const color = TONE_COLOR[tone]
  const textColor = TONE_TEXT[tone]

  return (
    <div className={clsx('flex items-center gap-2', className)}>
      <svg width={width} height={height} className="overflow-visible flex-shrink-0">
        <defs>
          <linearGradient id={`spark-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.35" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon
          points={`0,${height} ${points} ${width},${height}`}
          fill={`url(#spark-${id})`}
        />
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
        />
      </svg>
      {showAnnotations && (
        <div className={clsx('text-xxs font-mono tabular-nums', textColor)}>
          <div>peak {Math.round(max)}</div>
          <div className="opacity-70">now {Math.round(values[values.length - 1])}</div>
        </div>
      )}
      {label && (
        <span className="text-xxs font-mono text-zinc-500">{label}</span>
      )}
    </div>
  )
}
