/**
 * MatchingStatsHeader — сводка очереди матчинга.
 *
 * Показывает: total unmatched, distribution по score-buckets (good /
 * candidate / cold) и breakdown по магазинам с avg score. Помогает
 * понять, где оператору тратить время в первую очередь — где много
 * «good» score, там быстрая ручная проверка превратит unmatched →
 * manual в один клик.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, Layers } from 'lucide-react'
import clsx from 'clsx'
import { fetchMatchingStats } from '../../lib/catalog'
import { getStoreLabel, getStoreBadgeColor } from '../../lib/stores'

export function MatchingStatsHeader() {
  const { data, isLoading } = useQuery({
    queryKey: ['catalog', 'matching-stats'],
    queryFn: fetchMatchingStats,
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded p-3 flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={14} className="animate-spin" /> Загрузка статистики…
      </div>
    )
  }
  if (!data) return null

  const good = data.by_bucket.good ?? 0
  const cand = data.by_bucket.candidate ?? 0
  const cold = data.by_bucket.cold ?? 0
  const total = data.total_unmatched

  return (
    <div className="bg-gray-900 border border-gray-800 rounded p-3 space-y-3">
      <div className="flex items-center gap-3">
        <Layers size={14} className="text-gray-400" />
        <span className="text-sm font-semibold text-gray-100">
          {total.toLocaleString()} unmatched оффер{plural(total)}
        </span>
        <div className="flex items-center gap-2 ml-auto text-xs">
          <Bucket label={`good ≥${data.thresholds.auto.toFixed(2)}`}
                  count={good} color="emerald" />
          <Bucket label={`candidate ${data.thresholds.candidate.toFixed(2)}–${data.thresholds.auto.toFixed(2)}`}
                  count={cand} color="amber" />
          <Bucket label={`cold <${data.thresholds.candidate.toFixed(2)}`}
                  count={cold} color="gray" />
        </div>
      </div>

      {/* Stacked bar by store */}
      {data.by_store.length > 0 && (
        <div className="space-y-1">
          {data.by_store.map(s => (
            <div key={s.store_slug} className="flex items-center gap-2 text-xs">
              <span className={clsx('px-1.5 py-0.5 rounded font-mono w-28 flex-shrink-0', getStoreBadgeColor(s.store_slug))}>
                {getStoreLabel(s.store_slug)}
              </span>
              <div className="flex-1 h-4 bg-gray-950 rounded overflow-hidden">
                <div className="h-full bg-indigo-700"
                     style={{ width: `${total > 0 ? (s.total / total) * 100 : 0}%` }} />
              </div>
              <span className="w-16 text-right font-mono text-gray-300">{s.total}</span>
              <span className="w-20 text-right font-mono text-gray-500"
                    title="avg score">
                avg {s.avg_score != null ? s.avg_score.toFixed(2) : '—'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Bucket({
  label, count, color,
}: {
  label: string
  count: number
  color: 'emerald' | 'amber' | 'gray'
}) {
  const cls: Record<string, string> = {
    emerald: 'bg-emerald-900/40 text-emerald-200',
    amber:   'bg-amber-900/40 text-amber-200',
    gray:    'bg-gray-800 text-gray-400',
  }
  return (
    <span className={`px-2 py-0.5 rounded font-mono ${cls[color]}`} title={label}>
      {count.toLocaleString()}
    </span>
  )
}

function plural(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return 'а'
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) return 'а'
  return 'ов'
}
