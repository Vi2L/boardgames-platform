/**
 * SnapshotsTab — таблица raw HTTP-снепшотов из parsers БД.
 *
 * Snapshot'ы пишутся только при ENABLE_RAW_SNAPSHOTS=1 на parsers — иначе
 * показываем баннер «фича выключена» и не делаем запросов к /snapshots
 * (они всё равно вернут пустой массив, но смысл в том чтобы человек понял
 * почему пусто).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Filter, AlertCircle, Eye } from 'lucide-react'
import clsx from 'clsx'
import { fetchDebugFeatures, fetchRawSnapshots, fetchParsers } from '../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../lib/stores'
import { RawHttpDrawer } from './RawHttpDrawer'

const HOURS_OPTIONS = [1, 6, 24, 72, 168]

export function SnapshotsTab() {
  const [store, setStore] = useState<string>('')
  const [query, setQuery] = useState('')
  const [hours, setHours] = useState(72)
  const [openId, setOpenId] = useState<number | null>(null)

  const features = useQuery({ queryKey: ['debug-features'], queryFn: fetchDebugFeatures })
  const parsers = useQuery({ queryKey: ['parsers'], queryFn: fetchParsers })

  const enabled = features.data?.raw_snapshots === true

  const list = useQuery({
    queryKey: ['raw-snapshots', store, query, hours],
    queryFn: () => fetchRawSnapshots({
      store: store || undefined,
      query: query || undefined,
      hours,
      limit: 100,
    }),
    enabled,
    refetchInterval: 30_000,
  })

  return (
    <div className="space-y-4">
      {!features.isLoading && !enabled && (
        <div className="bg-amber-950/40 border border-amber-900/50 rounded p-3 text-xs text-amber-300 flex gap-2">
          <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
          <div>
            <div className="font-medium text-amber-200">Snapshots отключены</div>
            <div className="mt-1">
              На parsers запусти с <code className="bg-black/30 px-1 rounded">ENABLE_RAW_SNAPSHOTS=1</code>,
              чтобы каждый HTTP-ответ парсера попадал в БД и был виден здесь.
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 flex flex-wrap items-center gap-3">
        <Filter size={12} className="text-gray-500" />

        <select
          value={store}
          onChange={e => setStore(e.target.value)}
          className="px-2 py-1 text-xs bg-gray-800 border border-gray-700 rounded text-gray-200"
        >
          <option value="">все магазины</option>
          {parsers.data?.map(p => (
            <option key={p.slug} value={p.slug}>{getStoreLabel(p.slug, p.name)}</option>
          ))}
        </select>

        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="фильтр по query (LIKE %x%)"
          className="px-2 py-1 text-xs bg-gray-800 border border-gray-700 rounded text-gray-200 placeholder-gray-500 w-56"
        />

        <div className="flex items-center gap-1 text-xs text-gray-500">
          <span>Окно:</span>
          {HOURS_OPTIONS.map(h => (
            <button
              key={h}
              type="button"
              onClick={() => setHours(h)}
              className={clsx(
                'px-2 py-0.5 rounded',
                hours === h
                  ? 'bg-violet-900/60 text-violet-200'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
              )}
            >
              {h < 24 ? `${h}ч` : `${h / 24}д`}
            </button>
          ))}
        </div>

        <button
          onClick={() => list.refetch()}
          disabled={!enabled}
          className="ml-auto flex items-center gap-1 px-2 py-1 text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded disabled:opacity-40"
        >
          <RefreshCw size={11} className={list.isFetching ? 'animate-spin' : ''} />
          Обновить
        </button>
      </div>

      {/* Table */}
      {enabled && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-950 text-gray-500">
              <tr className="text-left">
                <th className="px-3 py-2">id</th>
                <th className="px-3 py-2">время</th>
                <th className="px-3 py-2">магазин</th>
                <th className="px-3 py-2">kind</th>
                <th className="px-3 py-2">метод / статус</th>
                <th className="px-3 py-2">query</th>
                <th className="px-3 py-2">размер</th>
                <th className="px-3 py-2">ms</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {list.data?.map(s => (
                <tr key={s.id} className="hover:bg-gray-850 cursor-pointer"
                    onClick={() => setOpenId(s.id)}>
                  <td className="px-3 py-2 font-mono text-gray-500">{s.id}</td>
                  <td className="px-3 py-2 text-gray-400 font-mono whitespace-nowrap">
                    {formatTs(s.ts)}
                  </td>
                  <td className="px-3 py-2">
                    <span className={clsx('px-1.5 py-0.5 rounded', getStoreBadgeColor(s.store_slug))}>
                      {getStoreLabel(s.store_slug)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-400">{s.kind}</td>
                  <td className="px-3 py-2 font-mono">
                    <span className="text-gray-400">{s.method}</span>
                    <span className="ml-1 text-gray-500">·</span>
                    <span className={clsx('ml-1', statusColor(s.status_code))}>
                      {s.status_code ?? '—'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-300 truncate max-w-[200px]" title={s.query || ''}>
                    {s.query || <span className="italic text-gray-600">—</span>}
                  </td>
                  <td className="px-3 py-2 text-gray-400 font-mono">
                    {s.body_size ? `${(s.body_size / 1024).toFixed(1)} KB` : '—'}
                    {s.truncated ? <span className="text-amber-400 ml-1">✂</span> : null}
                  </td>
                  <td className="px-3 py-2 text-gray-400 font-mono">{s.duration_ms ?? '—'}</td>
                  <td className="px-3 py-2">
                    <Eye size={12} className="text-gray-500" />
                  </td>
                </tr>
              ))}
              {(!list.data || list.data.length === 0) && (
                <tr>
                  <td colSpan={9} className="px-3 py-6 text-center text-gray-500">
                    {list.isLoading ? 'загрузка…' : 'Нет снепшотов в выбранном окне.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {openId !== null && (
        <RawHttpDrawer snapshotId={openId} onClose={() => setOpenId(null)} />
      )}
    </div>
  )
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('ru-RU', { hour12: false }).replace(',', '')
  } catch {
    return iso
  }
}

function statusColor(s: number | null): string {
  if (s == null) return 'text-gray-600'
  if (s >= 200 && s < 300) return 'text-emerald-400'
  if (s >= 300 && s < 400) return 'text-blue-300'
  return 'text-red-400'
}
