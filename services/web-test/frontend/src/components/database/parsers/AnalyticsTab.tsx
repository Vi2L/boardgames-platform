/**
 * AnalyticsTab — БД parsers: latency-перцентили, топ-запросы, тихие
 * сбои (empty responses).
 *
 * Это MVP: 3 ключевые секции из 9 возможных. Остальные виджеты
 * (timeline, latency-histogram, parser-breakdown) живут на parsers
 * /dashboard и могут быть добавлены сюда позже.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Activity, AlertCircle, TrendingUp } from 'lucide-react'
import clsx from 'clsx'
import {
  fetchParsersTopQueries, fetchParsersLatency, fetchParsersEmptyResponses,
} from '../../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../../lib/stores'

const HOURS_OPTIONS = [1, 6, 24, 72, 168]

export function AnalyticsTab() {
  const [hours, setHours] = useState(24)

  const latency = useQuery({
    queryKey: ['parsers-db', 'latency', hours],
    queryFn: () => fetchParsersLatency(hours),
  })
  const top = useQuery({
    queryKey: ['parsers-db', 'top-queries', hours],
    queryFn: () => fetchParsersTopQueries(hours, 20),
  })
  const empty = useQuery({
    queryKey: ['parsers-db', 'empty', hours],
    queryFn: () => fetchParsersEmptyResponses(hours, 50),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-xs">
        <span className="text-gray-500">Окно:</span>
        {HOURS_OPTIONS.map(h => (
          <button
            key={h}
            type="button"
            onClick={() => setHours(h)}
            className={clsx(
              'px-2 py-0.5 rounded',
              hours === h ? 'bg-violet-900/60 text-violet-200'
                          : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
            )}
          >
            {h < 24 ? `${h}ч` : `${h / 24}д`}
          </button>
        ))}
      </div>

      {/* Latency percentiles */}
      <Section title="Latency перцентили" icon={<Activity size={14} />}>
        {latency.isLoading ? (
          <Loader />
        ) : latency.data ? (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <Stat label="p50" value={fmtMs(latency.data.p50)} color="emerald" />
            <Stat label="p95" value={fmtMs(latency.data.p95)} color="amber" />
            <Stat label="p99" value={fmtMs(latency.data.p99)} color="red" />
            <Stat label="max" value={fmtMs(latency.data.max)} color="red" />
            <Stat label={`всего N=${latency.data.count}`}
                  value={fmtMs(latency.data.avg)} color="gray" hint="avg" />
          </div>
        ) : (
          <Empty />
        )}
      </Section>

      {/* Top queries */}
      <Section title="Топ запросов" icon={<TrendingUp size={14} />}>
        {top.isLoading ? (
          <Loader />
        ) : (top.data && top.data.length > 0) ? (
          <div className="bg-gray-900 border border-gray-800 rounded overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-gray-950 text-gray-500 text-left">
                <tr>
                  <th className="px-3 py-2">запрос</th>
                  <th className="px-3 py-2 text-right">hits</th>
                  <th className="px-3 py-2 text-right">avg ms</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {top.data.map((q, i) => (
                  <tr key={`${q.query}-${i}`} className="hover:bg-gray-850">
                    <td className="px-3 py-2 text-gray-200 truncate max-w-md" title={q.query}>{q.query}</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-300">{q.hits}</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-500">{fmtMs(q.avg_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty />
        )}
      </Section>

      {/* Empty responses (silent failures) */}
      <Section title="Тихие сбои (success, 0 товаров)" icon={<AlertCircle size={14} />}>
        {empty.isLoading ? (
          <Loader />
        ) : (empty.data && empty.data.length > 0) ? (
          <div className="bg-gray-900 border border-gray-800 rounded overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-gray-950 text-gray-500 text-left">
                <tr>
                  <th className="px-3 py-2">время</th>
                  <th className="px-3 py-2">магазин</th>
                  <th className="px-3 py-2">запрос</th>
                  <th className="px-3 py-2 text-right">ms</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {empty.data.map((e, i) => (
                  <tr key={i} className="hover:bg-gray-850">
                    <td className="px-3 py-2 font-mono text-gray-500 whitespace-nowrap">
                      {fmtTs(e.ts)}
                    </td>
                    <td className="px-3 py-2">
                      <span className={clsx('px-1.5 py-0.5 rounded font-mono', getStoreBadgeColor(e.store_slug))}>
                        {getStoreLabel(e.store_slug)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-200 truncate max-w-sm" title={e.query}>
                      {e.query}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-gray-500">{fmtMs(e.duration_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-xs text-emerald-400 bg-emerald-950/20 border border-emerald-900/30 rounded p-3">
            ✓ Тихих сбоев нет за выбранный период.
          </div>
        )}
      </Section>
    </div>
  )
}

function Section({
  title, icon, children,
}: {
  title: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm text-gray-300">
        {icon} <span className="font-medium">{title}</span>
      </div>
      {children}
    </div>
  )
}

function Stat({
  label, value, color, hint,
}: {
  label: string
  value: string
  color: 'emerald' | 'amber' | 'red' | 'gray'
  hint?: string
}) {
  const cls: Record<string, string> = {
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    red: 'text-red-400',
    gray: 'text-gray-300',
  }
  return (
    <div className="bg-gray-950 border border-gray-800 rounded p-3">
      <div className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={clsx('text-lg font-mono', cls[color])}>{value}</div>
      {hint && <div className="text-[10px] text-gray-500 mt-0.5">{hint}</div>}
    </div>
  )
}

function Loader() {
  return <div className="flex items-center justify-center py-6 text-gray-500"><Loader2 size={14} className="animate-spin" /></div>
}
function Empty() {
  return <div className="text-xs text-gray-500 italic py-3">Данных нет за выбранный период.</div>
}
function fmtMs(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${Math.round(v)} ms`
}
function fmtTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString('ru-RU', { hour12: false }).replace(',', '')
  } catch { return iso }
}
