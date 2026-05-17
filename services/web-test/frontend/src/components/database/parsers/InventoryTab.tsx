/**
 * InventoryTab — БД parsers: общая мета + per-store inventory.
 *
 * Заменяет соответствующую секцию /dashboard parsers (vanilla JS на :8001).
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, Database, Package, Clock, RefreshCw, Info,
  ArrowUpDown, ArrowUp, ArrowDown,
} from 'lucide-react'
import clsx from 'clsx'
import {
  fetchParsersDbMeta, fetchParsersStoresInventory,
  type ParsersStoreInventory,
} from '../../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../../lib/stores'

type SortKey = keyof Pick<
  ParsersStoreInventory,
  'store_slug' | 'products_count' | 'observations_count'
  | 'min_price_rub' | 'mean_price_rub' | 'max_price_rub' | 'newest_obs'
>
type SortDir = 'asc' | 'desc'

export function InventoryTab() {
  const queryClient = useQueryClient()
  const meta = useQuery({ queryKey: ['parsers-db', 'meta'], queryFn: fetchParsersDbMeta })
  const inv = useQuery({ queryKey: ['parsers-db', 'stores-inventory'],
                         queryFn: fetchParsersStoresInventory })

  const [sortKey, setSortKey] = useState<SortKey>('observations_count')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const sorted = useMemo(() => {
    const rows = inv.data ?? []
    return [...rows].sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      let cmp = 0
      if (av == null && bv == null) cmp = 0
      else if (av == null) cmp = 1
      else if (bv == null) cmp = -1
      else if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv
      else cmp = String(av).localeCompare(String(bv), 'ru-RU')
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [inv.data, sortKey, sortDir])

  const onSort = (k: SortKey) => {
    if (sortKey === k) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(k); setSortDir('desc') }
  }

  if (meta.isLoading || inv.isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-gray-500">
        <Loader2 size={18} className="animate-spin" />
      </div>
    )
  }

  const productsCount = meta.data?.tables?.products
  const obsCount = meta.data?.tables?.price_observations
  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'meta'] })
    void queryClient.invalidateQueries({ queryKey: ['parsers-db', 'stores-inventory'] })
  }

  return (
    <div className="space-y-4">
      {/* Info-блок: назначение раздела */}
      <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-gray-950/40 border border-gray-800 text-xs text-gray-400">
        <Info size={13} className="text-indigo-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <strong className="text-gray-300">Inventory parsers</strong> — состояние SQLite БД сервиса парсеров.
          Карточки сверху — суммарно: размер файла, общее количество товаров и точек цен (price_observations),
          окно наблюдений. Таблица — per-store: сколько товаров в кеше, сколько точек истории, диапазон цен и
          когда последний раз обновляли.
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-800 hover:bg-gray-700 text-gray-200"
          title="Перезагрузить мета и inventory"
        >
          <RefreshCw size={11} /> Обновить
        </button>
      </div>

      {/* Top meta cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetaCard
          icon={<Database size={14} />}
          label="Размер БД"
          value={meta.data?.db_size_bytes != null ? formatBytes(meta.data.db_size_bytes) : '—'}
          tooltip={meta.data?.db_size_mb != null ? `${meta.data.db_size_mb} MB` : undefined}
        />
        <MetaCard
          icon={<Package size={14} />}
          label="Товаров"
          value={productsCount != null ? productsCount.toLocaleString('ru-RU') : '—'}
          tooltip="Уникальных товаров во всех магазинах (таблица products)"
        />
        <MetaCard
          icon={<Clock size={14} />}
          label="Наблюдений"
          value={obsCount != null ? obsCount.toLocaleString('ru-RU') : '—'}
          tooltip="Точек истории цен (таблица price_observations) — каждый успешный парсинг = +1 точка на товар"
        />
        <MetaCard
          icon={<Clock size={14} />}
          label="Окно данных"
          value={meta.data?.oldest_observation
            ? `${meta.data.oldest_observation.slice(0, 10)} → ${(meta.data.newest_observation ?? '').slice(0, 10)}`
            : '—'}
          tooltip="Самая старая и самая свежая дата в price_observations"
        />
      </div>

      {/* Inventory table */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-950 text-gray-500 text-left">
            <tr>
              <SortableTh keyName="store_slug" label="магазин" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <SortableTh keyName="products_count" label="товаров" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right"
                          title="Количество уникальных товаров от этого магазина в БД" />
              <SortableTh keyName="observations_count" label="наблюдений" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right"
                          title="Количество точек истории цен (records в price_observations)" />
              <SortableTh keyName="min_price_rub" label="мин. ₽" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right"
                          title="Минимальная цена среди всех наблюдений магазина" />
              <SortableTh keyName="mean_price_rub" label="средняя ₽" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right"
                          title="Средняя цена по всем наблюдениям" />
              <SortableTh keyName="max_price_rub" label="макс. ₽" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right"
                          title="Максимальная цена среди всех наблюдений магазина" />
              <SortableTh keyName="newest_obs" label="обновлено" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right"
                          title="Дата последнего наблюдения" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {sorted.map(r => (
              <tr key={r.store_slug} className="hover:bg-gray-850">
                <td className="px-3 py-2">
                  <span className={clsx('px-1.5 py-0.5 rounded font-mono', getStoreBadgeColor(r.store_slug))}>
                    {getStoreLabel(r.store_slug)}
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-300">
                  {r.products_count.toLocaleString('ru-RU')}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-400">
                  {r.observations_count.toLocaleString('ru-RU')}
                </td>
                <td className="px-3 py-2 text-right font-mono text-emerald-400">
                  {r.min_price_rub != null ? Math.round(r.min_price_rub).toLocaleString('ru-RU') : '—'}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-300">
                  {r.mean_price_rub != null ? Math.round(r.mean_price_rub).toLocaleString('ru-RU') : '—'}
                </td>
                <td className="px-3 py-2 text-right font-mono text-amber-400">
                  {r.max_price_rub != null ? Math.round(r.max_price_rub).toLocaleString('ru-RU') : '—'}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-500" title={r.newest_obs ?? undefined}>
                  {r.newest_obs ? r.newest_obs.slice(0, 10) : '—'}
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
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

function SortableTh({
  keyName, label, sortKey, sortDir, onSort, align = 'left', title,
}: {
  keyName: SortKey
  label: string
  sortKey: SortKey
  sortDir: SortDir
  onSort: (k: SortKey) => void
  align?: 'left' | 'right'
  title?: string
}) {
  const active = sortKey === keyName
  const Icon = active ? (sortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown
  return (
    <th
      className={clsx('px-3 py-2 select-none', align === 'right' ? 'text-right' : 'text-left')}
      title={title}
    >
      <button
        type="button"
        onClick={() => onSort(keyName)}
        className={clsx(
          'inline-flex items-center gap-1 hover:text-gray-300',
          active && 'text-gray-200',
        )}
      >
        {label}
        <Icon size={10} className={active ? '' : 'opacity-40'} />
      </button>
    </th>
  )
}

function MetaCard({
  icon, label, value, tooltip,
}: {
  icon: React.ReactNode
  label: string
  value: string
  tooltip?: string
}) {
  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded p-3 space-y-1" title={tooltip}>
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
