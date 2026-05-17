import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink, Loader2, Share2, Check } from 'lucide-react'
import { toast } from 'sonner'
import { fetchDbProduct } from '../lib/api'
import { getStoreBadgeColor, getStoreLabel } from '../lib/stores'
import { ProductDetail } from '../components/shared/ProductDetail'
import { Button } from '../components/ui'

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
      toast.success('Ссылка скопирована')
      setTimeout(() => setCopied(false), 2000)
    })
  }

  if (!isValidId) {
    return <ErrorState title="Некорректный ID товара" />
  }

  if (isLoading) {
    return (
      <div className="p-4 flex items-center gap-2 text-zinc-500">
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
    <div className="p-4 space-y-4 max-w-5xl">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Button
          variant="ghost"
          size="sm"
          icon={ArrowLeft}
          onClick={() => navigate(-1)}
        >
          Назад
        </Button>

        <span className={`text-xs font-mono px-2 py-0.5 rounded ${getStoreBadgeColor(product.store_slug)}`}>
          {getStoreLabel(product.store_slug)}
        </span>

        <a
          href={product.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-indigo-300 hover:text-indigo-200 flex items-center gap-1"
        >
          <ExternalLink size={11} /> в магазине
        </a>

        <Button
          variant="secondary"
          size="sm"
          icon={copied ? Check : Share2}
          onClick={handleShare}
          title="Скопировать ссылку"
          className={copied ? 'text-emerald-300' : undefined}
        >
          {copied ? 'Скопировано' : 'Поделиться'}
        </Button>
      </div>

      {/* Карточка */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
        <ProductDetail product={product} />
      </div>
    </div>
  )
}

function ErrorState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="p-4 max-w-md py-12 text-center">
      <h1 className="text-lg font-semibold text-zinc-100">{title}</h1>
      {hint && <p className="text-sm text-zinc-500 mt-2">{hint}</p>}
      <Link to="/" className="inline-block mt-4 text-sm text-indigo-300 hover:text-indigo-200">
        ← К поиску
      </Link>
    </div>
  )
}
