/**
 * BggCard — данные из game_bgg (BGG ranks/XML API).
 *
 * Показываем top-level рейтинги отдельно (rank, average, users_rated)
 * и набор «теги» (designers/mechanics/categories) пилюлями. Description
 * не дублируем — он есть в основной карточке Game.
 */
import { Award, Trophy, Users, Ban } from 'lucide-react'
import type { CatalogGameBgg } from '../../lib/catalog'

export function BggCard({ bgg }: { bgg: CatalogGameBgg }) {
  return (
    <div className="bg-orange-950/20 border border-orange-900/40 rounded-lg p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Trophy size={14} className="text-orange-400" />
          <span className="text-sm font-semibold text-orange-200">BoardGameGeek</span>
          <span className="text-xs font-mono text-gray-500">#{bgg.bgg_id}</span>
        </div>
        <a
          href={`https://boardgamegeek.com/boardgame/${bgg.bgg_id}`}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-orange-300 hover:underline"
        >
          открыть на BGG →
        </a>
      </div>

      {/* Top stats */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <Stat icon={<Award size={11} />} label="rank" value={bgg.rank?.toLocaleString() ?? '—'} />
        <Stat icon={null} label="avg"
              value={bgg.average != null ? bgg.average.toFixed(2) : '—'} />
        <Stat icon={<Users size={11} />} label="raters"
              value={bgg.users_rated?.toLocaleString() ?? '—'} />
      </div>

      {bgg.is_expansion && (
        <div className="text-xs text-amber-300 flex items-center gap-1">
          <Ban size={11} /> расширение, не базовая игра
        </div>
      )}

      {/* Tags */}
      <Tags label="дизайнеры" items={bgg.designers} color="bg-violet-900/40 text-violet-200" />
      <Tags label="механики"  items={bgg.mechanics}  color="bg-emerald-900/40 text-emerald-200" />
      <Tags label="категории" items={bgg.categories} color="bg-blue-900/40 text-blue-200" />
      <Tags label="артисты"   items={bgg.artists}    color="bg-pink-900/40 text-pink-200" />

      <div className="text-[10px] text-gray-500 font-mono pt-1 border-t border-orange-900/30">
        source: {bgg.source ?? '—'} · fetched: {bgg.fetched_at.slice(0, 10)}
      </div>
    </div>
  )
}

function Stat({
  icon, label, value,
}: {
  icon: React.ReactNode
  label: string
  value: string | number
}) {
  return (
    <div className="bg-gray-900 rounded p-2">
      <div className="flex items-center gap-1 text-gray-500 text-[10px] uppercase tracking-wide">
        {icon} {label}
      </div>
      <div className="text-sm font-mono text-gray-100 mt-0.5">{value}</div>
    </div>
  )
}

function Tags({
  label, items, color,
}: {
  label: string
  items: string[] | null
  color: string
}) {
  if (!items || items.length === 0) return null
  return (
    <div className="space-y-1">
      <div className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.map(s => (
          <span key={s} className={`text-xs px-1.5 py-0.5 rounded ${color}`}>{s}</span>
        ))}
      </div>
    </div>
  )
}
