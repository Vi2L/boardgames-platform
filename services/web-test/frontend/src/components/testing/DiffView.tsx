import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowDown, ArrowUp, Plus, Minus } from 'lucide-react'
import clsx from 'clsx'
import type { DiffField, DiffProductItem } from '../../types/api'
import { fetchSnapshotDiff } from '../../lib/api'
import { getStoreBadgeColor } from '../../lib/stores'

/**
 * Side-by-side diff двух snapshot-ов.
 *
 * URL: /testing/diff?a=1&b=2 (через query-params, чтобы можно было поделиться).
 * Подсветка изменений: добавлен → зелёный, удалён → красный, изменён →
 * желтоватый с раскрытием полей. Filter «только изменения» спрятан в
 * select сверху — для длинных списков (50+ товаров).
 */
export function DiffView() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const a = Number(params.get('a'))
  const b = Number(params.get('b'))
  const [filter, setFilter] = useState<'all' | 'changes'>('changes')

  const { data: diff, isLoading, error } = useQuery({
    queryKey: ['snapshot-diff', a, b],
    queryFn: () => fetchSnapshotDiff(a, b),
    enabled: Number.isFinite(a) && Number.isFinite(b),
  })

  const filtered = useMemo(() => {
    if (!diff) return []
    if (filter === 'all') return diff.products
    return diff.products.filter(p => p.status !== 'same' as never)
  }, [diff, filter])

  if (isLoading) return <div className="text-sm text-gray-500">Загрузка diff…</div>
  if (error || !diff) {
    return (
      <div className="text-sm text-red-400">
        Не удалось загрузить diff. Проверь, что оба snapshot-а существуют.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200"
        >
          <ArrowLeft size={14} /> К списку
        </button>

        <select
          value={filter}
          onChange={e => setFilter(e.target.value as 'all' | 'changes')}
          className="px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200"
        >
          <option value="changes">Только изменения</option>
          <option value="all">Все</option>
        </select>

        <span className="text-xs text-gray-500 ml-auto font-mono">
          a:{diff.meta.a.id} · b:{diff.meta.b.id}
        </span>
      </div>

      {/* Сводка */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <SummaryCell label="Всего A" value={diff.summary.a_count} />
        <SummaryCell label="Всего B" value={diff.summary.b_count} />
        <SummaryCell label="Добавлено" value={`+${diff.summary.added}`} accent="text-green-400" />
        <SummaryCell label="Удалено" value={`−${diff.summary.removed}`} accent="text-red-400" />
        <SummaryCell label="Изменено" value={`Δ${diff.summary.changed}`} accent="text-yellow-400" />
      </div>

      {filtered.length === 0
        ? <div className="text-sm text-gray-500 py-12 text-center">Нет изменений</div>
        : (
          <div className="space-y-2">
            {filtered.map(item => <DiffRow key={item.key} item={item} />)}
          </div>
        )}
    </div>
  )
}

function SummaryCell({
  label, value, accent,
}: { label: string; value: number | string; accent?: string }) {
  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={clsx('text-lg font-mono font-semibold', accent ?? 'text-gray-200')}>
        {value}
      </div>
    </div>
  )
}

function DiffRow({ item }: { item: DiffProductItem }) {
  const product = item.b ?? item.a
  if (!product) return null

  const borderClass =
    item.status === 'added'   ? 'border-green-700 bg-green-950/20' :
    item.status === 'removed' ? 'border-red-700 bg-red-950/20' :
    'border-yellow-700 bg-yellow-950/20'

  const StatusIcon =
    item.status === 'added'   ? Plus :
    item.status === 'removed' ? Minus :
    null

  return (
    <details className={clsx('border rounded p-3', borderClass)}>
      <summary className="cursor-pointer flex items-center gap-2 select-none">
        {StatusIcon && <StatusIcon size={14} className={
          item.status === 'added' ? 'text-green-400' : 'text-red-400'
        } />}
        <span className={clsx('px-2 py-0.5 rounded text-xs font-mono', getStoreBadgeColor(product.store_slug))}>
          {product.store_slug}
        </span>
        <span className="font-medium text-gray-200 truncate flex-1" title={product.title}>
          {product.title}
        </span>
        {item.fields?.price_rub && (
          <PriceDelta field={item.fields.price_rub} />
        )}
      </summary>

      {item.status === 'changed' && item.fields && (
        <div className="mt-3 space-y-1.5 text-xs font-mono">
          {Object.entries(item.fields).map(([field, val]) => (
            <FieldDiff key={field} field={field} val={val} />
          ))}
        </div>
      )}
    </details>
  )
}

function PriceDelta({ field }: { field: DiffField }) {
  const pct = field.delta_pct
  if (pct == null) return null
  const isUp = pct > 0
  const Icon = isUp ? ArrowUp : ArrowDown
  // Зелёный для падения цены — благоприятно для пользователя
  const cls = isUp ? 'text-red-400' : 'text-green-400'
  return (
    <span className={clsx('flex items-center gap-0.5 text-xs font-medium', cls)}>
      <Icon size={11} />{isUp ? '+' : ''}{pct}%
    </span>
  )
}

function FieldDiff({ field, val }: { field: string; val: DiffField }) {
  const renderValue = (v: unknown) => {
    if (v === null || v === undefined) return <span className="text-gray-600">—</span>
    if (typeof v === 'object') return <span className="text-blue-400">{JSON.stringify(v).slice(0, 80)}</span>
    return <span>{String(v)}</span>
  }
  return (
    <div className="grid grid-cols-[100px_1fr_1fr] gap-2 items-start">
      <span className="text-gray-500">{field}</span>
      <span className="text-red-300/70 line-through truncate" title={String(val.a)}>{renderValue(val.a)}</span>
      <span className="text-green-300 truncate" title={String(val.b)}>{renderValue(val.b)}</span>
    </div>
  )
}
