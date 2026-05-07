/**
 * WikidataCard — labels/aliases по языкам.
 *
 * Wikidata-локализации часто покрывают русский (что критично для нашего
 * матчинга) и десятки других языков. Показываем в табличной форме:
 * «Язык → label · кол-во доп. алиасов».
 */
import { Database } from 'lucide-react'
import type { CatalogGameWikidata } from '../../lib/catalog'

const LANG_NAMES: Record<string, string> = {
  ru: 'Русский', en: 'English', de: 'Deutsch', fr: 'Français',
  es: 'Español', it: 'Italiano', pl: 'Polski', uk: 'Українська',
  zh: '中文', ja: '日本語', ko: '한국어', cs: 'Čeština', hu: 'Magyar',
  pt: 'Português', nl: 'Nederlands', tr: 'Türkçe',
}

export function WikidataCard({ wikidata }: { wikidata: CatalogGameWikidata }) {
  const langs = new Set([
    ...Object.keys(wikidata.labels),
    ...Object.keys(wikidata.aliases),
    ...Object.keys(wikidata.descriptions),
  ])

  return (
    <div className="bg-blue-950/20 border border-blue-900/40 rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database size={14} className="text-blue-400" />
          <span className="text-sm font-semibold text-blue-200">Wikidata</span>
          {wikidata.entity_id && (
            <a
              href={`https://www.wikidata.org/wiki/${wikidata.entity_id}`}
              target="_blank"
              rel="noreferrer"
              className="text-xs font-mono text-blue-300 hover:underline"
            >
              {wikidata.entity_id}
            </a>
          )}
        </div>
        <div className="text-xs text-gray-500">
          {wikidata.found ? `${langs.size} языков` : 'не найдено'}
        </div>
      </div>

      {!wikidata.found ? (
        <div className="text-xs text-gray-500 italic">
          Wikidata-запись не найдена для bgg_id={wikidata.bgg_id ?? '—'}.
        </div>
      ) : langs.size === 0 ? (
        <div className="text-xs text-gray-500 italic">Локализаций нет.</div>
      ) : (
        <div className="space-y-1.5 max-h-72 overflow-y-auto">
          {[...langs].sort(langOrder).map(lang => {
            const label = wikidata.labels[lang]
            const aliases = wikidata.aliases[lang] || []
            const desc = wikidata.descriptions[lang]
            return (
              <div key={lang} className="bg-gray-900 rounded p-2 space-y-1">
                <div className="flex items-center gap-2 text-xs">
                  <span className="font-mono text-blue-300 uppercase w-8 flex-shrink-0">{lang}</span>
                  <span className="text-gray-400 text-[10px]">{LANG_NAMES[lang] || ''}</span>
                </div>
                {label && <div className="text-sm text-gray-100">{label}</div>}
                {aliases.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {aliases.map((a, i) => (
                      <span key={i} className="text-xs px-1.5 py-0.5 rounded bg-blue-900/40 text-blue-200">
                        {a}
                      </span>
                    ))}
                  </div>
                )}
                {desc && (
                  <div className="text-xs text-gray-400 italic line-clamp-2">{desc}</div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <div className="text-[10px] text-gray-500 font-mono pt-1 border-t border-blue-900/30">
        fetched: {wikidata.fetched_at.slice(0, 10)}
      </div>
    </div>
  )
}

// Русский — первым (это primary locale матчинга), английский — вторым,
// потом все остальные по алфавиту.
function langOrder(a: string, b: string): number {
  if (a === 'ru') return -1
  if (b === 'ru') return 1
  if (a === 'en') return -1
  if (b === 'en') return 1
  return a.localeCompare(b)
}
