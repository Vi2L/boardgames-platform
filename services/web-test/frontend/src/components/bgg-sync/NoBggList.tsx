/**
 * NoBggList — игры из catalog'а без bgg_id.
 *
 * Назначение: оператор видит «недоматченные» к BGG canonical-игры, переходит
 * по ссылке в Catalog → BGG search → импортирует или связывает вручную.
 *
 * Использует существующий `/games?no_bgg=true` (миграция фильтра в Phase 5.3).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ExternalLink } from 'lucide-react'

import { listCatalogGames } from '../../lib/catalog'

export function NoBggList() {
  const [limit] = useState(50)
  const [offset, setOffset] = useState(0)

  const games = useQuery({
    queryKey: ['bgg-sync', 'no-bgg-games', limit, offset],
    queryFn: () => listCatalogGames(undefined, limit, offset, { no_bgg: true }),
  })

  if (games.isLoading) {
    return <div className="text-xs text-gray-500 py-4 flex items-center gap-2">
      <Loader2 size={12} className="animate-spin" /> Загружаю…
    </div>
  }
  if (games.isError) {
    return <div className="text-xs text-red-400 py-4">{(games.error as Error).message}</div>
  }

  const data = games.data
  if (!data || data.items.length === 0) {
    return (
      <div className="text-xs text-gray-500 py-6 text-center border border-dashed border-gray-800 rounded">
        Все игры в каталоге привязаны к BGG. 🎉
      </div>
    )
  }

  const totalPages = Math.ceil(data.total / limit)
  const currentPage = Math.floor(offset / limit) + 1

  return (
    <div className="space-y-3">
      <div className="text-xs text-gray-500">
        Всего без BGG ID: <span className="text-gray-300 font-mono">{data.total}</span> игр.
        Кликните «Найти» чтобы открыть BGG search в новой вкладке.
      </div>

      <div className="border border-gray-800 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 border-b border-gray-800 text-xs text-gray-400">
            <tr>
              <th className="text-left px-3 py-2 font-normal">ID</th>
              <th className="text-left px-3 py-2 font-normal">Название</th>
              <th className="text-left px-3 py-2 font-normal">Год</th>
              <th className="text-left px-3 py-2 font-normal">Источник</th>
              <th className="text-left px-3 py-2 font-normal">Tesera ID</th>
              <th className="text-right px-3 py-2 font-normal">Действия</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map(g => (
              <tr key={g.id} className="border-b border-gray-800 last:border-b-0 hover:bg-gray-900/40">
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{g.id}</td>
                <td className="px-3 py-2 text-gray-200">
                  {g.title_ru ?? g.title}
                  {g.title_ru && g.title_ru !== g.title && (
                    <div className="text-[10px] text-gray-500">{g.title}</div>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">{g.year ?? '—'}</td>
                <td className="px-3 py-2 text-[10px] text-gray-500 font-mono">{g.source}</td>
                <td className="px-3 py-2 text-xs text-gray-400 font-mono">{g.tesera_id ?? '—'}</td>
                <td className="px-3 py-2 text-right">
                  <a
                    href={`https://boardgamegeek.com/geeksearch.php?action=search&objecttype=boardgame&q=${encodeURIComponent(g.title)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded"
                  >
                    <ExternalLink size={11} />
                    Найти
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-gray-400">
          <button
            type="button"
            onClick={() => setOffset(o => Math.max(0, o - limit))}
            disabled={offset === 0}
            className="px-3 py-1 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 rounded"
          >
            ← Назад
          </button>
          <span>
            страница {currentPage} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setOffset(o => o + limit)}
            disabled={currentPage >= totalPages}
            className="px-3 py-1 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 rounded"
          >
            Вперёд →
          </button>
        </div>
      )}
    </div>
  )
}
