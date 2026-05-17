/**
 * MergeDialog — объединение двух игр в каталоге.
 *
 * Поток: source (текущая игра, из которой открыли диалог) → target
 * (выбирается через fuzzy-search). После confirm: вызов
 * POST /api/catalog/games/merge, показ статистики (offers_moved,
 * aliases_moved, aliases_skipped_dup), инвалидация query cache.
 *
 * Защиты: source==target отбивается с предупреждением, double-click
 * на «Слить» не сработает (mutation disabled на pending).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { X, GitMerge, Loader2, AlertTriangle, CheckCircle2 } from 'lucide-react'
import {
  listCatalogGames, mergeGames,
  type CatalogGame, type CatalogGameDetail, type GameMergeResult,
} from '../../lib/catalog'

interface Props {
  source: CatalogGameDetail
  onClose: () => void
}

export function MergeDialog({ source, onClose }: Props) {
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<CatalogGame | null>(null)
  const [result, setResult] = useState<GameMergeResult | null>(null)
  const queryClient = useQueryClient()

  const games = useQuery({
    queryKey: ['catalog', 'merge-picker', q],
    queryFn: () => listCatalogGames(q || undefined, 10, 0),
    enabled: !!q.trim() && !result,
  })

  const merge = useMutation({
    mutationFn: () => mergeGames(source.id, picked!.id),
    onSuccess: (r) => {
      setResult(r)
      toast.success(`Объединено: offers ${r.offers_moved}, aliases ${r.aliases_moved}`)
      queryClient.invalidateQueries({ queryKey: ['catalog', 'games'] })
      queryClient.invalidateQueries({ queryKey: ['catalog', 'game-detail', source.id] })
      queryClient.invalidateQueries({ queryKey: ['catalog', 'game-detail', picked!.id] })
    },
    onError: (e) => toast.error(`Не удалось объединить: ${e}`),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-gray-900 border border-gray-800 rounded-lg shadow-2xl w-[min(640px,100%)] max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <h2 className="text-sm font-semibold text-gray-100 flex items-center gap-2">
            <GitMerge size={14} /> Объединить игры
          </h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {!result ? (
            <>
              <div className="bg-amber-950/30 border border-amber-900/50 rounded p-2 text-xs text-amber-300 flex gap-2">
                <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
                <div>
                  Source-игра останется в БД со status='merged' и meta.merged_into=target_id.
                  Все её offers и aliases переедут на target.
                </div>
              </div>

              <div className="bg-gray-950 rounded p-2 space-y-1">
                <div className="text-[10px] text-gray-500 uppercase">Source (что объединяем)</div>
                <div className="text-sm text-gray-100">{source.title}</div>
                <div className="text-xs font-mono text-gray-500">#{source.id} · {source.slug}</div>
              </div>

              <div className="bg-gray-950 rounded p-2 space-y-2">
                <div className="text-[10px] text-gray-500 uppercase">Target (с чем объединяем)</div>
                {picked ? (
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm text-gray-100">{picked.title}</div>
                      <div className="text-xs font-mono text-gray-500">#{picked.id} · {picked.slug}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setPicked(null)}
                      className="text-xs text-indigo-300 hover:underline"
                    >
                      сменить
                    </button>
                  </div>
                ) : (
                  <>
                    <input
                      type="text"
                      value={q}
                      onChange={e => setQ(e.target.value)}
                      placeholder="Найти target по названию (fuzzy)…"
                      className="w-full px-2 py-1 text-sm bg-gray-900 border border-gray-700 rounded text-gray-100"
                    />
                    {games.data && games.data.items.length > 0 && (
                      <div className="space-y-1">
                        {games.data.items
                          .filter(g => g.id !== source.id)
                          .map(g => (
                            <button
                              key={g.id}
                              type="button"
                              onClick={() => setPicked(g)}
                              className="w-full text-left px-2 py-1.5 text-sm bg-gray-900 hover:bg-gray-800 rounded text-gray-200 flex items-center gap-2"
                            >
                              <span className="font-mono text-xs text-gray-500">#{g.id}</span>
                              <span className="truncate flex-1">{g.title}</span>
                              {g.year && <span className="text-xs text-gray-500">{g.year}</span>}
                            </button>
                          ))}
                      </div>
                    )}
                  </>
                )}
              </div>

              <button
                type="button"
                onClick={() => {
                  if (!picked) return
                  if (!window.confirm(
                    `Объединить «${source.title}» (#${source.id}) → «${picked.title}» (#${picked.id})?\n\n` +
                    'Действие необратимо без manual работы с БД.',
                  )) return
                  merge.mutate()
                }}
                disabled={!picked || merge.isPending}
                className="w-full px-4 py-2 rounded text-sm font-medium flex items-center justify-center gap-2 bg-red-700 hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed text-white"
              >
                {merge.isPending
                  ? <><Loader2 size={13} className="animate-spin" /> Объединяю…</>
                  : <><GitMerge size={13} /> Объединить</>}
              </button>
            </>
          ) : (
            <div className="space-y-3">
              <div className="bg-emerald-950/40 border border-emerald-900/50 rounded p-3 text-emerald-200 flex items-start gap-2">
                <CheckCircle2 size={16} className="text-emerald-400 mt-0.5 flex-shrink-0" />
                <div>
                  <div className="font-medium">Объединение выполнено</div>
                  <div className="text-xs text-emerald-300/80 mt-1 font-mono">
                    #{result.source_id} → #{result.target_id}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <Stat value={result.offers_moved} label="offers перемещено" />
                <Stat value={result.aliases_moved} label="aliases перемещено" />
                <Stat value={result.aliases_skipped_dup} label="aliases-дубликаты" />
              </div>
              <button
                type="button"
                onClick={onClose}
                className="w-full px-3 py-1.5 text-xs bg-indigo-700 hover:bg-indigo-600 text-white rounded"
              >
                Закрыть
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="bg-gray-950 rounded p-2">
      <div className="text-lg font-mono text-gray-100">{value}</div>
      <div className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</div>
    </div>
  )
}
