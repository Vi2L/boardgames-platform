/**
 * AliasList — список alternate names игры с источниками и языками.
 *
 * UI-only, без edit-функций (это F2.2). Показывает каждый алиас как «pill»
 * с цветом по source: manual (зелёный, verified=true), bgg/wikidata/tesera
 * (нейтральные), auto-match (приглушённый).
 */
import { CheckCircle2, Globe } from 'lucide-react'
import clsx from 'clsx'
import type { CatalogGameAlias } from '../../lib/catalog'

export function AliasList({ aliases }: { aliases: CatalogGameAlias[] }) {
  if (!aliases || aliases.length === 0) {
    return <div className="text-xs text-gray-500 italic">Алиасов нет.</div>
  }
  // Сортируем: verified manual первыми, затем bgg/wikidata/tesera, в конце auto-match.
  const order = (a: CatalogGameAlias) => {
    if (a.verified && a.source === 'manual') return 0
    if (a.source === 'manual') return 1
    if (a.source === 'wikidata') return 2
    if (a.source === 'bgg' || a.source === 'tesera') return 3
    return 4
  }
  const sorted = [...aliases].sort((a, b) => order(a) - order(b))
  return (
    <div className="flex flex-wrap gap-1.5">
      {sorted.map(a => (
        <div
          key={a.id}
          className={clsx(
            'flex items-center gap-1.5 px-2 py-1 rounded text-xs border',
            badgeColors(a),
          )}
        >
          <span className="text-gray-100">{a.alias}</span>
          {a.language && (
            <span className="flex items-center gap-0.5 text-[10px] text-gray-400 font-mono uppercase">
              <Globe size={9} /> {a.language}
            </span>
          )}
          <span className="text-[10px] text-gray-500 font-mono uppercase tracking-wide">
            {a.source}
          </span>
          {a.verified && (
            <CheckCircle2 size={11} className="text-emerald-400" />
          )}
        </div>
      ))}
    </div>
  )
}

function badgeColors(a: CatalogGameAlias): string {
  if (a.verified) return 'bg-emerald-950/40 border-emerald-900/50'
  switch (a.source) {
    case 'manual':   return 'bg-gray-800 border-gray-700'
    case 'bgg':      return 'bg-orange-950/40 border-orange-900/50'
    case 'wikidata': return 'bg-blue-950/40 border-blue-900/50'
    case 'tesera':   return 'bg-cyan-950/40 border-cyan-900/50'
    case 'auto-match': return 'bg-gray-900 border-gray-800 opacity-70'
    default:         return 'bg-gray-900 border-gray-800'
  }
}
