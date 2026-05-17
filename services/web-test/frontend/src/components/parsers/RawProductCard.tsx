/**
 * Карточка сырого ParsedProduct из debug-парсера.
 *
 * В отличие от ResultsTable, мы здесь показываем ВСЕ поля включая raw —
 * это диагностический инструмент, человеку важно видеть что вернул парсер
 * один-в-один, прежде чем нормализатор начнёт что-то делать.
 *
 * Compact-режим: миниатюра + цена + название.
 * Expanded:      все поля + JsonViewer с raw.
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight, ExternalLink, ImageOff } from 'lucide-react'
import clsx from 'clsx'
import type { DebugProduct } from '../../types/api'
import { JsonViewer } from '../shared/JsonViewer'

interface Props {
  product: DebugProduct
}

export function RawProductCard({ product }: Props) {
  const [expanded, setExpanded] = useState(false)
  const img = product.image_url_hd || product.image_url
  const rawCount = Object.keys(product.raw || {}).length

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-md overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className="w-full flex gap-3 p-2.5 hover:bg-gray-850 text-left"
      >
        <div className="w-12 h-12 flex-shrink-0 bg-gray-950 rounded flex items-center justify-center overflow-hidden">
          {img ? (
            <img
              src={img}
              alt=""
              className="max-w-full max-h-full object-contain"
              onError={(e) => { (e.currentTarget.style.display = 'none') }}
            />
          ) : (
            <ImageOff size={16} className="text-gray-600" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-gray-100 truncate">{product.title}</div>
          <div className="flex items-center gap-2 mt-1 text-xs text-gray-400">
            <span className="text-emerald-400 font-mono">{product.price_rub.toFixed(0)} ₽</span>
            <span className="text-gray-600">·</span>
            <span className="font-mono text-gray-500">id {String(product.external_id)}</span>
            {rawCount > 0 && (
              <>
                <span className="text-gray-600">·</span>
                <span className="text-gray-500">{rawCount} raw-полей</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center text-gray-500">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-gray-800 p-3 space-y-3 bg-gray-950">
          {/* Поля ParsedProduct */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <Field label="price (копейки)" value={String(product.price)} mono />
            <Field label="price_rub" value={`${product.price_rub.toFixed(2)} ₽`} mono />
            <Field label="players" value={product.players} />
            <Field label="age_min" value={product.age_min ?? null} />
            <Field label="playtime" value={product.playtime} />
            <Field label="rules_url" value={product.rules_url} link />
            <Field label="image_url" value={product.image_url} link />
            <Field label="image_url_hd" value={product.image_url_hd} link />
          </div>

          {product.description && (
            <div className="text-xs">
              <div className="text-gray-500 mb-1">description</div>
              <div className={clsx(
                'text-gray-300 leading-relaxed bg-gray-900 p-2 rounded',
                'max-h-40 overflow-y-auto',
              )}>
                {product.description}
              </div>
            </div>
          )}

          <div className="flex gap-2">
            <a
              href={product.url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded"
            >
              <ExternalLink size={11} /> URL товара
            </a>
          </div>

          {/* Raw JSON */}
          {rawCount > 0 && (
            <div>
              <div className="text-xs text-gray-500 mb-1">raw ({rawCount} полей)</div>
              <JsonViewer data={product.raw} maxHeight={300} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Field({
  label, value, mono = false, link = false,
}: {
  label: string
  value: string | number | null | undefined
  mono?: boolean
  link?: boolean
}) {
  const isEmpty = value === null || value === undefined || value === ''
  return (
    <div className="flex gap-2 min-w-0">
      <span className="text-gray-500 flex-shrink-0">{label}:</span>
      {isEmpty ? (
        <span className="text-gray-600 italic">null</span>
      ) : link && typeof value === 'string' ? (
        <a
          href={value}
          target="_blank"
          rel="noreferrer"
          className={clsx('text-indigo-300 hover:underline truncate', mono && 'font-mono')}
          title={value}
        >
          {value}
        </a>
      ) : (
        <span className={clsx('text-gray-300 truncate', mono && 'font-mono')} title={String(value)}>
          {String(value)}
        </span>
      )}
    </div>
  )
}
