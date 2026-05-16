/**
 * CircuitStateBadge — визуальный индикатор состояния Circuit Breaker для ML-модели.
 *
 * Три состояния (из catalog.matching.v2.health.OllamaHealth):
 *   - closed    — модель отвечает, обычная работа. Зелёный pulse-dot.
 *   - half_open — модель упала, прошёл recovery_timeout (60с) → следующий
 *                 запрос будет probe. Жёлтый, faster pulse — сигнал «в моменте».
 *   - open      — open-state без пробы. Красный, **без** пульсации — оператор
 *                 видит «alert»-состояние, не моргающее, а константное.
 *
 * Используется в header /matching и в ControlTab → ML-модели карточке.
 */
import clsx from 'clsx'

export type CircuitState = 'closed' | 'half_open' | 'open' | 'unknown'

interface CircuitStateBadgeProps {
  state: CircuitState
  /** компактный inline-режим: только dot + 1 слово */
  compact?: boolean
  /** имя модели, отображается после dot если не compact */
  label?: string
  className?: string
}

const STATE_CONFIG: Record<CircuitState, { dot: string; pulse: string; pill: string; label: string }> = {
  closed: {
    dot: 'bg-green-400',
    pulse: 'animate-pulse',
    pill: 'bg-green-900/30 text-green-300 border-green-800/50',
    label: 'closed',
  },
  half_open: {
    // tailwind animate-pulse — 2s. Чуть быстрее достигается через duration override
    // на конкретный класс — но для простоты используем стандартный pulse.
    dot: 'bg-amber-400',
    pulse: 'animate-pulse',
    pill: 'bg-amber-900/30 text-amber-300 border-amber-800/50',
    label: 'half-open',
  },
  open: {
    // без pulse — alert-состояние должно быть «застывшим», глаз цепляется сильнее.
    dot: 'bg-red-500',
    pulse: '',
    pill: 'bg-red-950/40 text-red-300 border-red-900/50',
    label: 'open',
  },
  unknown: {
    dot: 'bg-gray-600',
    pulse: '',
    pill: 'bg-gray-800/50 text-gray-500 border-gray-700/50',
    label: '?',
  },
}

export function CircuitStateBadge({ state, compact, label, className }: CircuitStateBadgeProps) {
  const cfg = STATE_CONFIG[state]
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 font-mono',
        compact ? 'text-[10px]' : 'text-[11px]',
        compact ? '' : 'border rounded px-2 py-0.5',
        compact ? '' : cfg.pill,
        className,
      )}
    >
      <span className="relative flex items-center">
        <span className={clsx('block w-2 h-2 rounded-full', cfg.dot, cfg.pulse)} />
      </span>
      {label && <span className="text-gray-400">{label}</span>}
      <span className="uppercase tracking-wider">{cfg.label}</span>
    </span>
  )
}
