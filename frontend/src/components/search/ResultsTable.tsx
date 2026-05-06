import { useState } from 'react'
import { ChevronDown, ChevronUp, Users, Clock, Baby, ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import clsx from 'clsx'
import type { PriceDeltaOut, ProductOut } from '../../types/api'
import { getStoreBadgeColor } from '../../lib/stores'

interface Props {
  products: ProductOut[]
  /** Δ-цены пакетом (id → PriceDeltaOut). Может быть пустым на первом рендере. */
  deltas?: Map<number, PriceDeltaOut>
  onSelect: (product: ProductOut) => void
}

/**
 * Показывает значок изменения цены: ↑ +5% (red), ↓ −12% (green), — (gray).
 * Логика «зелёный для падения цены» — пользовательская: для покупателя
 * снижение цены — благоприятное событие.
 */
function PriceDelta({ delta }: { delta?: PriceDeltaOut }) {
  if (!delta || delta.delta_pct == null) {
    return <span className="text-gray-600 text-xs flex items-center gap-1"><Minus size={10} />—</span>
  }
  const pct = delta.delta_pct
  const isUp = pct > 0
  const isDown = pct < 0
  const Icon = isUp ? ArrowUpRight : isDown ? ArrowDownRight : Minus
  const cls =
    isUp ? 'text-red-400' :
    isDown ? 'text-green-400' :
    'text-gray-500'
  const tooltip = delta.prev_price_rub != null && delta.days_between != null
    ? `Было ${delta.prev_price_rub.toLocaleString('ru-RU')} ₽ ${delta.days_between} дн. назад`
    : 'Изменение цены'
  return (
    <span className={clsx('text-xs flex items-center gap-0.5 font-medium whitespace-nowrap', cls)} title={tooltip}>
      <Icon size={11} />
      {isUp ? '+' : ''}{pct}%
    </span>
  )
}

function timeAgo(dateStr: string): string {
  if (!dateStr) return '—'
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 60_000) return 'только что'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} мин.`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} ч.`
  return `${Math.floor(diff / 86_400_000)} дн.`
}

function formatPrice(rub: number): string {
  return `${rub.toLocaleString('ru-RU', { minimumFractionDigits: 0 })} ₽`
}

/**
 * Таблица результатов поиска с двумя представлениями:
 * - на md+ экранах: классическая таблица (привычная плотность для дебаг-сценария);
 * - на <md: карточки (обычная таблица режется горизонтальным скроллом и
 *   становится нечитаемой на 375px).
 *
 * Опциональные колонки/секции (Δ-цена, описание) на узких экранах прячутся,
 * чтобы карточка влезала в один ряд без переполнения.
 */
export function ResultsTable({ products, deltas, onSelect }: Props) {
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  if (products.length === 0) {
    return <div className="text-center text-gray-500 py-12 text-sm">Нет результатов</div>
  }

  const sorted = [...products].sort((a, b) =>
    sortDir === 'asc' ? a.price_rub - b.price_rub : b.price_rub - a.price_rub
  )

  const renderStoreBadge = (slug: string) => (
    <span className={clsx('px-2 py-0.5 rounded text-xs font-mono font-medium', getStoreBadgeColor(slug))}>
      {slug}
    </span>
  )

  const renderParams = (p: ProductOut) => (
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
  )

  return (
    <>
      {/* ── Desktop / Tablet: таблица ─────────────────────────────────── */}
      <div className="hidden md:block overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/80">
              <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium w-8"></th>
              <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium">Магазин</th>
              <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium">Название</th>
              <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium hidden lg:table-cell">Параметры</th>
              <th
                className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium cursor-pointer hover:text-gray-300 select-none whitespace-nowrap"
                onClick={() => setSortDir(d => d === 'asc' ? 'desc' : 'asc')}
              >
                <span className="flex items-center gap-1">
                  Цена {sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </span>
              </th>
              <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium hidden xl:table-cell whitespace-nowrap" title="Изменение цены между двумя последними точками истории">Δ</th>
              <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium hidden lg:table-cell">Дата</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(p => (
              <tr
                key={p.id}
                className="border-b border-gray-800/40 hover:bg-gray-900/60 cursor-pointer transition-colors"
                onClick={() => onSelect(p)}
              >
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
                <td className="px-3 py-2.5">{renderStoreBadge(p.store_slug)}</td>
                <td className="px-3 py-2.5 max-w-xs">
                  <div className="font-medium text-gray-200 truncate" title={p.title}>{p.title}</div>
                  {p.description && (
                    <div className="text-xs text-gray-500 truncate mt-0.5" title={p.description}>
                      {p.description}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2.5 hidden lg:table-cell">{renderParams(p)}</td>
                <td className="px-3 py-2.5 whitespace-nowrap text-green-400 font-semibold">
                  {formatPrice(p.price_rub)}
                </td>
                <td className="px-3 py-2.5 hidden xl:table-cell">
                  <PriceDelta delta={deltas?.get(p.id)} />
                </td>
                <td className="px-3 py-2.5 text-gray-500 text-xs whitespace-nowrap hidden lg:table-cell">
                  {timeAgo(p.fetched_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Mobile: карточки ──────────────────────────────────────────── */}
      <div className="md:hidden grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="col-span-full flex justify-end mb-1">
          <button
            type="button"
            onClick={() => setSortDir(d => d === 'asc' ? 'desc' : 'asc')}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded bg-gray-900 border border-gray-800"
          >
            Сортировка по цене {sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        </div>
        {sorted.map(p => (
          <button
            key={p.id}
            type="button"
            onClick={() => onSelect(p)}
            className="text-left flex gap-3 p-3 bg-gray-900 border border-gray-800 rounded-lg hover:bg-gray-900/60 active:bg-gray-800/60 transition-colors"
          >
            {(p.image_url_hd ?? p.image_url) ? (
              <img
                src={p.image_url_hd ?? p.image_url ?? ''}
                alt=""
                className="w-14 h-14 flex-shrink-0 object-cover rounded bg-gray-800"
                onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
              />
            ) : (
              <div className="w-14 h-14 flex-shrink-0 rounded bg-gray-800" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                {renderStoreBadge(p.store_slug)}
                <span className="text-xs text-gray-500">{timeAgo(p.fetched_at)}</span>
              </div>
              <div className="font-medium text-gray-200 line-clamp-2 mb-1">{p.title}</div>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className="text-green-400 font-semibold whitespace-nowrap">
                    {formatPrice(p.price_rub)}
                  </div>
                  <PriceDelta delta={deltas?.get(p.id)} />
                </div>
                {renderParams(p)}
              </div>
            </div>
          </button>
        ))}
      </div>
    </>
  )
}
