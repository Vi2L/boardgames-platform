/**
 * AnalyticsTab — БД parsers: latency-перцентили, топ-запросы, тихие
 * сбои (empty responses).
 *
 * Это MVP: 3 ключевые секции из 9 возможных. Остальные виджеты
 * (timeline, latency-histogram, parser-breakdown) живут на parsers
 * /dashboard и могут быть добавлены сюда позже.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Activity, AlertCircle, TrendingUp, Info, RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import {
  fetchParsersTopQueries, fetchParsersLatency, fetchParsersEmptyResponses,
} from '../../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../../lib/stores'

const HOURS_OPTIONS = [1, 6, 24, 72, 168]

export function AnalyticsTab() {
  const [hours, setHours] = useState(24)
  const queryClient = useQueryClient()

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

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'latency'] })
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'top-queries'] })
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'empty'] })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-gray-950/40 border border-gray-800 text-xs text-gray-400">
        <Info size={13} className="text-violet-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <strong className="text-gray-300">Аналитика API парсеров.</strong>
          {' '}<strong>Latency</strong> — перцентили времени поиска (p50 — медиана, p99 — 1% самых медленных).
          {' '}<strong>Top запросов</strong> — что чаще всего ищут (полезно для прогрева кеша).
          {' '}<strong>Тихие сбои</strong> — парсер вернул success, но 0 товаров — значит, на сайте магазина что-то изменилось.
          {' '}Все цифры — из таблицы request_log/parser_log БД parsers.
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-800 hover:bg-gray-700 text-gray-200"
          title="Перезагрузить все 3 секции"
        >
          <RefreshCw size={11} /> Обновить
        </button>
      </div>

      <div className="flex items-center gap-2 text-xs">
        <span className="text-gray-500" title="Окно времени для всех агрегатов ниже">Окно:</span>
        {HOURS_OPTIONS.map(h => (
          <button
            key={h}
            type="button"
            onClick={() => setHours(h)}
            title={`Показывать данные за последние ${h < 24 ? `${h} час(ов)` : `${h / 24} дн.`}`}
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
            <Stat label="p50" value={fmtMs(latency.data.p50)} color="emerald"
                  tooltip="Медиана: 50% запросов укладываются в это время" />
            <Stat label="p95" value={fmtMs(latency.data.p95)} color="amber"
                  tooltip="95% запросов быстрее этого значения" />
            <Stat label="p99" value={fmtMs(latency.data.p99)} color="red"
                  tooltip="99% запросов быстрее этого значения — хвост распределения" />
            <Stat label="max" value={fmtMs(latency.data.max)} color="red"
                  tooltip="Максимально зафиксированная задержка" />
            <Stat label={`всего N=${latency.data.count}`}
                  value={fmtMs(latency.data.avg)} color="gray" hint="avg"
                  tooltip="Среднее арифметическое; может скрывать хвост — смотри p95/p99" />
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
                  <th className="px-3 py-2 text-right" title="Сколько раз запрос приходил за окно">count</th>
                  <th className="px-3 py-2 text-right" title="Доля попаданий в кеш — высокий % значит экономия HTTP к магазинам">cache hit</th>
                  <th className="px-3 py-2 text-right" title="Сколько раз парсер вернул ошибку для этого запроса">err</th>
                  <th className="px-3 py-2 text-right" title="Среднее время /search для этого запроса">avg ms</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {top.data.map((qr, i) => (
                  <tr key={`${qr.query}-${i}`} className="hover:bg-gray-850">
                    <td className="px-3 py-2 text-gray-200 truncate max-w-md" title={qr.query}>{qr.query}</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-300">{qr.count}</td>
                    <td
                      className={clsx('px-3 py-2 text-right font-mono',
                        qr.cache_hit_rate >= 50 ? 'text-emerald-400'
                        : qr.cache_hit_rate > 0 ? 'text-amber-400'
                        : 'text-gray-500')}
                      title={`${qr.cache_hits} из ${qr.count} попаданий в кеш`}
                    >
                      {qr.cache_hit_rate.toFixed(0)}%
                    </td>
                    <td className={clsx('px-3 py-2 text-right font-mono', qr.errors > 0 ? 'text-red-400' : 'text-gray-600')}>
                      {qr.errors}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-gray-500">{fmtMs(qr.avg_ms)}</td>
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
  label, value, color, hint, tooltip,
}: {
  label: string
  value: string
  color: 'emerald' | 'amber' | 'red' | 'gray'
  hint?: string
  tooltip?: string
}) {
  const cls: Record<string, string> = {
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    red: 'text-red-400',
    gray: 'text-gray-300',
  }
  return (
    <div className="bg-gray-950 border border-gray-800 rounded p-3" title={tooltip}>
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
