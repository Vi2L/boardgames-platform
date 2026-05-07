import { useState } from 'react'
import {
  ChevronDown, ChevronUp, ChevronsUpDown, Users, Clock, Baby,
  ArrowDownRight, ArrowUpRight, Minus,
} from 'lucide-react'
import clsx from 'clsx'
import type { PriceDeltaOut, ProductOut } from '../../types/api'
import { getStoreBadgeColor, getStoreLabel } from '../../lib/stores'

interface Props {
  products: ProductOut[]
  /** Δ-цены пакетом (id → PriceDeltaOut). Может быть пустым на первом рендере. */
  deltas?: Map<number, PriceDeltaOut>
  onSelect: (product: ProductOut) => void
}

type SortKey = 'store' | 'title' | 'price'
type SortDir = 'asc' | 'desc'

/** Лейблы для mobile-переключателя сортировки. */
const SORT_LABELS: Record<SortKey, string> = {
  store: 'Магазин',
  title: 'Название',
  price: 'Цена',
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
  // Дефолт — цена по возрастанию (сохраняем прежнее поведение). По клику на
  // тот же ключ — флипаем направление; на другой ключ — переключаем ключ и
  // сбрасываем dir в asc, чтобы интерфейс был предсказуем.
  const [sortKey, setSortKey] = useState<SortKey>('price')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  if (products.length === 0) {
    return <div className="text-center text-gray-500 py-12 text-sm">Нет результатов</div>
  }

  // Для магазина сортируем по человеческому имени, а не по slug —
  // «GaGa», «HobbyGames», «Лавка игр» вместо «gaga»/«hobbygames»/«lavkaigr».
  // Для названия — locale-aware с флагом sensitivity='base' (без учёта регистра/диакритики).
  const sorted = [...products].sort((a, b) => {
    let cmp = 0
    if (sortKey === 'price') {
      cmp = a.price_rub - b.price_rub
    } else if (sortKey === 'store') {
      cmp = getStoreLabel(a.store_slug).localeCompare(getStoreLabel(b.store_slug), 'ru-RU')
    } else if (sortKey === 'title') {
      cmp = a.title.localeCompare(b.title, 'ru-RU', { sensitivity: 'base' })
    }
    return sortDir === 'asc' ? cmp : -cmp
  })

  const renderStoreBadge = (slug: string) => (
    <span className={clsx('px-2 py-0.5 rounded text-xs font-mono font-medium', getStoreBadgeColor(slug))}>
      {slug}
    </span>
  )

  /**
   * Рендер кликабельного `<th>`. Активная колонка показывает направление
   * стрелкой; остальные — приглушённый ChevronsUpDown как индикатор того,
   * что по ним тоже можно сортировать.
   */
  const SortableTh = ({
    keyName, label, className,
  }: { keyName: SortKey; label: string; className?: string }) => {
    const active = sortKey === keyName
    const Icon = active
      ? (sortDir === 'asc' ? ChevronUp : ChevronDown)
      : ChevronsUpDown
    return (
      <th
        scope="col"
        className={clsx(
          'px-3 py-2.5 text-left text-xs font-medium cursor-pointer select-none whitespace-nowrap',
          active ? 'text-gray-300' : 'text-gray-500 hover:text-gray-300',
          className,
        )}
        onClick={() => toggleSort(keyName)}
        aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          <Icon size={12} className={active ? '' : 'opacity-40'} />
        </span>
      </th>
    )
  }

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
              <SortableTh keyName="store" label="Магазин" />
              <SortableTh keyName="title" label="Название" />
              <th className="px-3 py-2.5 text-left text-xs text-gray-500 font-medium hidden lg:table-cell">Параметры</th>
              <SortableTh keyName="price" label="Цена" />
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
        {/*
          Mobile-переключатель сортировки: сегментированный контрол вместо
          трёх дублирующих заголовков. Активная кнопка подсвечена + стрелка
          направления; повторный клик меняет dir.
        */}
        <div className="col-span-full flex flex-wrap items-center gap-1.5 mb-1">
          <span className="text-xs text-gray-500 mr-1">Сортировка:</span>
          {(Object.keys(SORT_LABELS) as SortKey[]).map(k => {
            const active = sortKey === k
            const Icon = active
              ? (sortDir === 'asc' ? ChevronUp : ChevronDown)
              : ChevronsUpDown
            return (
              <button
                key={k}
                type="button"
                onClick={() => toggleSort(k)}
                className={clsx(
                  'flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors',
                  active
                    ? 'bg-violet-900/40 border-violet-700 text-violet-200'
                    : 'bg-gray-900 border-gray-800 text-gray-400 hover:text-gray-200',
                )}
              >
                {SORT_LABELS[k]}
                <Icon size={12} className={active ? '' : 'opacity-40'} />
              </button>
            )
          })}
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
