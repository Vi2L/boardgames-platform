import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { X, ExternalLink as LinkIcon } from 'lucide-react'
import clsx from 'clsx'
import type { ProductOut } from '../../types/api'
import { getStoreBadgeColor, getStoreLabel } from '../../lib/stores'
import { ProductDetail } from '../shared/ProductDetail'

interface Props {
  product: ProductOut | null
  /** Полный список результатов текущего поиска для SimilarProducts. */
  pool?: ProductOut[]
  onClose: () => void
  /** Открыть другой товар (из SimilarProducts). */
  onSelect?: (product: ProductOut) => void
}

/**
 * Боковая панель деталей товара. Открывается из ResultsTable; на узких
 * экранах разворачивается на весь экран.
 *
 * Логика отрисовки сама по себе — в `ProductDetail` (общий компонент с
 * ProductPage). Здесь только wrapper: оверлей, sticky-header с кнопкой
 * закрытия, hotkey Esc, ссылка «открыть как страницу».
 */
export function ProductDrawer({ product, pool = [], onClose, onSelect }: Props) {
  useEffect(() => {
    if (!product) return
    const handler = (e: KeyboardEvent) => {
      // Если открыт lightbox — он сам закроется по Esc. Drawer закрываем
      // только если в DOM нет lightbox-узла.
      const lightboxOpen = document.querySelector('[role="dialog"][aria-label="Просмотр галереи"]')
      if (e.key === 'Escape' && !lightboxOpen) onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [product, onClose])

  if (!product) return null

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />

      {/* Drawer — на мобильном full-screen, на md+ ширина 32rem */}
      <div className="fixed inset-0 md:inset-y-0 md:right-0 md:left-auto md:w-full md:max-w-xl bg-gray-900 md:border-l border-gray-800 z-40 overflow-y-auto shadow-2xl">
        <div className="sticky top-0 bg-gray-900 border-b border-gray-800 px-5 py-3 flex items-center justify-between gap-3 z-10">
          <span className={clsx('text-xs font-mono px-2 py-0.5 rounded', getStoreBadgeColor(product.store_slug))}>
            {getStoreLabel(product.store_slug)}
          </span>
          <div className="flex items-center gap-2">
            <Link
              to={`/products/${product.id}`}
              className="text-xs text-violet-400 hover:text-violet-300 flex items-center gap-1"
              title="Открыть как страницу"
              onClick={onClose}
            >
              <LinkIcon size={12} /> страница
            </Link>
            <button
              onClick={onClose}
              className="p-1 rounded text-gray-500 hover:text-gray-300 hover:bg-gray-800"
              title="Закрыть (Esc)"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="p-5">
          <ProductDetail
            product={product}
            pool={pool}
            onSelectSimilar={onSelect}
          />
        </div>
      </div>
    </>
  )
}
