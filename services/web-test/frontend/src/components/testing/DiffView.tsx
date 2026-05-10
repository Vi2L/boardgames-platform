import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowDown, ArrowUp, Plus, Minus, AlertTriangle, Layers } from 'lucide-react'
import clsx from 'clsx'
import type { DiffCategory, DiffField, DiffProductItem } from '../../types/api'
import { fetchSnapshotDiff } from '../../lib/api'
import { getStoreBadgeColor } from '../../lib/stores'

const PRICE_ALERT_THRESHOLD = 30  // % — > 30% считаем подозрительным

// В compact-режиме extra.* поля группируются в схлопнутый блок.
// Список «важных» ключей отображается вне схлопывания даже в compact-режиме:
// они влияют на UX (цена, наличие, акция, идентификатор).
const RAW_ALWAYS_VISIBLE = new Set([
  'availability', 'in_stock', 'on_sale', 'original_price',
  'sku', 'article', 'bonus_percent',
])

/**
 * Side-by-side diff двух snapshot-ов.
 *
 * URL: /testing/diff?a=1&b=2 (через query-params, чтобы можно было поделиться).
 * Подсветка изменений: добавлен → зелёный, удалён → красный, изменён →
 * желтоватый с раскрытием полей. Filter «только изменения» спрятан в
 * select сверху — для длинных списков (50+ товаров).
 */
type RawFilter = 'compact' | 'all'

