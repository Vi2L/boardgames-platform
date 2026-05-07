/**
 * ProductsBrowserTab — браузер товаров parsers БД с возможностью
 * удалять кривые observations.
 *
 * Поток:
 *  1) Поиск/фильтр товаров parsers БД (по магазину и q).
 *  2) Клик по строке открывает inline-секцию с наблюдениями.
 *  3) Каждое observation — Delete-кнопка с confirm.
 *
 * После удаления invalidates ['parsers-db'] чтобы Inventory/Analytics
 * показали актуальные счётчики.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Loader2, Trash2, ChevronDown, ChevronRight, ExternalLink, Filter,
} from 'lucide-react'
import clsx from 'clsx'
import {
  fetchParsersDbProducts, fetchParsersDbProduct, deleteParsersObservation,
  fetchParsers,
} from '../../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../../lib/stores'

const PAGE_SIZE = 50

export function ProductsBrowserTab() {
  const [store, setStore] = useState('')
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)

  const parsers = useQuery({ queryKey: ['parsers'], queryFn: fetchParsers })
  const list = useQuery({
    queryKey: ['parsers-db', 'products', store, q],
    queryFn: () => fetchParsersDbProducts({
      store: store || undefined,
      q: q || undefined,
      limit: PAGE_SIZE,
    }),
    placeholderData: (prev) => prev,
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <Filter size={12} className="text-gray-500" />
        <select
          value={store}
          onChange={e => setStore(e.target.value)}
          className="px-2 py-1 text-xs bg-gray-800 border border-gray-700 rounded text-gray-200"
        >
          <option value="">все магазины</option>
          {parsers.data?.map(p => (
            <option key={p.slug} value={p.slug}>{getStoreLabel(p.slug, p.name)}</option>
          ))}
        </select>
        <input
          type="text"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="title (LIKE %x%)…"
          className="px-2 py-1 text-xs bg-gray-800 border border-gray-700 rounded text-gray-200 placeholder-gray-500 w-64"
        />
        <span className="text-xs text-gray-500 ml-auto">
          {list.data ? `${list.data.total.toLocaleString()} товаров (показано ${list.data.items.length})` : '...'}
        </span>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-950 text-gray-500 text-left">
            <tr>
              <th className="px-3 py-2 w-8"></th>
              <th className="px-3 py-2">id</th>
              <th className="px-3 py-2">магазин</th>
              <th className="px-3 py-2">название</th>
              <th className="px-3 py-2 text-right">last ₽</th>
              <th className="px-3 py-2 text-right">обновлено</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {list.data?.items.map(p => (
              <ProductRow
                key={p.id} p={p}
                expanded={openId === p.id}
                onToggle={() => setOpenId(openId === p.id ? null : p.id)}
              />
            ))}
            {(!list.data || list.data.items.length === 0) && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-500">
                {list.isLoading ? 'загрузка…' : 'Ничего не найдено.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ProductRow({
  p, expanded, onToggle,
}: {
  p: { id: number; store_slug: string; title: string; url: string;
       last_price: number | null; last_fetched_at: string | null }
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr className="hover:bg-gray-850 cursor-pointer" onClick={onToggle}>
        <td className="px-3 py-2 text-gray-500">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </td>
        <td className="px-3 py-2 font-mono text-gray-500">#{p.id}</td>
        <td className="px-3 py-2">
          <span className={clsx('px-1.5 py-0.5 rounded font-mono', getStoreBadgeColor(p.store_slug))}>
            {getStoreLabel(p.store_slug)}
          </span>
        </td>
        <td className="px-3 py-2 text-gray-200 truncate max-w-md" title={p.title}>
          <a href={p.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
             className="hover:text-violet-300 inline-flex items-center gap-1">
            {p.title} <ExternalLink size={10} className="opacity-50" />
          </a>
        </td>
        <td className="px-3 py-2 text-right font-mono text-emerald-400">
          {p.last_price != null ? Math.round(p.last_price / 100).toLocaleString() : '—'}
        </td>
        <td className="px-3 py-2 text-right font-mono text-gray-500">
          {p.last_fetched_at ? p.last_fetched_at.slice(0, 10) : '—'}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} className="px-3 py-3 bg-gray-950/40">
            <ObservationsList productId={p.id} />
          </td>
        </tr>
      )}
    </>
  )
}

function ObservationsList({ productId }: { productId: number }) {
  const queryClient = useQueryClient()
  const detail = useQuery({
    queryKey: ['parsers-db', 'product-detail', productId],
    queryFn: () => fetchParsersDbProduct(productId),
  })
  const remove = useMutation({
    mutationFn: (id: number) => deleteParsersObservation(id),
    onSuccess: () => {
      toast.success('Наблюдение удалено')
      queryClient.invalidateQueries({ queryKey: ['parsers-db'] })
    },
    onError: (e) => toast.error(`Не удалось удалить: ${e}`),
  })

  if (detail.isLoading) {
    return <div className="text-xs text-gray-500 flex items-center gap-2">
      <Loader2 size={11} className="animate-spin" /> загрузка наблюдений…
    </div>
  }
  if (!detail.data) return <div className="text-xs text-red-400">Ошибка</div>

  const obs = detail.data.observations ?? []
  if (obs.length === 0) {
    return <div className="text-xs text-gray-500">Наблюдений пока нет.</div>
  }

  return (
    <div className="space-y-1">
      <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
        История ({obs.length}). Удаление — необратимо.
      </div>
      <div className="bg-gray-900 rounded border border-gray-800 max-h-72 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-950 text-gray-500 text-left">
            <tr>
              <th className="px-3 py-1.5">obs id</th>
              <th className="px-3 py-1.5">время</th>
              <th className="px-3 py-1.5 text-right">цена ₽</th>
              <th className="px-3 py-1.5 w-10"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {obs.map(o => (
              <tr key={o.id} className="hover:bg-gray-850">
                <td className="px-3 py-1.5 font-mono text-gray-500">{o.id}</td>
                <td className="px-3 py-1.5 font-mono text-gray-400">
                  {new Date(o.fetched_at).toLocaleString('ru-RU', { hour12: false })}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-emerald-400">
                  {Math.round(o.price / 100).toLocaleString()}
                </td>
                <td className="px-3 py-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Удалить observation #${o.id} (${Math.round(o.price / 100)} ₽)?`))
                        remove.mutate(o.id)
                    }}
                    disabled={remove.isPending}
                    className="p-1 text-gray-500 hover:text-red-400 hover:bg-red-950/40 rounded"
                    title="Удалить эту запись"
                  >
                    {remove.isPending ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
