import clsx from 'clsx'

/**
 * Бейдж tier'а матчинга для отображения в очереди и журнале.
 *
 * Цвета по tier'у:
 *   T0 (cache)    — серый: дешёвый instant lookup
 *   T1 (trgm)     — синий: pg_trgm 0.92+
 *   T2 (vector)   — фиолетовый: bge-m3 0.85+
 *   T3 (LLM)      — оранжевый: qwen2.5 арбитр
 *   manual        — зелёный: оператор подтвердил
 *
 * Reason — короткое объяснение под бейджем (если есть).
 */
interface Props {
  tier: number | null | undefined
  reason?: string | null
  compact?: boolean
}

const TIER_INFO: Record<string, { label: string; bg: string; fg: string }> = {
  '0': { label: 'T0 cache', bg: 'bg-gray-800', fg: 'text-gray-300' },
  '1': { label: 'T1 trgm',  bg: 'bg-blue-900/50', fg: 'text-blue-300' },
  '2': { label: 'T2 vec',   bg: 'bg-indigo-900/50', fg: 'text-indigo-300' },
  '3': { label: 'T3 llm',   bg: 'bg-amber-900/50', fg: 'text-amber-300' },
  manual: { label: 'manual', bg: 'bg-emerald-900/50', fg: 'text-emerald-300' },
}

export function TierBadge({ tier, reason, compact = false }: Props) {
  const key = tier == null ? null : String(tier)
  const info = key && TIER_INFO[key] ? TIER_INFO[key] : null
  if (!info) {
    return <span className="text-xs text-gray-600 font-mono">—</span>
  }
  return (
    <div className="inline-flex flex-col gap-0.5">
      <span
        className={clsx(
          'inline-flex items-center text-[10px] px-1.5 py-0.5 rounded font-mono uppercase',
          info.bg, info.fg,
        )}
      >
        {info.label}
      </span>
      {!compact && reason && (
        <span className="text-[10px] text-gray-500 font-mono truncate max-w-[140px]" title={reason}>
          {reason}
        </span>
      )}
    </div>
  )
}
