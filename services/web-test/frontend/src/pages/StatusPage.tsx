/**
 * StatusPage — /status
 *
 * История пингов обоих сервисов для ретроспектив:
 * - График unmatched_offers во времени (основная метрика)
 * - График total_games (вторичная ось)
 * - Timeline-лента статусов parsers / catalog
 * - Текущий статус (последний пинг)
 *
 * Auto-ping при входе + каждые 30 сек (=записывает точку в ping_history).
 * Window selector: 1h / 6h / 24h / 7d.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AreaChart, Area,
  XAxis, YAxis,
  CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import { CheckCircle2, XCircle, RefreshCw, Activity } from 'lucide-react'
import clsx from 'clsx'
import { recordPing, fetchStatusHistory, type PingRecord } from '../lib/api'

// ── Window options ────────────────────────────────────────────────────────────

const WINDOWS = [
  { label: '1ч', hours: 1 },
  { label: '6ч', hours: 6 },
  { label: '24ч', hours: 24 },
  { label: '7д', hours: 168 },
] as const

// ── Page ─────────────────────────────────────────────────────────────────────

export function StatusPage() {
  const qc = useQueryClient()
  const [hours, setHours] = useState<number>(24)

  // Ping при входе и каждые 30 сек — записывает точку в ping_history.
  const ping = useMutation({
    mutationFn: recordPing,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['status-history'] })
    },
  })

  useEffect(() => {
    ping.mutate()
    const interval = setInterval(() => ping.mutate(), 30_000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const history = useQuery({
    queryKey: ['status-history', hours],
    queryFn: () => fetchStatusHistory(hours),
    refetchInterval: 31_000, // чуть больше пинга — подхватывает новую точку
    staleTime: 15_000,
  })

  const items = history.data?.items ?? []
  // Разворачиваем: API отдаёт новые первыми, chart нужен хронологический порядок.
  const chronological = [...items].reverse()

  const latest = items[0] ?? null

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <Header latest={latest} isPinging={ping.isPending} onPing={() => ping.mutate()} />

      {/* Window selector */}
      <div className="flex items-center gap-1">
        <span className="text-xs text-gray-500 mr-2">Период:</span>
        {WINDOWS.map(w => (
          <button
            key={w.hours}
            type="button"
            onClick={() => setHours(w.hours)}
            className={clsx(
              'px-2.5 py-1 text-xs rounded',
              hours === w.hours
                ? 'bg-violet-700 text-white'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
            )}
          >
            {w.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-600">
          {items.length} точек
        </span>
      </div>

      {history.isLoading && (
        <div className="text-center py-12 text-gray-500 text-sm">Загрузка…</div>
      )}

      {items.length === 0 && !history.isLoading && (
        <div className="text-center py-12 text-gray-500 text-sm">
          Пока нет данных за этот период. Оставайтесь на странице — данные накапливаются.
        </div>
      )}

      {chronological.length > 0 && (
        <>
          <UnmatchedChart data={chronological} />
          <GamesChart data={chronological} />
          <StatusTimeline items={items.slice(0, 120)} />
        </>
      )}
    </div>
  )
}

// ── Header ────────────────────────────────────────────────────────────────────

function Header({
  latest, isPinging, onPing,
}: {
  latest: PingRecord | null
  isPinging: boolean
  onPing: () => void
}) {
  return (
    <div className="flex items-start justify-between">
      <div>
        <h1 className="text-lg font-semibold text-gray-100 flex items-center gap-2">
          <Activity size={18} className="text-violet-400" />
          Статус сервисов
        </h1>
        {latest && (
          <p className="text-xs text-gray-500 mt-0.5">
            Последний пинг:{' '}
            {new Date(latest.checked_at).toLocaleString('ru-RU', { hour12: false })}
          </p>
        )}
      </div>

      <div className="flex items-center gap-4">
        {latest && (
          <div className="flex items-center gap-3">
            <ServiceDot name="parsers" status={latest.parsers_status} />
            <ServiceDot name="catalog" status={latest.catalog_status} />
          </div>
        )}
        <button
          type="button"
          onClick={onPing}
          disabled={isPinging}
          title="Пинговать сейчас"
          className="p-1.5 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-800 disabled:opacity-50"
        >
          <RefreshCw size={14} className={isPinging ? 'animate-spin' : ''} />
        </button>
      </div>
    </div>
  )
}

function ServiceDot({ name, status }: { name: string; status: string }) {
  const ok = status === 'ok'
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {ok
        ? <CheckCircle2 size={13} className="text-green-400" />
        : <XCircle size={13} className="text-red-400" />}
      <span className={ok ? 'text-green-400' : 'text-red-400'}>{name}</span>
    </div>
  )
}

// ── Charts ────────────────────────────────────────────────────────────────────

type ChartPoint = {
  ts: string        // ось X
  unmatched: number | null
  good: number | null
  games: number | null
  parsers_ok: 0 | 1
  catalog_ok: 0 | 1
}

function toChartPoints(items: PingRecord[]): ChartPoint[] {
  return items.map(p => ({
    ts: fmtTs(p.checked_at),
    unmatched: p.unmatched_offers,
    good: p.unmatched_good,
    games: p.total_games,
    parsers_ok: p.parsers_status === 'ok' ? 1 : 0,
    catalog_ok: p.catalog_status === 'ok' ? 1 : 0,
  }))
}

function fmtTs(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function UnmatchedChart({ data }: { data: PingRecord[] }) {
  const points = toChartPoints(data)

  return (
    <section>
      <h2 className="text-sm font-semibold text-gray-300 mb-3">
        Unmatched offers
      </h2>
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={points} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="gradUnmatched" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#7c3aed" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#7c3aed" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gradGood" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#10b981" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="ts" tick={{ fill: '#6b7280', fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} width={40} allowDecimals={false} />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: '#9ca3af' }}
            formatter={(v: number, name: string) => [
              v?.toLocaleString('ru-RU') ?? '—',
              name === 'unmatched' ? 'Unmatched' : 'Good (≥0.6)',
            ]}
          />
          <Legend
            formatter={(v) => v === 'unmatched' ? 'Unmatched' : 'Good (≥0.6)'}
            wrapperStyle={{ fontSize: 11, color: '#9ca3af' }}
          />
          <Area
            type="monotone"
            dataKey="unmatched"
            stroke="#7c3aed"
            strokeWidth={2}
            fill="url(#gradUnmatched)"
            dot={false}
            connectNulls
          />
          <Area
            type="monotone"
            dataKey="good"
            stroke="#10b981"
            strokeWidth={1.5}
            fill="url(#gradGood)"
            dot={false}
            connectNulls
          />
        </AreaChart>
      </ResponsiveContainer>
    </section>
  )
}

function GamesChart({ data }: { data: PingRecord[] }) {
  const points = toChartPoints(data)
  // Показываем только если данные есть и есть изменения (не статичная горизонталь).
  const hasData = points.some(p => p.games != null)
  if (!hasData) return null

  return (
    <section>
      <h2 className="text-sm font-semibold text-gray-300 mb-3">
        Игры в каталоге
      </h2>
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={points} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="gradGames" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="ts" tick={{ fill: '#6b7280', fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis
            tick={{ fill: '#6b7280', fontSize: 10 }}
            width={55}
            allowDecimals={false}
            tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)}
          />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: '#9ca3af' }}
            formatter={(v: number) => [v?.toLocaleString('ru-RU') ?? '—', 'Игры']}
          />
          <Area
            type="monotone"
            dataKey="games"
            stroke="#3b82f6"
            strokeWidth={2}
            fill="url(#gradGames)"
            dot={false}
            connectNulls
          />
        </AreaChart>
      </ResponsiveContainer>
    </section>
  )
}

