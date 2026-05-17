/**
 * ResultsTableGrouped — Master-таблица групп по `pages/05-search.md`.
 *
 * Строка = группа предложений по одной канонической игре (clustering
 * через `lib/searchGrouping.ts`). Click → выбор группы (для drawer).
 *
 * Колонки:
 *   canonical_title · stores · min · spread (mini-pills)
 *
 * Δ% / 90д sparkline — отложены до отдельной задачи (требует price-stats
 * по group, а не по offer; см. handoff §05).
 */
import { useMemo } from 'react'
import { getStoreBadgeColor, getStoreLabel } from '../../lib/stores'
import type { ProductGroup, GroupedResults } from '../../lib/searchGrouping'
import { Tag } from '../ui'

export interface ResultsTableGroupedProps {
  data: GroupedResults
  selectedId?: string | null
  onSelectGroup: (g: ProductGroup) => void
}

export function ResultsTableGrouped({ data, selectedId, onSelectGroup }: ResultsTableGroupedProps) {
  const { groups } = data

  if (groups.length === 0) {
    return (
      <div className="text-sm text-zinc-500 py-12 text-center">
        Нет групп с ≥2 магазинами. Все офферы в секции «Не сматчено» ниже.
      </div>
    )
  }

  return (
    <div className="border border-zinc-800 rounded overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-zinc-900 text-zinc-400 text-xs sticky top-0 z-10">
          <tr>
            <th className="text-left px-3 py-2 font-normal">Каноническая игра</th>
            <th className="text-left px-3 py-2 font-normal w-20">Магазины</th>
            <th className="text-right px-3 py-2 font-normal w-32">Min цена</th>
            <th className="text-left px-3 py-2 font-normal">Spread</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/60">
          {groups.map(g => (
            <GroupRow
              key={g.canonicalTitle}
              group={g}
              selected={selectedId === g.canonicalTitle}
              onClick={() => onSelectGroup(g)}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function GroupRow({
  group, selected, onClick,
}: { group: ProductGroup; selected: boolean; onClick: () => void }) {
  const minPrice = group.minPrice
  const stockText = `${group.inStockCount}/${group.totalStores}`

  return (
    <tr
      className={`cursor-pointer ${selected ? 'bg-indigo-500/10' : 'hover:bg-zinc-800/30'}`}
      onClick={onClick}
    >
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-zinc-200 font-medium truncate max-w-md" title={group.canonicalTitle}>
            {group.canonicalTitle}
          </span>
          {group.hasSale && (
            <Tag tone="warn">sale</Tag>
          )}
        </div>
        <div className="text-xxs text-zinc-500 font-mono">
          {group.offers.length} оффер{plural(group.offers.length, '', 'а', 'ов')}
        </div>
      </td>
      <td className="px-3 py-2 text-xs font-mono tabular-nums">
        <span className={group.inStockCount > 0 ? 'text-emerald-400' : 'text-zinc-500'}>
          {stockText}
        </span>
      </td>
      <td className="px-3 py-2 text-right">
        {minPrice != null
          ? <span className="text-emerald-300 font-mono tabular-nums">{minPrice.toLocaleString('ru-RU')} ₽</span>
          : <span className="text-zinc-600 text-xs">нет в наличии</span>}
      </td>
      <td className="px-3 py-2">
        <StoresSpread group={group} />
      </td>
    </tr>
  )
}

function StoresSpread({ group }: { group: ProductGroup }) {
  // Mini-pills: магазины представлены своим цветом-tag'ом (lib/stores).
  // Spread = разница min/max цен среди in_stock offers.
  const prices = useMemo(
    () => group.offers
      .filter(o => o.price_rub > 0)
      .map(o => o.price_rub)
      .sort((a, b) => a - b),
    [group.offers],
  )
  const min = prices[0] ?? null
  const max = prices[prices.length - 1] ?? null
  const spreadPct = (min && max && min > 0)
    ? ((max - min) / min) * 100
    : null

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="flex items-center gap-0.5">
        {group.storeSlugs.slice(0, 6).map(slug => (
          <span
            key={slug}
            title={getStoreLabel(slug)}
            className={`text-xxs font-mono px-1 py-0.5 rounded ${getStoreBadgeColor(slug)}`}
          >
            {slug.slice(0, 2)}
          </span>
        ))}
      </div>
      {spreadPct != null && spreadPct > 5 && (
        <span className={`text-xxs font-mono tabular-nums ${spreadPct > 30 ? 'text-amber-300' : 'text-zinc-500'}`}>
          ±{spreadPct.toFixed(0)}%
        </span>
      )}
    </div>
  )
}

function plural(n: number, one: string, few: string, many: string): string {
  const n10 = n % 10
  const n100 = n % 100
  if (n10 === 1 && n100 !== 11) return one
  if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return few
  return many
}
