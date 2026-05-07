/**
 * CatalogPage — UI поверх boardgames-catalog (~/Projects/boardgames-catalog).
 *
 * Две секции:
 * 1. «Каталог»  — поиск + список Game (pg_trgm fuzzy через q).
 * 2. «Матчинг»  — очередь unmatched-оффер'ов с действиями [Связать]/[Отклонить].
 *
 * Намеренно простой layout (без drag&drop / modal'ок): прототип ручного
 * матчинга, нагружать визуалом будем по мере живого использования.
 */
import { useState } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  fetchCatalogHealth,
  fetchMatchingQueue,
  linkOffer,
  listCatalogGames,
  rejectOffer,
  type CatalogGame,
  type CatalogOffer,
} from '../lib/catalog'
import { GameDetailDrawer } from '../components/catalog/GameDetailDrawer'

type Tab = 'catalog' | 'matching'

export function CatalogPage() {
  const [tab, setTab] = useState<Tab>('catalog')
  const health = useQuery({
    queryKey: ['catalog', 'health'],
    queryFn: fetchCatalogHealth,
    refetchInterval: 30_000,
    retry: 0,
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-100">Каталог настольных игр</h1>
        <div className="text-xs text-gray-400">
          catalog: {health.isError ? <span className="text-red-400">недоступен</span> :
            health.data ? <span className="text-emerald-400">{health.data.status}</span> :
            <span>...</span>}
        </div>
      </div>

      <div className="flex gap-2 border-b border-gray-800">
        {(['catalog', 'matching'] as Tab[]).map(t => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm transition-colors ${
              tab === t
                ? 'text-violet-300 border-b-2 border-violet-500'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {t === 'catalog' ? 'Каталог' : 'Очередь матчинга'}
          </button>
        ))}
      </div>

      {tab === 'catalog' ? <CatalogSection /> : <MatchingSection />}
    </div>
  )
}

// ─── Каталог ──────────────────────────────────────────────────────────────

function CatalogSection() {
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const games = useQuery({
    queryKey: ['catalog', 'games', q],
    queryFn: () => listCatalogGames(q || undefined, 50, 0),
  })

  return (
    <div className="space-y-3">
      <input
        type="text"
        placeholder="Поиск по названию (pg_trgm fuzzy: «каркасон» найдёт «Каркассон»)"
        value={q}
        onChange={e => setQ(e.target.value)}
        className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded text-sm text-gray-100 placeholder-gray-500 focus:border-violet-500 focus:outline-none"
      />
      {games.isError && (
        <div className="text-sm text-red-400">Не удалось получить каталог: {String(games.error)}</div>
      )}
      <div className="text-xs text-gray-500">
        {games.data ? `${games.data.total} игр в каталоге` : 'загрузка...'}
      </div>
      <div className="border border-gray-800 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2">id</th>
              <th className="px-3 py-2">slug</th>
              <th className="px-3 py-2">title</th>
              <th className="px-3 py-2">year</th>
              <th className="px-3 py-2">source</th>
              <th className="px-3 py-2">BGG / Tesera</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {games.data?.items.map(g => (
              <GameRow key={g.id} g={g} onOpen={() => setOpenId(g.id)} />
            ))}
            {games.data?.items.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-500">
                Нет игр {q && <>по запросу «{q}»</>}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {openId !== null && (
        <GameDetailDrawer gameId={openId} onClose={() => setOpenId(null)} />
      )}
    </div>
  )
}

function GameRow({ g, onOpen }: { g: CatalogGame; onOpen: () => void }) {
  return (
    <tr className="hover:bg-gray-900 cursor-pointer" onClick={onOpen}>
      <td className="px-3 py-2 font-mono text-xs text-gray-500">{g.id}</td>
      <td className="px-3 py-2 font-mono text-xs text-gray-400">{g.slug}</td>
      <td className="px-3 py-2 text-gray-100">{g.title}</td>
      <td className="px-3 py-2 text-gray-300">{g.year ?? '—'}</td>
      <td className="px-3 py-2"><SourceBadge source={g.source} /></td>
      <td className="px-3 py-2 text-xs text-gray-400">
        {g.bgg_id && <span title="BGG">BGG#{g.bgg_id}</span>}
        {g.bgg_id && g.tesera_id && ' · '}
        {g.tesera_id && <span title="Tesera">T#{g.tesera_id}</span>}
        {!g.bgg_id && !g.tesera_id && '—'}
      </td>
    </tr>
  )
}

function SourceBadge({ source }: { source: string }) {
  const colors: Record<string, string> = {
    manual: 'bg-gray-800 text-gray-300',
    bgg: 'bg-orange-900/50 text-orange-300',
    tesera: 'bg-blue-900/50 text-blue-300',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${colors[source] || 'bg-gray-800 text-gray-300'}`}>
      {source}
    </span>
  )
}

// ─── Очередь матчинга ─────────────────────────────────────────────────────

function MatchingSection() {
  const queryClient = useQueryClient()
  const queue = useQuery({
    queryKey: ['catalog', 'matching-queue'],
    queryFn: () => fetchMatchingQueue(undefined, 100, 0),
  })

  const reject = useMutation({
    mutationFn: rejectOffer,
    onSuccess: () => {
      toast.success('Оффер отклонён')
      queryClient.invalidateQueries({ queryKey: ['catalog', 'matching-queue'] })
    },
    onError: (e) => toast.error(`Не удалось отклонить: ${e}`),
  })

  return (
    <div className="space-y-3">
      <div className="text-xs text-gray-500">
        {queue.data
          ? `${queue.data.total} unmatched-оффер'ов в очереди (сортировка по match_score)`
          : 'загрузка...'}
      </div>
      <div className="border border-gray-800 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2">store</th>
              <th className="px-3 py-2">title_raw</th>
              <th className="px-3 py-2">price</th>
              <th className="px-3 py-2">score</th>
              <th className="px-3 py-2">действия</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {queue.data?.items.map(o => (
              <OfferRow
                key={o.id}
                o={o}
                onLinked={() => queryClient.invalidateQueries({ queryKey: ['catalog', 'matching-queue'] })}
                onReject={() => reject.mutate(o.id)}
              />
            ))}
            {queue.data?.items.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-500">
                Очередь пуста — все оффер'ы сматчены или отклонены.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function OfferRow({
  o, onLinked, onReject,
}: {
  o: CatalogOffer
  onLinked: () => void
  onReject: () => void
}) {
  const [linkOpen, setLinkOpen] = useState(false)
  return (
    <>
      <tr className="hover:bg-gray-900">
        <td className="px-3 py-2 text-xs font-mono text-gray-400">{o.store_slug}</td>
        <td className="px-3 py-2 text-gray-100">
          <a href={o.url} target="_blank" rel="noreferrer" className="hover:text-violet-300">
            {o.title_raw}
          </a>
        </td>
        <td className="px-3 py-2 text-gray-300">
          {o.last_price ? `${(o.last_price / 100).toFixed(0)} ₽` : '—'}
        </td>
        <td className="px-3 py-2 text-xs text-gray-400">
          {o.match_score != null ? o.match_score.toFixed(2) : '—'}
        </td>
        <td className="px-3 py-2 space-x-2">
          <button
            type="button"
            onClick={() => setLinkOpen(v => !v)}
            className="px-2 py-1 text-xs bg-violet-900/50 text-violet-200 rounded hover:bg-violet-900"
          >
            Связать
          </button>
          <button
            type="button"
            onClick={onReject}
            className="px-2 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700"
          >
            Отклонить
          </button>
        </td>
      </tr>
      {linkOpen && (
        <tr className="bg-gray-950">
          <td colSpan={5} className="px-3 py-3 border-t border-gray-800">
            <LinkPicker offer={o} onLinked={() => { setLinkOpen(false); onLinked() }} />
          </td>
        </tr>
      )}
    </>
  )
}

function LinkPicker({ offer, onLinked }: { offer: CatalogOffer; onLinked: () => void }) {
  const [q, setQ] = useState(offer.title_raw)
  const games = useQuery({
    queryKey: ['catalog', 'link-picker', q],
    queryFn: () => listCatalogGames(q || undefined, 10, 0),
  })
  const link = useMutation({
    mutationFn: (gameId: number) => linkOffer(offer.id, gameId),
    onSuccess: () => { toast.success('Оффер связан с игрой'); onLinked() },
    onError: (e) => toast.error(`Не удалось связать: ${e}`),
  })

  return (
    <div className="space-y-2">
      <input
        type="text"
        value={q}
        onChange={e => setQ(e.target.value)}
        placeholder="Найти игру в каталоге..."
        className="w-full px-2 py-1 text-sm bg-gray-900 border border-gray-700 rounded text-gray-100"
      />
      <div className="space-y-1">
        {games.data?.items.map(g => (
          <button
            key={g.id}
            type="button"
            disabled={link.isPending}
            onClick={() => link.mutate(g.id)}
            className="w-full text-left px-2 py-1 text-sm bg-gray-900 hover:bg-gray-800 rounded text-gray-200 disabled:opacity-50"
          >
            <span className="font-mono text-xs text-gray-500 mr-2">#{g.id}</span>
            {g.title}
            {g.year && <span className="text-xs text-gray-500 ml-2">({g.year})</span>}
          </button>
        ))}
        {games.data?.items.length === 0 && (
          <div className="text-xs text-gray-500 px-2 py-1">
            Игра не найдена. Создайте её через POST /games или импортируйте из BGG/Tesera.
          </div>
        )}
      </div>
    </div>
  )
}
