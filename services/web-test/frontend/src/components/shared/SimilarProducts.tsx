import { useMemo } from 'react'
import { ArrowRight } from 'lucide-react'
import clsx from 'clsx'
import type { ProductOut } from '../../types/api'
import { tokenize, jaccardSimilarity } from '../../lib/similarity'
import { getStoreBadgeColor, getStoreLabel } from '../../lib/stores'

interface Props {
  /** Текущий продукт, для которого ищем аналоги. */
  current: ProductOut
  /** Полный список результатов текущего поиска (все магазины). */
  pool: ProductOut[]
  /** Минимальный Jaccard для попадания в список (0..1). По умолчанию 0.5. */
  threshold?: number
  /** Колбэк на клик по найденному аналогу. */
  onSelect: (product: ProductOut) => void
}

/**
 * Мини-таблица «Этот товар в других магазинах».
 *
 * Алгоритм: токенизируем title текущего товара (см. lib/similarity.ts),
 * считаем Jaccard со всеми остальными товарами в pool. Берём те, что:
 *  - из другого магазина (`store_slug !== current.store_slug`);
 *  - выше threshold;
 *  - сортируем по убыванию похожести.
 *
 * Дешёво: O(N · |tokens|), N редко больше 50 в одном поиске.
 */
export function SimilarProducts({ current, pool, threshold = 0.5, onSelect }: Props) {
  const matches = useMemo(() => {
    const currentTokens = tokenize(current.title)
    if (currentTokens.size === 0) return []

    const scored = pool
      .filter(p => p.id !== current.id && p.store_slug !== current.store_slug)
      .map(p => ({ product: p, score: jaccardSimilarity(currentTokens, tokenize(p.title)) }))
      .filter(x => x.score >= threshold)

    scored.sort((a, b) => b.score - a.score)
    return scored
  }, [current, pool, threshold])

  if (matches.length === 0) return null

  // Самая низкая цена среди аналогов и текущего — используется для подсветки
  const minPrice = Math.min(current.price_rub, ...matches.map(m => m.product.price_rub))

  return (
    <div>
      <div className="text-xs text-gray-500 mb-2">
        В других магазинах ({matches.length})
      </div>
      <div className="space-y-1">
        {matches.map(({ product: p, score }) => {
          const isLowest = p.price_rub === minPrice
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => onSelect(p)}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-gray-800/50 hover:bg-gray-800 text-left transition-colors"
            >
              <span className={clsx('px-2 py-0.5 rounded text-xs font-mono whitespace-nowrap', getStoreBadgeColor(p.store_slug))}>
                {getStoreLabel(p.store_slug)}
              </span>
              <span className="flex-1 min-w-0 text-sm text-gray-300 truncate" title={p.title}>
                {p.title}
              </span>
              <span className={clsx(
                'whitespace-nowrap font-semibold text-sm',
                isLowest ? 'text-green-400' : 'text-gray-300',
              )}>
                {p.price_rub.toLocaleString('ru-RU')} ₽
              </span>
              <span className="text-xs text-gray-600 font-mono w-10 text-right" title={`Похожесть ${Math.round(score * 100)}%`}>
                {Math.round(score * 100)}%
              </span>
              <ArrowRight size={12} className="text-gray-500" />
            </button>
          )
        })}
      </div>
    </div>
  )
}
