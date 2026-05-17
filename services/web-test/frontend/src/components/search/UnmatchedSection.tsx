/**
 * UnmatchedSection — секция «Не сматчено» под master-таблицей (`pages/05-search.md`).
 *
 * Появляется когда у offer'а нет совпадения с каноническим title других
 * магазинов (frontend-fallback) или backend пометил его `game_id=null`.
 *
 * Collapse-сценарий: по умолчанию свёрнут если orphans > 10, иначе
 * развёрнут. Default expanded если > 0.
 *
 * `[Сматчить]` кнопка ведёт на `/matching` со query-параметром offer_id —
 * там оператор сделает ручную привязку.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import type { ProductOut } from '../../types/api'
import { getStoreBadgeColor, getStoreLabel } from '../../lib/stores'
import { Button } from '../ui'

export interface UnmatchedSectionProps {
  orphans: ProductOut[]
  onSelectOrphan?: (p: ProductOut) => void
}

export function UnmatchedSection({ orphans, onSelectOrphan }: UnmatchedSectionProps) {
  const [collapsed, setCollapsed] = useState(orphans.length > 10)

  if (orphans.length === 0) return null

  return (
    <section className="border-t-2 border-amber-500/30 pt-3 mt-4">
      <button
        type="button"
        onClick={() => setCollapsed(c => !c)}
        className="flex items-center gap-2 text-amber-300 hover:text-amber-200 mb-2"
      >
        {collapsed
          ? <ChevronRight size={14} />
          : <ChevronDown size={14} />}
        <AlertTriangle size={14} />
        <span className="text-sm font-medium">Не сматчено</span>
        <span className="text-xs font-mono tabular-nums text-amber-400/70">({orphans.length})</span>
        <span className="text-xxs text-zinc-500 ml-2">
          не нашлось пары в других магазинах
        </span>
      </button>

      {!collapsed && (
        <div className="space-y-1 max-h-96 overflow-y-auto">
          {orphans.map(o => (
            <OrphanRow key={o.id} offer={o} onSelect={onSelectOrphan} />
          ))}
        </div>
      )}
    </section>
  )
}

function OrphanRow({
  offer, onSelect,
}: {
  offer: ProductOut
  onSelect?: (p: ProductOut) => void
}) {
  return (
    <div
      className="flex items-center gap-3 px-3 py-1.5 rounded bg-zinc-950/40 border border-zinc-800 hover:bg-zinc-800/30 cursor-pointer text-xs"
      onClick={() => onSelect?.(offer)}
    >
      <AlertTriangle size={11} className="text-amber-400 shrink-0" />
      <span
        className={`text-xxs font-mono px-1 py-0.5 rounded shrink-0 ${getStoreBadgeColor(offer.store_slug)}`}
        title={getStoreLabel(offer.store_slug)}
      >
        {offer.store_slug}
      </span>
      <span className="text-zinc-300 truncate flex-1" title={offer.title}>
        {offer.title}
      </span>
      <span className="text-emerald-400 font-mono tabular-nums shrink-0">
        {offer.price_rub.toLocaleString('ru-RU')} ₽
      </span>
      <a
        href={offer.url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={e => e.stopPropagation()}
        className="text-zinc-500 hover:text-indigo-300 shrink-0"
        title="Открыть в магазине"
      >
        <ExternalLink size={11} />
      </a>
      <Button asChild variant="primary" size="xs">
        <Link
          to={`/matching?store=${offer.store_slug}`}
          onClick={e => e.stopPropagation()}
        >
          Сматчить
        </Link>
      </Button>
    </div>
  )
}
