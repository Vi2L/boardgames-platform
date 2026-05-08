import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, Cell,
} from 'recharts'
import { BarChart2, TrendingUp, PieChart, Cpu, Key, Loader2, RefreshCw, Info } from 'lucide-react'
import clsx from 'clsx'
import {
  fetchParsersTimeline, fetchParsersLatencyHistogram, fetchParsersStoreDistribution,
  fetchParsersParserBreakdown, fetchParsersRawKeys,
} from '../../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../../lib/stores'

const HOURS_OPTIONS = [6, 24, 72, 168] as const

/** Hex-цвета для Recharts (Tailwind-классы там не работают). */
const STORE_HEX: Record<string, string> = {
  hobbygames: '#60a5fa',   // blue-400
  lavkaigr:   '#4ade80',   // green-400
  gaga:       '#fb923c',   // orange-400
  crowdgames: '#c084fc',   // purple-400
}
function storeHex(slug: string): string { return STORE_HEX[slug] ?? '#9ca3af' }

export function ChartsTab() {
  const [hours, setHours] = useState(24)
  const [bucket, setBucket] = useState<'hour' | 'day'>('hour')
  const [topN, setTopN] = useState(10)
  const queryClient = useQueryClient()

  const timeline = useQuery({
    queryKey: ['parsers-db', 'timeline', bucket, hours],
    queryFn: () => fetchParsersTimeline(bucket, hours),
  })
  const histogram = useQuery({
    queryKey: ['parsers-db', 'latency-histogram', hours],
    queryFn: () => fetchParsersLatencyHistogram(hours),
  })
  const distribution = useQuery({
    queryKey: ['parsers-db', 'store-distribution', hours],
    queryFn: () => fetchParsersStoreDistribution(hours),
  })
  const breakdown = useQuery({
    queryKey: ['parsers-db', 'parser-breakdown'],
    queryFn: fetchParsersParserBreakdown,
  })
  const rawKeys = useQuery({
    queryKey: ['parsers-db', 'raw-keys', topN],
    queryFn: () => fetchParsersRawKeys(topN),
  })

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'timeline'] })
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'latency-histogram'] })
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'store-distribution'] })
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'parser-breakdown'] })
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'raw-keys'] })
  }

  return (
    <div className="space-y-6">
      {/* Шапка */}
      <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-gray-950/40 border border-gray-800 text-xs text-gray-400">
        <Info size={13} className="text-violet-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <strong className="text-gray-300">Графики активности парсеров.</strong>
          {' '}<strong>Timeline</strong> — история запросов по cache/network/partial.
          {' '}<strong>Latency</strong> — распределение по бинам.
          {' '}<strong>Нагрузка</strong> — доли вызовов по магазинам.
          {' '}<strong>Search vs Enrich</strong> — разбивка latency парсера на фазы.
          {' '}<strong>Raw-ключи</strong> — что парсеры кладут в <code>extra</code>.
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 whitespace-nowrap"
          title="Перезагрузить все секции"
        >
          <RefreshCw size={11} /> Обновить
        </button>
      </div>

      {/* Общие фильтры (для time-based секций) */}
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <div className="flex items-center gap-1.5">
          <span className="text-gray-500">Окно:</span>
          {HOURS_OPTIONS.map(h => (
            <button key={h} type="button" onClick={() => setHours(h)}
              className={clsx('px-2 py-0.5 rounded',
                hours === h ? 'bg-violet-900/60 text-violet-200' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800')}
            >
              {h < 24 ? `${h}ч` : `${h / 24}д`}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-gray-500">Бакет:</span>
          {(['hour', 'day'] as const).map(b => (
            <button key={b} type="button" onClick={() => setBucket(b)}
              className={clsx('px-2 py-0.5 rounded',
                bucket === b ? 'bg-violet-900/60 text-violet-200' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800')}
            >
              {b === 'hour' ? 'по часам' : 'по дням'}
            </button>
          ))}
        </div>
      </div>

      {/* ── 1. Timeline ─────────────────────────────────────────────── */}
      <Section
        title="Timeline запросов"
        icon={<BarChart2 size={14} />}
        hint="Распределение запросов /search по источнику ответа за выбранный период. cache — ответ из TTL-кеша parsers (без HTTP к магазинам). network — свежий парсинг хотя бы одного магазина. partial — все магазины упали, вернули устаревший кеш. errors — технические сбои."
      >
        {timeline.isLoading ? <Loader /> : timeline.data && timeline.data.length > 0 ? (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={timeline.data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="ts"
                tickFormatter={ts => fmtTs(ts, bucket)}
                tick={{ fill: '#6b7280', fontSize: 10 }}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} width={28} allowDecimals={false} />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
                labelFormatter={ts => fmtTs(ts as string, bucket)}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />
              <Bar dataKey="cache"   stackId="s" fill="#3b82f6" name="cache" />
              <Bar dataKey="network" stackId="s" fill="#22c55e" name="network" />
              <Bar dataKey="partial" stackId="s" fill="#f59e0b" name="partial" />
              <Bar dataKey="errors"  stackId="s" fill="#ef4444" name="errors" />
            </BarChart>
          </ResponsiveContainer>
        ) : <Empty />}
      </Section>

      {/* ── 2. Latency Histogram ────────────────────────────────────── */}
      <Section
        title="Гистограмма latency /search"
        icon={<TrendingUp size={14} />}
        hint="Сколько запросов /search уложились в каждый временной бин. Большой хвост в «1-3с» или «>3с» указывает на медленные парсеры или rate-limit магазина. Бин «<100мс» — почти всегда cache-hit (HTTP к магазинам не было)."
      >
        {histogram.isLoading ? <Loader /> : histogram.data && histogram.data.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={histogram.data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="bin" tick={{ fill: '#9ca3af', fontSize: 10 }} />
              <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} width={28} allowDecimals={false} />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
                formatter={(v: number) => [v, 'запросов']}
              />
              <Bar dataKey="count" fill="#8b5cf6" name="запросов" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : <Empty />}
      </Section>

      {/* ── 3. Store Distribution ───────────────────────────────────── */}
      <Section
        title="Нагрузка по магазинам"
        icon={<PieChart size={14} />}
        hint="Доля вызовов каждого парсера за выбранный период. В норме ~25% на каждый из 4 магазинов. avg рез. = 0 при большом числе вызовов — признак тихих сбоев: парсер отвечает успешно, но возвращает 0 товаров (сайт магазина изменился)."
      >
        {distribution.isLoading ? <Loader /> : distribution.data && distribution.data.length > 0 ? (
          <div className="space-y-3">
            <ResponsiveContainer width="100%" height={150}>
              <BarChart
                data={distribution.data.map(d => ({ ...d, name: getStoreLabel(d.store_slug) }))}
                layout="vertical"
                margin={{ top: 4, right: 40, left: 72, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#6b7280', fontSize: 10 }} unit="%" />
                <YAxis type="category" dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} width={70} />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
                  formatter={(v: number) => [`${v.toFixed(1)}%`, 'Доля']}
                />
                <Bar dataKey="share_pct" name="Доля" radius={[0, 2, 2, 0]}>
                  {distribution.data.map(d => (
                    <Cell key={d.store_slug} fill={storeHex(d.store_slug)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {distribution.data.map(d => (
                <div key={d.store_slug} className="bg-gray-950 border border-gray-800 rounded p-2 text-xs space-y-1">
                  <div className={clsx('inline-block px-1.5 py-0.5 rounded font-mono', getStoreBadgeColor(d.store_slug))}>
                    {getStoreLabel(d.store_slug)}
                  </div>
                  <div className="text-gray-400 space-y-0.5">
                    <div title="Всего вызовов за выбранный период">
                      вызовов: <span className="text-gray-200 font-mono">{d.calls}</span>
                    </div>
                    <div title="Среднее число товаров в ответе">
                      avg рез.: <span className="text-gray-200 font-mono">{d.avg_results?.toFixed(1) ?? '—'}</span>
                    </div>
                    <div title="Среднее время ответа">
                      avg ms: <span className="text-gray-200 font-mono">{d.avg_ms != null ? Math.round(d.avg_ms) : '—'}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : <Empty />}
      </Section>

      {/* ── 4. Parser Breakdown (Search vs Enrich) ──────────────────── */}
      <Section
        title="Search vs Enrich latency"
        icon={<Cpu size={14} />}
        hint="Разбивка времени вызова парсера на две фазы. search — HTTP-запрос к поисковому endpoint магазина. enrich — параллельный fetch страниц отдельных товаров для обогащения данных (фото, описание, players и т.д.). enrich = «—» означает отсутствие фазы обогащения (CrowdGames — локальный поиск по кешу каталога)."
      >
        {breakdown.isLoading ? <Loader /> : breakdown.data && breakdown.data.length > 0 ? (
          <div className="space-y-3">
            <ResponsiveContainer width="100%" height={180}>
              <BarChart
                data={breakdown.data.map(d => ({
                  name: getStoreLabel(d.store_slug),
                  store_slug: d.store_slug,
                  search: d.avg_search_ms != null ? Math.round(d.avg_search_ms) : 0,
                  enrich: d.avg_enrich_ms != null ? Math.round(d.avg_enrich_ms) : 0,
                }))}
                margin={{ top: 4, right: 8, left: 0, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 10 }} />
                <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} unit=" мс" width={52} />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
                  formatter={(v: number, key: string) => [`${v} мс`, key === 'search' ? 'Search' : 'Enrich']}
                />
                <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />
                <Bar dataKey="search" stackId="b" fill="#6366f1" name="search" />
                <Bar dataKey="enrich" stackId="b" fill="#a78bfa" name="enrich" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            <div className="overflow-x-auto rounded border border-gray-800">
              <table className="w-full text-xs">
                <thead className="bg-gray-950 text-gray-500 text-left">
                  <tr>
                    <th className="px-3 py-2">Магазин</th>
                    <th className="px-3 py-2 text-right" title="Успешных вызовов (is_test=0)">вызовов</th>
                    <th className="px-3 py-2 text-right" title="Среднее время фазы поиска (HTTP к поиску магазина)">search мс</th>
                    <th className="px-3 py-2 text-right" title="Среднее время фазы обогащения (fetch страниц товаров)">enrich мс</th>
                    <th className="px-3 py-2 text-right" title="Итоговое среднее (search + enrich)">total мс</th>
                    <th className="px-3 py-2 text-right" title="Среднее число HTTP-запросов за вызов">HTTP req</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {breakdown.data.map(d => (
                    <tr key={d.store_slug} className="hover:bg-gray-900/40">
                      <td className="px-3 py-2">
                        <span className={clsx('px-1.5 py-0.5 rounded font-mono', getStoreBadgeColor(d.store_slug))}>
                          {getStoreLabel(d.store_slug)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-gray-300">{d.calls}</td>
                      <td className="px-3 py-2 text-right font-mono text-indigo-400">
                        {d.avg_search_ms != null ? Math.round(d.avg_search_ms) : '—'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-violet-400">
                        {d.avg_enrich_ms != null ? Math.round(d.avg_enrich_ms) : '—'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-gray-300">
                        {d.avg_total_ms != null ? Math.round(d.avg_total_ms) : '—'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-gray-500">
                        {d.avg_http_requests != null ? d.avg_http_requests.toFixed(1) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : <Empty />}
      </Section>

      {/* ── 5. Raw Keys ─────────────────────────────────────────────── */}
      <Section
        title="Raw-ключи в extra"
        icon={<Key size={14} />}
        hint="Топ ключей, которые парсеры кладут в поле extra каждого товара. Эти ключи используются для sale-бейджей (on_sale), программ лояльности (original_price, availability), фильтрации наличия (in_stock, availability). Помогает понять, какие данные реально приходят от каждого магазина."
      >
        <div className="flex items-center gap-2 text-xs mb-3">
          <span className="text-gray-500" title="Топ N ключей per-store">Top N:</span>
          {[5, 10, 20].map(n => (
            <button key={n} type="button" onClick={() => setTopN(n)}
              className={clsx('px-2 py-0.5 rounded',
                topN === n ? 'bg-violet-900/60 text-violet-200' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800')}
            >
              {n}
            </button>
          ))}
        </div>
        {rawKeys.isLoading ? <Loader /> : rawKeys.data && rawKeys.data.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {rawKeys.data.map(store => (
              <div key={store.store_slug} className="bg-gray-950/50 border border-gray-800 rounded p-3">
                <div className={clsx('inline-block px-1.5 py-0.5 rounded font-mono text-xs mb-2',
                  getStoreBadgeColor(store.store_slug))}
                >
                  {getStoreLabel(store.store_slug)}
                </div>
                {store.keys.length === 0 ? (
                  <p className="text-xs text-gray-500 italic">нет ключей</p>
                ) : (
                  <div className="space-y-1">
                    {store.keys.map(k => (
                      <div key={k.key} className="flex items-center justify-between text-xs">
                        <span className="font-mono text-amber-300/80">{k.key}</span>
                        <span className="font-mono text-gray-500">{k.count.toLocaleString('ru-RU')}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : <Empty />}
      </Section>
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────

function Section({ title, icon, hint, children }: {
  title: string; icon: React.ReactNode; hint?: string; children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm text-gray-300">
        {icon}
        <span className="font-medium">{title}</span>
        {hint && (
          <span title={hint} className="text-gray-600 hover:text-gray-400 cursor-help transition-colors">
            <Info size={13} />
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

function Loader() {
  return (
    <div className="flex justify-center py-6 text-gray-500">
      <Loader2 size={14} className="animate-spin" />
    </div>
  )
}

function Empty() {
  return <p className="text-xs text-gray-500 italic py-3">Данных нет за выбранный период.</p>
}

function fmtTs(iso: string, bucket: 'hour' | 'day'): string {
  try {
    const d = new Date(iso)
    if (bucket === 'hour') return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
  } catch { return iso }
}
