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
import { RefreshCw, Activity } from 'lucide-react'
import clsx from 'clsx'
import { recordPing, fetchStatusHistory, type PingRecord } from '../lib/api'
import { Button, IconButton, StatusDot } from '../components/ui'

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
    <div className="p-4 max-w-4xl mx-auto space-y-6">
      <Header latest={latest} isPinging={ping.isPending} onPing={() => ping.mutate()} />

      {/* Window selector — сегментированный switch */}
      <div className="flex items-center gap-1">
        <span className="text-xs text-zinc-500 mr-2">Период:</span>
        {WINDOWS.map(w => (
          <Button
            key={w.hours}
            size="xs"
            variant={hours === w.hours ? 'primary' : 'ghost'}
            onClick={() => setHours(w.hours)}
          >
            {w.label}
          </Button>
        ))}
        <span className="ml-auto text-xs text-zinc-600 font-mono tabular-nums">
          {items.length} точек
        </span>
      </div>

      {history.isLoading && (
        <div className="text-center py-12 text-zinc-500 text-sm">Загрузка…</div>
      )}

      {items.length === 0 && !history.isLoading && (
        <div className="text-center py-12 text-zinc-500 text-sm">
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
        <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
          <Activity size={18} className="text-indigo-400" />
          Статус сервисов
        </h1>
        {latest && (
          <p className="text-xs text-zinc-500 mt-0.5">
            Последний пинг:{' '}
            {new Date(latest.checked_at).toLocaleString('ru-RU', { hour12: false })}
          </p>
        )}
      </div>

      <div className="flex items-center gap-4">
        {latest && (
          <div className="flex items-center gap-3">
            <ServiceLabel name="parsers" status={latest.parsers_status} />
            <ServiceLabel name="catalog" status={latest.catalog_status} />
          </div>
        )}
        <IconButton
          icon={RefreshCw}
          variant="ghost"
          size="sm"
          aria-label="Пинговать сейчас"
          title="Пинговать сейчас"
          loading={isPinging}
          onClick={onPing}
        />
      </div>
    </div>
  )
}

function ServiceLabel({ name, status }: { name: string; status: string }) {
  const ok = status === 'ok'
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <StatusDot status={ok ? 'done' : 'failed'} />
      <span className={ok ? 'text-emerald-300' : 'text-rose-300'}>{name}</span>
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
      <h2 className="text-sm font-semibold text-zinc-300 mb-3">
        Unmatched offers
      </h2>
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={points} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="gradUnmatched" x1="0" y1="0" x2="0" y2="1">
              {/* indigo-500 — accent design-tokens */}
              <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gradGood" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#10b981" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
          <XAxis dataKey="ts" tick={{ fill: '#71717a', fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis tick={{ fill: '#71717a', fontSize: 10 }} width={40} allowDecimals={false} />
          <Tooltip
            contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: '#a1a1aa' }}
            formatter={(v: number, name: string) => [
              v?.toLocaleString('ru-RU') ?? '—',
              name === 'unmatched' ? 'Unmatched' : 'Good (≥0.6)',
            ]}
          />
          <Legend
            formatter={(v) => v === 'unmatched' ? 'Unmatched' : 'Good (≥0.6)'}
            wrapperStyle={{ fontSize: 11, color: '#a1a1aa' }}
          />
          <Area
            type="monotone"
            dataKey="unmatched"
            stroke="#6366f1"
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
      <h2 className="text-sm font-semibold text-zinc-300 mb-3">
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
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
          <XAxis dataKey="ts" tick={{ fill: '#71717a', fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis
            tick={{ fill: '#71717a', fontSize: 10 }}
            width={55}
            allowDecimals={false}
            tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)}
          />
          <Tooltip
            contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: '#a1a1aa' }}
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
      <h2 className="text-sm font-semibold text-zinc-300 mb-3">
        Лента событий{' '}
        <span className="text-zinc-600 font-normal text-xs">(последние {items.length})</span>
      </h2>
      <div className="border border-zinc-800 rounded overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-zinc-900 border-b border-zinc-800 text-zinc-400">
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
              <tr key={p.id} className="border-b border-zinc-800 last:border-0 hover:bg-zinc-800/30">
                <td className="px-3 py-1.5 text-zinc-400 font-mono whitespace-nowrap">
                  {new Date(p.checked_at).toLocaleString('ru-RU', {
                    month: '2-digit', day: '2-digit',
                    hour: '2-digit', minute: '2-digit',
                    hour12: false,
                  })}
                </td>
                <td className="px-3 py-1.5 text-center">
                  <TimelineDot status={p.parsers_status} error={p.parsers_error} />
                </td>
                <td className="px-3 py-1.5 text-center">
                  <TimelineDot status={p.catalog_status} error={p.catalog_error} />
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                  {p.unmatched_offers?.toLocaleString('ru-RU') ?? '—'}
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-emerald-400">
                  {p.unmatched_good != null && p.unmatched_good > 0
                    ? p.unmatched_good.toLocaleString('ru-RU')
                    : <span className="text-zinc-600">—</span>}
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-zinc-400">
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

function TimelineDot({ status, error }: { status: string; error?: string | null }) {
  const ok = status === 'ok'
  return (
    <span title={error ?? status} className="inline-flex justify-center">
      <span className={clsx(
        'inline-block w-2 h-2 rounded-full',
        ok ? 'bg-emerald-500' : 'bg-rose-500',
      )} />
    </span>
  )
}
