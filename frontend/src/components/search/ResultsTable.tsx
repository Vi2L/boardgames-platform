import { useState } from 'react'
import { ChevronDown, ChevronUp, Users, Clock, Baby, ExternalLink } from 'lucide-react'
import clsx from 'clsx'
import type { ProductOut } from '../../types/api'

interface Props {
  products: ProductOut[]
  onSelect: (product: ProductOut) => void
}

const STORE_COLORS: Record<string, string> = {
  hobbygames: 'bg-blue-900/70 text-blue-300',
  lavkaigr:   'bg-green-900/70 text-green-300',
  gaga:       'bg-orange-900/70 text-orange-300',
}

function timeAgo(dateStr: string): string {
  if (!dateStr) return '—'
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 60_000) return 'только что'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} мин.`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} ч.`
  return `${Math.floor(diff / 86_400_000)} дн.`
}

export function ResultsTable({ products, onSelect }: Props) {
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  if (products.length === 0) {
    return <div className="text-center text-gray-500 py-12 text-sm">Нет результатов</div>
  }

  const sorted = [...products].sort((a, b) =>
    sortDir === 'asc' ? a.price_rub - b.price_rub : b.price_rub - a.price_rub
  )

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-900/80">
            <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium w-8"></th>
            <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium">Магазин</th>
            <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium">Название</th>
            <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium">Параметры</th>
            <th
              className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium cursor-pointer hover:text-gray-300 select-none whitespace-nowrap"
              onClick={() => setSortDir(d => d === 'asc' ? 'desc' : 'asc')}
            >
              <span className="flex items-center gap-1">
                Цена {sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </span>
            </th>
            <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium">Дата</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(p => (
            <tr
              key={p.id}
              className="border-b border-gray-800/40 hover:bg-gray-900/60 cursor-pointer transition-colors"
              onClick={() => onSelect(p)}
            >
              {/* Thumbnail */}
              <td className="px-2 py-2">
                {(p.image_url_hd ?? p.image_url) ? (
                  <img
                    src={p.image_url_hd ?? p.image_url ?? ''}
                    alt=""
                    className="w-8 h-8 object-cover rounded bg-gray-800"
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                  />
                ) : (
                  <div className="w-8 h-8 rounded bg-gray-800" />
                )}
              </td>

              {/* Store */}
              <td className="px-3 py-2.5">
                <span className={clsx(
                  'px-2 py-0.5 rounded text-xs font-mono font-medium',
                  STORE_COLORS[p.store_slug] ?? 'bg-gray-800 text-gray-300',
                )}>
                  {p.store_slug}
                </span>
              </td>

              {/* Title + description */}
              <td className="px-3 py-2.5 max-w-xs">
                <div className="font-medium text-gray-200 truncate" title={p.title}>{p.title}</div>
                {p.description && (
                  <div className="text-xs text-gray-500 truncate mt-0.5" title={p.description}>
                    {p.description}
                  </div>
                )}
              </td>

              {/* players / age / playtime */}
              <td className="px-3 py-2.5">
                <div className="flex flex-wrap gap-1.5">
                  {p.players && (
                    <span className="flex items-center gap-0.5 text-xs text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">
                      <Users size={10} /> {p.players}
                    </span>
                  )}
                  {p.age_min != null && (
                    <span className="flex items-center gap-0.5 text-xs text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">
                      <Baby size={10} /> {p.age_min}+
                    </span>
                  )}
                  {p.playtime && (
                    <span className="flex items-center gap-0.5 text-xs text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">
                      <Clock size={10} /> {p.playtime}
                    </span>
                  )}
                </div>
              </td>

              {/* Price */}
              <td className="px-3 py-2.5 whitespace-nowrap text-green-400 font-semibold">
                {p.price_rub.toLocaleString('ru-RU', { minimumFractionDigits: 0 })} ₽
              </td>

              {/* Date */}
              <td className="px-3 py-2.5 text-gray-500 text-xs whitespace-nowrap">
                {timeAgo(p.fetched_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
