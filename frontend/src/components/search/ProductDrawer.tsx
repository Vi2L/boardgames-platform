import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, ExternalLink, BookOpen, Star, Package, Hash } from 'lucide-react'
import clsx from 'clsx'
import type { ProductOut } from '../../types/api'
import { fetchHistory } from '../../lib/api'
import { PriceChart } from '../shared/PriceChart'
import { JsonViewer } from '../shared/JsonViewer'

interface Props {
  product: ProductOut | null
  onClose: () => void
}

const STORE_LABELS: Record<string, string> = {
  hobbygames: 'HobbyGames',
  lavkaigr: 'Лавка Игр',
  gaga: 'GaGa.ru',
}

const STORE_COLORS: Record<string, string> = {
  hobbygames: 'bg-blue-900 text-blue-300',
  lavkaigr:   'bg-green-900 text-green-300',
  gaga:       'bg-orange-900 text-orange-300',
}

function Badge({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs', className)}>
      {children}
    </span>
  )
}

export function ProductDrawer({ product, onClose }: Props) {
  // Закрытие по Esc
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const { data: history = [] } = useQuery({
    queryKey: ['history', product?.id],
    queryFn: () => fetchHistory(product!.id),
    enabled: !!product,
    staleTime: 60_000,
  })

  if (!product) return null

  const gallery: string[] = (product.extra?.gallery as string[]) ?? []
  const rating = product.extra?.rating as string | undefined
  const reviewCount = product.extra?.review_count as string | undefined
  const sku = product.extra?.sku as string | undefined
  const availability = product.extra?.availability as boolean | undefined
  const complexity = product.extra?.complexity as string | undefined

  // Правила: у разных магазинов разный формат
  const rulesRaw = product.extra?.rules
  const rules: Array<{ url: string; name: string }> = Array.isArray(rulesRaw)
    ? rulesRaw.map(r =>
        typeof r === 'string' ? { url: r, name: r.split('/').pop() ?? 'PDF' } : r as { url: string; name: string }
      )
    : []

  const hasExtra = Object.keys(product.extra).length > 0

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full max-w-xl bg-gray-900 border-l border-gray-800 z-50 overflow-y-auto shadow-2xl">
        <div className="sticky top-0 bg-gray-900 border-b border-gray-800 px-5 py-3 flex items-center justify-between z-10">
          <span className={clsx('text-xs font-mono px-2 py-0.5 rounded', STORE_COLORS[product.store_slug] ?? 'bg-gray-800 text-gray-300')}>
            {STORE_LABELS[product.store_slug] ?? product.store_slug}
          </span>
          <button onClick={onClose} className="p-1 rounded text-gray-500 hover:text-gray-300 hover:bg-gray-800">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Header */}
          <div className="flex gap-4">
            {(product.image_url_hd ?? product.image_url) && (
              <img
                src={product.image_url_hd ?? product.image_url ?? ''}
                alt={product.title}
                className="w-24 h-24 object-contain rounded bg-gray-800 flex-shrink-0"
                onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
              />
            )}
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-semibold text-gray-100 leading-tight">{product.title}</h2>
              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                <span className="text-2xl font-bold text-green-400">
                  {product.price_rub.toLocaleString('ru-RU', { minimumFractionDigits: 0 })} ₽
                </span>
                {rating && (
                  <Badge className="bg-yellow-950 text-yellow-400">
                    <Star size={10} fill="currentColor" /> {rating}
                    {reviewCount && <span className="text-gray-500">({reviewCount})</span>}
                  </Badge>
                )}
                {availability === true && <Badge className="bg-green-950 text-green-400">В наличии</Badge>}
                {availability === false && <Badge className="bg-red-950 text-red-400">Нет в наличии</Badge>}
              </div>
            </div>
          </div>

          {/* Параметры */}
          <div className="flex flex-wrap gap-2">
            {product.players && <Badge className="bg-gray-800 text-gray-300">👥 {product.players} игроков</Badge>}
            {product.age_min != null && <Badge className="bg-gray-800 text-gray-300">🎂 {product.age_min}+</Badge>}
            {product.playtime && <Badge className="bg-gray-800 text-gray-300">⏱ {product.playtime}</Badge>}
            {complexity && <Badge className="bg-gray-800 text-gray-300">🎯 {complexity}</Badge>}
            {sku && <Badge className="bg-gray-800 text-gray-400"><Hash size={10} /> {sku}</Badge>}
          </div>

          {/* Описание */}
          {product.description && (
            <p className="text-sm text-gray-300 leading-relaxed">{product.description}</p>
          )}

          {/* Ссылка */}
          <a
            href={product.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-sm text-violet-400 hover:text-violet-300 w-fit"
          >
            <ExternalLink size={13} /> Открыть в магазине
          </a>

          {/* Галерея */}
          {gallery.length > 0 && (
            <div>
              <div className="text-xs text-gray-500 mb-2">Галерея ({gallery.length})</div>
              <div className="flex gap-2 overflow-x-auto pb-2">
                {gallery.slice(0, 12).map((url, i) => (
                  <a key={i} href={url} target="_blank" rel="noopener noreferrer">
                    <img
                      src={url}
                      alt=""
                      className="h-20 w-20 object-cover rounded flex-shrink-0 bg-gray-800 hover:opacity-80"
                      onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Правила */}
          {rules.length > 0 && (
            <div>
              <div className="text-xs text-gray-500 mb-2">Правила</div>
              <div className="space-y-1">
                {rules.map((r, i) => (
                  <a
                    key={i}
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm text-violet-400 hover:text-violet-300"
                  >
                    <BookOpen size={12} /> {r.name}
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* История цен */}
          <div>
            <div className="text-sm font-medium text-gray-300 mb-2">
              История цен
              {history.length > 0 && <span className="text-gray-500 font-normal ml-2 text-xs">({history.length} точек)</span>}
            </div>
            <PriceChart data={history} />
          </div>

          {/* Extra raw data */}
          {hasExtra && (
            <div>
              <div className="text-xs text-gray-500 mb-2 flex items-center gap-1">
                <Package size={11} /> Extra данные
              </div>
              <JsonViewer data={product.extra} maxHeight={300} />
            </div>
          )}
        </div>
      </div>
    </>
  )
}
