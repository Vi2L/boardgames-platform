/**
 * InventoryTab — БД parsers: общая мета + per-store inventory.
 *
 * Заменяет соответствующую секцию /dashboard parsers (vanilla JS на :8001).
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, Database, Package, Clock } from 'lucide-react'
import clsx from 'clsx'
import { fetchParsersDbMeta, fetchParsersStoresInventory } from '../../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../../lib/stores'

export function InventoryTab() {
  const meta = useQuery({ queryKey: ['parsers-db', 'meta'], queryFn: fetchParsersDbMeta })
  const inv = useQuery({ queryKey: ['parsers-db', 'stores-inventory'],
                         queryFn: fetchParsersStoresInventory })

  if (meta.isLoading || inv.isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-gray-500">
        <Loader2 size={18} className="animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Top meta cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetaCard icon={<Database size={14} />} label="Размер БД"
                  value={meta.data ? formatBytes(meta.data.size_bytes) : '—'} />
        <MetaCard icon={<Package size={14} />} label="Товаров"
                  value={meta.data?.product_count?.toLocaleString() ?? '—'} />
        <MetaCard icon={<Clock size={14} />} label="Наблюдений"
                  value={meta.data?.observation_count?.toLocaleString() ?? '—'} />
        <MetaCard icon={<Clock size={14} />} label="Окно данных"
                  value={meta.data?.oldest_observation
                    ? `${meta.data.oldest_observation.slice(0, 10)} → ${(meta.data.newest_observation ?? '').slice(0, 10)}`
                    : '—'} />
      </div>

      {/* Inventory table */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-950 text-gray-500 text-left">
            <tr>
              <th className="px-3 py-2">магазин</th>
              <th className="px-3 py-2 text-right">товаров</th>
              <th className="px-3 py-2 text-right">наблюдений</th>
              <th className="px-3 py-2 text-right">мин. ₽</th>
              <th className="px-3 py-2 text-right">средняя ₽</th>
              <th className="px-3 py-2 text-right">макс. ₽</th>
              <th className="px-3 py-2 text-right">обновлено</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {(inv.data ?? []).map(r => (
              <tr key={r.store_slug} className="hover:bg-gray-850">
                <td className="px-3 py-2">
                  <span className={clsx('px-1.5 py-0.5 rounded font-mono', getStoreBadgeColor(r.store_slug))}>
                    {getStoreLabel(r.store_slug)}
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-300">
                  {r.product_count.toLocaleString()}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-400">
                  {r.observation_count.toLocaleString()}
                </td>
                <td className="px-3 py-2 text-right font-mono text-emerald-400">
                  {r.min_price != null ? Math.round(r.min_price / 100).toLocaleString() : '—'}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-300">
                  {r.avg_price != null ? Math.round(r.avg_price / 100).toLocaleString() : '—'}
                </td>
                <td className="px-3 py-2 text-right font-mono text-amber-400">
                  {r.max_price != null ? Math.round(r.max_price / 100).toLocaleString() : '—'}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-500">
                  {r.last_seen ? r.last_seen.slice(0, 10) : '—'}
                </td>
              </tr>
            ))}
            {(!inv.data || inv.data.length === 0) && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-gray-500">
                Inventory пуст — запусти любой парсер.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MetaCard({
  icon, label, value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded p-3 space-y-1">
      <div className="flex items-center gap-1.5 text-xs text-gray-500">{icon} {label}</div>
      <div className="text-base font-mono text-gray-100 truncate">{value}</div>
    </div>
  )
}

function formatBytes(b: number): string {
  if (!b) return '—'
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
}
