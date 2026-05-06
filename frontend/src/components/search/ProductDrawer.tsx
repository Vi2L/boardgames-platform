import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  X, ExternalLink, BookOpen, Star, Package, Hash,
  Box, Scale, Globe, Award, TrendingDown, TrendingUp,
} from 'lucide-react'
import clsx from 'clsx'
import type { ProductOut, ProductRule } from '../../types/api'
import { fetchHistory } from '../../lib/api'
import { getStoreBadgeColor, getStoreLabel } from '../../lib/stores'
import { PriceChart } from '../shared/PriceChart'
import { JsonViewer } from '../shared/JsonViewer'
import { Lightbox } from '../shared/Lightbox'
import { SimilarProducts } from '../shared/SimilarProducts'

interface Props {
  product: ProductOut | null
  /** Полный список результатов текущего поиска для SimilarProducts. */
  pool?: ProductOut[]
  onClose: () => void
  /** Открыть другой товар (из SimilarProducts). */
  onSelect?: (product: ProductOut) => void
}

function Badge({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs', className)}>
      {children}
    </span>
  )
}

const formatRub = (v: number) => `${v.toLocaleString('ru-RU')} ₽`

export function ProductDrawer({ product, pool = [], onClose, onSelect }: Props) {
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)

  // Закрытие по Esc — но только если lightbox закрыт (он сам ловит Esc).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && lightboxIndex === null) onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose, lightboxIndex])

  const { data: history = [] } = useQuery({
    queryKey: ['history', product?.id],
    queryFn: () => fetchHistory(product!.id),
    enabled: !!product,
    staleTime: 60_000,
  })

  // Min/max за последние 30 дней — для бейджа рядом с текущей ценой.
  // useMemo: history — стабильный, пересчёт только при смене.
  const last30 = useMemo(() => {
    if (history.length === 0) return null
    const cutoff = Date.now() - 30 * 86_400_000
    const recent = history.filter(p => new Date(p.fetched_at).getTime() >= cutoff)
    if (recent.length === 0) return null
    const prices = recent.map(p => p.price_rub)
    return { min: Math.min(...prices), max: Math.max(...prices), count: recent.length }
  }, [history])

  if (!product) return null

  // ── Извлечение полей extra ──────────────────────────────────────────────
  const extra = product.extra
  const gallery: string[] = extra.gallery ?? []
  const rating = extra.rating
  const reviewCount = extra.review_count
  const ranking = extra.ranking
  const sku = extra.sku
  const complexity = extra.complexity
  const tags = extra.tags ?? []
  const language = extra.language
  const dimensions = extra.dimensions
  const weight = extra.weight
  const offlinePriceKop = extra.offline_price
  // Унификация наличия: HobbyGames даёт `availability`, CrowdGames — `in_stock`.
  const inStock = extra.availability ?? extra.in_stock

  // Состав может быть массивом или строкой — нормализуем для рендера.
  const composition: string[] = Array.isArray(extra.composition)
    ? extra.composition
    : (typeof extra.composition === 'string' && extra.composition.trim()
        ? [extra.composition]
        : [])

  // Правила: у разных магазинов разный формат (массив строк vs массив объектов).
  const rulesRaw = extra.rules
  const rules: ProductRule[] = Array.isArray(rulesRaw)
    ? rulesRaw.map((r): ProductRule =>
        typeof r === 'string' ? { url: r, name: r.split('/').pop() ?? 'PDF' } : r
      )
    : []

  const hasExtra = Object.keys(extra).length > 0

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Drawer — на мобильном full-screen, на md+ ширина 32rem */}
      <div className="fixed inset-0 md:inset-y-0 md:right-0 md:left-auto md:w-full md:max-w-xl bg-gray-900 md:border-l border-gray-800 z-40 overflow-y-auto shadow-2xl">
        <div className="sticky top-0 bg-gray-900 border-b border-gray-800 px-5 py-3 flex items-center justify-between z-10">
          <span className={clsx('text-xs font-mono px-2 py-0.5 rounded', getStoreBadgeColor(product.store_slug))}>
            {getStoreLabel(product.store_slug)}
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded text-gray-500 hover:text-gray-300 hover:bg-gray-800"
            title="Закрыть (Esc)"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Header */}
          <div className="flex gap-4">
            {(product.image_url_hd ?? product.image_url) && (
              <button
                type="button"
                onClick={() => gallery.length > 0 && setLightboxIndex(0)}
                className="flex-shrink-0"
                title={gallery.length > 0 ? 'Открыть галерею' : undefined}
              >
                <img
                  src={product.image_url_hd ?? product.image_url ?? ''}
                  alt={product.title}
                  className={clsx(
                    'w-24 h-24 object-contain rounded bg-gray-800',
                    gallery.length > 0 && 'cursor-zoom-in hover:opacity-80',
                  )}
                  onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                />
              </button>
            )}
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-semibold text-gray-100 leading-tight">{product.title}</h2>
              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                <span className="text-2xl font-bold text-green-400">
                  {formatRub(product.price_rub)}
                </span>
                {offlinePriceKop != null && (
                  <Badge className="bg-gray-800 text-gray-400" >
                    офлайн {formatRub(offlinePriceKop / 100)}
                  </Badge>
                )}
                {rating && (
                  <Badge className="bg-yellow-950 text-yellow-400">
                    <Star size={10} fill="currentColor" /> {rating}
                    {reviewCount && <span className="text-gray-500">({reviewCount})</span>}
                  </Badge>
                )}
                {ranking && (
                  <Badge className="bg-purple-950 text-purple-300">
                    <Award size={10} /> {ranking}
                  </Badge>
                )}
                {inStock === true && <Badge className="bg-green-950 text-green-400">В наличии</Badge>}
                {inStock === false && <Badge className="bg-red-950 text-red-400">Нет в наличии</Badge>}
              </div>

              {/* Min/max за 30 дн. */}
              {last30 && last30.count >= 2 && (
                <div className="text-xs text-gray-500 mt-2 flex items-center gap-3">
                  <span className="flex items-center gap-1">
                    <TrendingDown size={11} className="text-green-500" /> мин {formatRub(last30.min)}
                  </span>
                  <span className="flex items-center gap-1">
                    <TrendingUp size={11} className="text-red-500" /> макс {formatRub(last30.max)}
                  </span>
                  <span className="text-gray-600">за 30 дн.</span>
                </div>
              )}
            </div>
          </div>

          {/* Параметры */}
          <div className="flex flex-wrap gap-2">
            {product.players && <Badge className="bg-gray-800 text-gray-300">👥 {product.players} игроков</Badge>}
            {product.age_min != null && <Badge className="bg-gray-800 text-gray-300">🎂 {product.age_min}+</Badge>}
            {product.playtime && <Badge className="bg-gray-800 text-gray-300">⏱ {product.playtime}</Badge>}
            {complexity && <Badge className="bg-gray-800 text-gray-300">🎯 {complexity}</Badge>}
            {language && (
              <Badge className="bg-gray-800 text-gray-300">
                <Globe size={10} /> {language}
              </Badge>
            )}
            {sku && <Badge className="bg-gray-800 text-gray-400"><Hash size={10} /> {sku}</Badge>}
          </div>

          {/* Размер коробки и вес */}
          {(dimensions || weight) && (
            <div className="flex flex-wrap gap-3 text-xs text-gray-400">
              {dimensions && (
                <span className="flex items-center gap-1.5">
                  <Box size={12} /> {dimensions}
                </span>
              )}
              {weight && (
                <span className="flex items-center gap-1.5">
                  <Scale size={12} /> {weight}
                </span>
              )}
            </div>
          )}

          {/* Теги */}
          {tags.length > 0 && (
            <div>
              <div className="text-xs text-gray-500 mb-1.5">Теги</div>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((t, i) => (
                  <span key={`${t}-${i}`} className="px-2 py-0.5 rounded bg-gray-800 text-gray-300 text-xs">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Описание */}
          {product.description && (
            <p className="text-sm text-gray-300 leading-relaxed">{product.description}</p>
          )}

          {/* Состав */}
          {composition.length > 0 && (
            <div>
              <div className="text-xs text-gray-500 mb-1.5">Состав</div>
              <ul className="list-disc pl-5 text-sm text-gray-300 space-y-0.5">
                {composition.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
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
                {gallery.slice(0, 6).map((url, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setLightboxIndex(i)}
                    className="flex-shrink-0"
                  >
                    <img
                      src={url}
                      alt=""
                      className="h-20 w-20 object-cover rounded bg-gray-800 hover:opacity-80 cursor-zoom-in"
                      onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  </button>
                ))}
                {gallery.length > 6 && (
                  <button
                    type="button"
                    onClick={() => setLightboxIndex(6)}
                    className="flex-shrink-0 h-20 w-20 rounded bg-gray-800 text-gray-300 text-xs font-medium hover:bg-gray-700"
                  >
                    +{gallery.length - 6}
                  </button>
                )}
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

          {/* В других магазинах */}
          {pool.length > 0 && onSelect && (
            <SimilarProducts current={product} pool={pool} onSelect={onSelect} />
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
              <JsonViewer data={extra} maxHeight={300} />
            </div>
          )}
        </div>
      </div>

      {/* Lightbox для галереи */}
      {lightboxIndex !== null && gallery.length > 0 && (
        <Lightbox
          images={gallery}
          initialIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
        />
      )}
    </>
  )
}
