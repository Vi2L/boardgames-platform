import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink, Loader2, Share2, Check } from 'lucide-react'
import clsx from 'clsx'
import { fetchDbProduct } from '../lib/api'
import { getStoreBadgeColor, getStoreLabel } from '../lib/stores'
import { ProductDetail } from '../components/shared/ProductDetail'

/**
 * Полноценная страница товара. Открывается:
 *  - из ProductDrawer кнопкой «страница»;
 *  - по прямой ссылке `/products/:id` (deep-link для шаринга).
 *
 * Использует общий `ProductDetail`, добавляет шапку с кнопками «Назад» и
 * «Поделиться» (копирует URL в буфер).
 */
export function ProductPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [copied, setCopied] = useState(false)

  const productId = id ? Number(id) : NaN
  const isValidId = Number.isFinite(productId) && productId > 0

  const { data: product, isLoading, error } = useQuery({
    queryKey: ['db-product', productId],
    queryFn: () => fetchDbProduct(productId),
    enabled: isValidId,
    retry: 0,
  })

  const handleShare = () => {
    void navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  if (!isValidId) {
    return <ErrorState title="Некорректный ID товара" />
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-gray-500">
        <Loader2 size={14} className="animate-spin" /> Загрузка…
      </div>
    )
  }

  if (error || !product) {
    return (
      <ErrorState
        title="Товар не найден в локальной БД"
        hint="Найдите его через поиск — он появится в БД после первого запроса"
      />
    )
  }

  return (
    <div className="space-y-4 max-w-5xl">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200"
        >
          <ArrowLeft size={14} /> Назад
        </button>

        <span className={clsx('text-xs font-mono px-2 py-0.5 rounded', getStoreBadgeColor(product.store_slug))}>
          {getStoreLabel(product.store_slug)}
        </span>

        <a
          href={product.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-violet-400 hover:text-violet-300 flex items-center gap-1"
        >
          <ExternalLink size={11} /> в магазине
        </a>

        <button
          type="button"
          onClick={handleShare}
          className="ml-auto text-xs text-gray-400 hover:text-gray-200 flex items-center gap-1.5 px-2 py-1 rounded bg-gray-900 border border-gray-800"
          title="Скопировать ссылку"
        >
          {copied ? <Check size={12} className="text-green-400" /> : <Share2 size={12} />}
          {copied ? 'Скопировано' : 'Поделиться'}
        </button>
      </div>

      {/* Карточка */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <ProductDetail product={product} />
      </div>
    </div>
  )
}

function ErrorState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="max-w-md py-12 text-center">
      <h1 className="text-lg font-semibold text-gray-100">{title}</h1>
      {hint && <p className="text-sm text-gray-500 mt-2">{hint}</p>}
      <Link to="/" className="inline-block mt-4 text-sm text-violet-400 hover:text-violet-300">
        ← К поиску
      </Link>
    </div>
  )
}