export function DiffView() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const a = Number(params.get('a'))
  const b = Number(params.get('b'))
  const [filter, setFilter] = useState<'all' | 'changes'>('changes')
  const [catFilter, setCatFilter] = useState<DiffCategory | 'any'>('any')
  const [rawFilter, setRawFilter] = useState<RawFilter>('compact')

  const { data: diff, isLoading, error } = useQuery({
    queryKey: ['snapshot-diff', a, b],
    queryFn: () => fetchSnapshotDiff(a, b),
    enabled: Number.isFinite(a) && Number.isFinite(b),
  })

  const filtered = useMemo(() => {
    if (!diff) return []
    let items = filter === 'all'
      ? diff.products
      : diff.products.filter(p => p.status !== 'same' as never)
    if (catFilter !== 'any') {
      items = items.filter(p => {
        if (p.status !== 'changed') return false
        return Object.values(p.fields ?? {}).some(f => f.category === catFilter)
      })
    }
    return items
  }, [diff, filter, catFilter])

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

        <select
          value={catFilter}
          onChange={e => setCatFilter(e.target.value as DiffCategory | 'any')}
          className="px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200"
          title="Категория изменения"
        >
          <option value="any">Все категории</option>
          <option value="price">Цена</option>
          <option value="lost">Потеряно поле</option>
          <option value="gained">Появилось поле</option>
          <option value="raw">Raw (extra)</option>
          <option value="field">Прочее</option>
        </select>

        <button
          type="button"
          onClick={() => setRawFilter(f => f === 'compact' ? 'all' : 'compact')}
          title={rawFilter === 'compact' ? 'Показать все extra-поля' : 'Свернуть extra-поля'}
          className={clsx(
            'flex items-center gap-1.5 px-2 py-1 rounded text-xs border transition-colors',
            rawFilter === 'compact'
              ? 'bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200'
              : 'bg-blue-900/40 border-blue-700 text-blue-300',
          )}
        >
          <Layers size={11} />
          {rawFilter === 'compact' ? 'compact raw' : 'все raw'}
        </button>

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

      {/* Categories breakdown */}
      {diff.summary.categories && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
          <CatCell label="Цена изменилась"  count={diff.summary.categories.price ?? 0} category="price" />
          <CatCell label="Потеряно поле"    count={diff.summary.categories.lost ?? 0}  category="lost" />
          <CatCell label="Появилось поле"   count={diff.summary.categories.gained ?? 0} category="gained" />
          <CatCell label="Raw (extra)"      count={diff.summary.categories.raw ?? 0}   category="raw" />
          <CatCell label="Прочие изм."      count={diff.summary.categories.field ?? 0} category="field" />
        </div>
      )}

      {filtered.length === 0
        ? <div className="text-sm text-gray-500 py-12 text-center">Нет изменений</div>
        : (
          <div className="space-y-2">
            {filtered.map(item => <DiffRow key={item.key} item={item} rawFilter={rawFilter} />)}
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

function CatCell({
  label, count, category,
}: { label: string; count: number; category: DiffCategory }) {
  const color = CAT_COLOR[category]
  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded px-3 py-2">
      <div className={clsx('text-xs', color.text)}>{label}</div>
      <div className={clsx('text-base font-mono font-semibold', count > 0 ? color.text : 'text-gray-500')}>
        {count}
      </div>
    </div>
  )
}

const CAT_COLOR: Record<DiffCategory, { text: string; bg: string; pill: string }> = {
  price:  { text: 'text-yellow-400', bg: 'bg-yellow-950/20', pill: 'bg-yellow-900/40 text-yellow-200' },
  lost:   { text: 'text-red-400',    bg: 'bg-red-950/20',    pill: 'bg-red-900/40 text-red-200' },
  gained: { text: 'text-emerald-400',bg: 'bg-emerald-950/20',pill: 'bg-emerald-900/40 text-emerald-200' },
  raw:    { text: 'text-blue-400',   bg: 'bg-blue-950/20',   pill: 'bg-blue-900/40 text-blue-200' },
  field:  { text: 'text-gray-400',   bg: 'bg-gray-900/40',   pill: 'bg-gray-800 text-gray-300' },
}

function DiffRow({ item, rawFilter }: { item: DiffProductItem; rawFilter: RawFilter }) {
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

  // Уникальные категории всех полей, чтобы показать summary-pills.
  const cats = new Set<DiffCategory>()
  if (item.status === 'changed' && item.fields) {
    for (const f of Object.values(item.fields)) {
      if (f.category) cats.add(f.category)
    }
  }
  const priceField = item.fields?.price_rub
  const isBigPriceJump =
    priceField?.delta_pct != null && Math.abs(priceField.delta_pct) >= PRICE_ALERT_THRESHOLD

  // Разделяем поля на «обычные» и «extra.*» для compact-режима.
  const allFields = Object.entries(item.fields ?? {})
  const regularFields = allFields.filter(([f]) => !f.startsWith('extra.'))
  const extraFields   = allFields.filter(([f]) =>  f.startsWith('extra.'))

  // В compact-режиме «важные» extra-ключи показываем вместе с обычными.
  const extraVisible = rawFilter === 'all'
    ? extraFields
    : extraFields.filter(([f]) => RAW_ALWAYS_VISIBLE.has(f.slice('extra.'.length)))
  const extraHidden = rawFilter === 'all'
    ? []
    : extraFields.filter(([f]) => !RAW_ALWAYS_VISIBLE.has(f.slice('extra.'.length)))

  return (
    <details className={clsx('border rounded p-3', borderClass)}>
      <summary className="cursor-pointer flex items-center gap-2 select-none flex-wrap">
        {StatusIcon && <StatusIcon size={14} className={
          item.status === 'added' ? 'text-green-400' : 'text-red-400'
        } />}
        <span className={clsx('px-2 py-0.5 rounded text-xs font-mono', getStoreBadgeColor(product.store_slug))}>
          {product.store_slug}
        </span>
        <span className="font-medium text-gray-200 truncate flex-1 min-w-0" title={product.title}>
          {product.title}
        </span>

        {/* Категории-pills */}
        {[...cats].map(c => (
          <span key={c} className={clsx('text-[10px] px-1.5 py-0.5 rounded uppercase', CAT_COLOR[c].pill)}>
            {c}
          </span>
        ))}

        {isBigPriceJump && (
          <span className="text-amber-400 flex items-center gap-1" title="Большое изменение цены">
            <AlertTriangle size={12} />
          </span>
        )}

        {priceField && <PriceDelta field={priceField} />}
      </summary>

      {item.status === 'changed' && item.fields && (
        <div className="mt-3 space-y-1.5 text-xs font-mono">
          {/* Обычные поля + важные extra — всегда видны */}
          {[...regularFields, ...extraVisible].map(([field, val]) => (
            <FieldDiff key={field} field={field} val={val} />
          ))}

          {/* Схлопнутый блок для шумных extra-полей в compact-режиме */}
          {extraHidden.length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer text-gray-500 hover:text-gray-300 select-none">
                <span className={clsx('text-[9px] px-1 py-0 rounded uppercase tracking-wide mr-1.5', CAT_COLOR.raw.pill)}>
                  raw
                </span>
                ещё {extraHidden.length} extra-{extraHidden.length === 1 ? 'поле' : extraHidden.length < 5 ? 'поля' : 'полей'}
              </summary>
              <div className="mt-1.5 space-y-1.5 pl-2 border-l border-gray-800">
                {extraHidden.map(([field, val]) => (
                  <FieldDiff key={field} field={field} val={val} />
                ))}
              </div>
            </details>
          )}
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
    if (Array.isArray(v)) {
      return <span className="text-blue-400">[…{v.length}]</span>
    }
    if (typeof v === 'object') return <span className="text-blue-400">{JSON.stringify(v).slice(0, 80)}</span>
    return <span>{String(v)}</span>
  }
  const cat = val.category
  return (
    <div className="grid grid-cols-[140px_1fr_1fr] gap-2 items-start">
      <div className="flex items-center gap-1.5 min-w-0">
        {cat && (
          <span className={clsx('text-[9px] px-1 py-0 rounded uppercase tracking-wide', CAT_COLOR[cat].pill)}>
            {cat}
          </span>
        )}
        <span className="text-gray-500 truncate" title={field}>{field}</span>
      </div>
      <span className="text-red-300/70 line-through truncate" title={String(val.a)}>{renderValue(val.a)}</span>
      <span className="text-green-300 truncate" title={String(val.b)}>{renderValue(val.b)}</span>
    </div>
  )
}