// ── Status timeline ───────────────────────────────────────────────────────────

function StatusTimeline({ items }: { items: PingRecord[] }) {
  return (
    <section>
      <h2 className="text-sm font-semibold text-gray-300 mb-3">
        Лента событий{' '}
        <span className="text-gray-600 font-normal text-xs">(последние {items.length})</span>
      </h2>
      <div className="border border-gray-800 rounded overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-900 border-b border-gray-800 text-gray-400">
            <tr>
              <th className="text-left px-3 py-2 font-normal">Время</th>
              <th className="text-center px-3 py-2 font-normal">parsers</th>
              <th className="text-center px-3 py-2 font-normal">catalog</th>
              <th className="text-right px-3 py-2 font-normal">Unmatched</th>
              <th className="text-right px-3 py-2 font-normal">Good</th>
              <th className="text-right px-3 py-2 font-normal">Игры</th>
            </tr>
          </thead>
          <tbody>
            {items.map(p => (
              <tr key={p.id} className="border-b border-gray-800 last:border-0 hover:bg-gray-900/40">
                <td className="px-3 py-1.5 text-gray-400 font-mono whitespace-nowrap">
                  {new Date(p.checked_at).toLocaleString('ru-RU', {
                    month: '2-digit', day: '2-digit',
                    hour: '2-digit', minute: '2-digit',
                    hour12: false,
                  })}
                </td>
                <td className="px-3 py-1.5 text-center">
                  <StatusDot status={p.parsers_status} error={p.parsers_error} />
                </td>
                <td className="px-3 py-1.5 text-center">
                  <StatusDot status={p.catalog_status} error={p.catalog_error} />
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-300">
                  {p.unmatched_offers?.toLocaleString('ru-RU') ?? '—'}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-emerald-400">
                  {p.unmatched_good != null && p.unmatched_good > 0
                    ? p.unmatched_good.toLocaleString('ru-RU')
                    : <span className="text-gray-600">—</span>}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                  {p.total_games?.toLocaleString('ru-RU') ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function StatusDot({ status, error }: { status: string; error?: string | null }) {
  const ok = status === 'ok'
  return (
    <span title={error ?? status} className="inline-flex justify-center">
      <span className={clsx(
        'inline-block w-2 h-2 rounded-full',
        ok ? 'bg-green-500' : 'bg-red-500',
      )} />
    </span>
  )
}
