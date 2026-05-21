/**
 * ContractPanel — контракт парсера (ParsedProduct) + heatmap coverage.
 *
 * Слева — таблица полей (required/optional, type, default).
 * Справа — heatmap «магазин × поле», % товаров с непустым значением.
 *
 * Назначение: понять, какие поля магазин стабильно отдаёт, а какие — null
 * в большинстве случаев. Это полезно при добавлении нового магазина или
 * при проверке регрессии после правки селекторов.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertTriangle } from 'lucide-react'
import clsx from 'clsx'
import { fetchContract, fetchFieldCoverage } from '../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../lib/stores'
import { HelpBox } from '../shared/HelpBox'

const HEATMAP_FIELDS = [
  'description', 'image_url', 'image_url_hd',
  'players', 'age_min', 'playtime', 'rules_url',
]

export function ContractPanel() {
  const contract = useQuery({ queryKey: ['debug-contract'], queryFn: fetchContract })
  const coverage = useQuery({ queryKey: ['debug-field-coverage'], queryFn: fetchFieldCoverage })

  if (contract.isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-gray-500">
        <Loader2 size={18} className="animate-spin" />
      </div>
    )
  }
  if (contract.isError) {
    return (
      <div className="bg-red-950/50 border border-red-900/50 rounded p-3 text-sm text-red-400 flex items-start gap-2">
        <AlertTriangle size={14} className="mt-0.5" />
        <div>Не удалось получить контракт: {String(contract.error)}</div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Fields table */}
        <div>
          <div className="text-xs text-gray-500 mb-2">
            <span className="font-mono text-gray-300">{contract.data!.model}</span>
            {' · '}
            <span className="font-mono text-gray-500">{contract.data!.module}</span>
            {' · '}
            <span>{contract.data!.fields.length} полей</span>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-gray-950 text-gray-500 text-left">
                <tr>
                  <th className="px-3 py-2">Поле</th>
                  <th className="px-3 py-2">Тип</th>
                  <th className="px-3 py-2">
                    <span className="inline-flex items-center gap-1">
                      Required <HelpBox topic="debug.parsed_product_required" />
                    </span>
                  </th>
                  <th className="px-3 py-2">
                    <span className="inline-flex items-center gap-1">
                      Default <HelpBox topic="debug.field_defaults" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {contract.data!.fields.map(f => (
                  <tr key={f.name} className="hover:bg-gray-850">
                    <td className="px-3 py-2 font-mono text-gray-200">
                      <span className="inline-flex items-center gap-1.5">
                        {f.name}
                        {f.name === 'category' && (
                          <HelpBox topic="debug.category_whitelist" />
                        )}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-gray-400">{f.type}</td>
                    <td className="px-3 py-2">
                      {f.required
                        ? <span className="px-1.5 py-0.5 rounded bg-red-900/50 text-red-300">required</span>
                        : <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">optional</span>}
                    </td>
                    <td className="px-3 py-2 font-mono text-gray-500 truncate max-w-[160px]">
                      {f.default === null ? <span className="italic">None</span> :
                       typeof f.default === 'object' && Object.keys(f.default || {}).length === 0
                         ? '{}' : JSON.stringify(f.default)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Coverage heatmap */}
        <div>
          <div className="text-xs text-gray-500 mb-2 inline-flex items-center gap-1.5">
            Coverage опциональных полей (% непустых значений в БД)
            <HelpBox topic="debug.coverage_heatmap" />
          </div>
          {coverage.isLoading ? (
            <div className="bg-gray-900 border border-gray-800 rounded-lg h-40 animate-pulse" />
          ) : coverage.isError ? (
            <div className="bg-red-950/40 border border-red-900/50 rounded p-3 text-xs text-red-300">
              Не удалось получить coverage: {String(coverage.error)}
            </div>
          ) : !coverage.data || coverage.data.length === 0 ? (
            <div className="bg-gray-900 border border-gray-800 rounded p-3 text-xs text-gray-500">
              В БД нет товаров — coverage пусто.
            </div>
          ) : (
            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-gray-950 text-gray-500 text-left">
                  <tr>
                    <th className="px-2 py-2 sticky left-0 bg-gray-950">магазин</th>
                    <th className="px-2 py-2 text-right">total</th>
                    {HEATMAP_FIELDS.map(f => (
                      <th key={f} className="px-2 py-2 text-center font-mono"
                          title={f}>{f.replace(/_/g, ' ')}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {coverage.data.map(row => (
                    <tr key={row.store_slug} className="border-t border-gray-800">
                      <td className="px-2 py-2">
                        <span className={clsx('px-1.5 py-0.5 rounded text-xs', getStoreBadgeColor(row.store_slug))}>
                          {getStoreLabel(row.store_slug)}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right font-mono text-gray-400">
                        {row.total.toLocaleString()}
                      </td>
                      {HEATMAP_FIELDS.map(f => {
                        const pct = row.coverage[f] ?? 0
                        return <CoverageCell key={f} pct={pct} />
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function CoverageCell({ pct }: { pct: number }) {
  // Цветовая шкала: 0% red → 50% amber → 100% emerald
  let bg: string, fg: string
  if (pct >= 90) { bg = 'bg-emerald-900/60'; fg = 'text-emerald-200' }
  else if (pct >= 70) { bg = 'bg-emerald-900/30'; fg = 'text-emerald-300' }
  else if (pct >= 40) { bg = 'bg-amber-900/40'; fg = 'text-amber-300' }
  else if (pct > 0)   { bg = 'bg-red-900/40';   fg = 'text-red-300' }
  else                { bg = 'bg-gray-800';     fg = 'text-gray-600' }
  return (
    <td className={clsx('px-2 py-2 text-center font-mono', bg, fg)}>
      {pct === 0 ? '—' : `${Math.round(pct)}%`}
    </td>
  )
}
