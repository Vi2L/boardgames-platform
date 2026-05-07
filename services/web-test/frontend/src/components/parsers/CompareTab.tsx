/**
 * CompareTab — параллельный запуск /search (с кешем) и /api/debug/parse (мимо).
 *
 * Backend сам считает diff (`/api/debug/compare`), фронт лишь отображает три
 * категории расхождений: only_cache, only_live, changed. Это отвечает на вопрос
 * «после моей правки селекторов магазин не сломался?» — если diff большой,
 * стоит присмотреться к коду.
 *
 * Ключ для diff — `url` товара (он стабильнее `external_id` между кешем и live).
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Play, Loader2, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight,
  Plus, Minus, Equal, ArrowLeftRight,
} from 'lucide-react'
import clsx from 'clsx'
import { debugCompare, fetchParsers } from '../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../lib/stores'
import type { CompareResponse, CompareStoreResult } from '../../types/api'

const LIMIT_OPTIONS = [5, 10, 20]

export function CompareTab() {
  const [q, setQ] = useState('')
  const [selectedStores, setSelectedStores] = useState<string[]>([])
  const [limit, setLimit] = useState(10)

  const parsers = useQuery({ queryKey: ['parsers'], queryFn: fetchParsers })

  const mutation = useMutation<CompareResponse, Error>({
    mutationFn: () => debugCompare({
      q: q.trim(),
      stores: selectedStores.length > 0 ? selectedStores : undefined,
      limit,
    }),
  })

  const toggleStore = (slug: string) =>
    setSelectedStores(s => s.includes(slug) ? s.filter(x => x !== slug) : [...s, slug])

  const submit = () => { if (q.trim()) mutation.mutate() }

  return (
    <div className="space-y-4">
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submit() }}
            placeholder="Запрос для сравнения cache vs live…"
            className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-violet-500"
            disabled={mutation.isPending}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!q.trim() || mutation.isPending}
            className="px-4 py-2 rounded text-sm font-medium flex items-center gap-1.5 bg-violet-700 hover:bg-violet-600 disabled:opacity-40 disabled:cursor-not-allowed text-white"
          >
            {mutation.isPending
              ? <><Loader2 size={13} className="animate-spin" /> Сравниваем…</>
              : <><Play size={13} /> Сравнить</>}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="text-xs text-gray-500">Магазины:</div>
          {parsers.data?.map(p => (
            <label key={p.slug} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={selectedStores.includes(p.slug)}
                onChange={() => toggleStore(p.slug)}
                className="accent-violet-500"
              />
              <span className={clsx(
                'px-1.5 py-0.5 rounded',
                selectedStores.includes(p.slug) ? getStoreBadgeColor(p.slug) : 'text-gray-400',
              )}>
                {getStoreLabel(p.slug, p.name)}
              </span>
            </label>
          ))}
          <div className="flex items-center gap-2 text-xs text-gray-500 ml-auto">
            <span>Лимит:</span>
            {LIMIT_OPTIONS.map(n => (
              <button
                key={n}
                type="button"
                onClick={() => setLimit(n)}
                className={clsx(
                  'px-2 py-0.5 rounded',
                  limit === n
                    ? 'bg-violet-900/60 text-violet-200'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
                )}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
      </div>

      {mutation.isError && (
        <div className="bg-red-950/50 border border-red-900/50 rounded p-3 text-sm text-red-400">
          {String(mutation.error)}
        </div>
      )}

      {mutation.data && (
        <div className="space-y-2">
          {mutation.data.errors.cache && (
            <ErrorBanner label="cache search" message={mutation.data.errors.cache} />
          )}
          {mutation.data.errors.live && (
            <ErrorBanner label="live parse" message={mutation.data.errors.live} />
          )}
          {Object.entries(mutation.data.results).map(([slug, r]) => (
            <CompareStoreBlock key={slug} slug={slug} result={r} />
          ))}
          {Object.keys(mutation.data.results).length === 0 && (
            <div className="text-xs text-gray-500 italic py-4">
              Ни cache, ни live ничего не вернули. Возможно q невалиден или parsers недоступен.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ErrorBanner({ label, message }: { label: string; message: string }) {
  return (
    <div className="bg-red-950/40 border border-red-900/50 rounded p-2 text-xs text-red-300 flex gap-2">
      <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
      <span><span className="font-mono text-red-400">{label}</span>: {message}</span>
    </div>
  )
}

function CompareStoreBlock({ slug, result }: { slug: string; result: CompareStoreResult }) {
  const [open, setOpen] = useState(true)
  const { cache, live, diff } = result
  const totalDiff = diff.only_cache.length + diff.only_live.length + diff.changed.length
  const hasError = !!(cache.error || live.error)

  return (
    <div className={clsx(
      'border rounded-lg overflow-hidden',
      hasError ? 'bg-red-950/30 border-red-900/50' : 'bg-gray-900 border-gray-800',
    )}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 p-3 hover:bg-gray-850"
      >
        <div className="text-gray-500">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
        <span className={clsx('px-2 py-0.5 rounded text-xs font-medium', getStoreBadgeColor(slug))}>
          {getStoreLabel(slug)}
        </span>

        <div className="flex items-center gap-3 text-xs">
          <CountBadge icon={<Equal size={11} />} value={diff.same_count} label="одинаковых" muted />
          <CountBadge icon={<Plus size={11} />} value={diff.only_live.length} label="только live"
                      color="emerald" />
          <CountBadge icon={<Minus size={11} />} value={diff.only_cache.length} label="только cache"
                      color="amber" />
          <CountBadge icon={<ArrowLeftRight size={11} />} value={diff.changed.length}
                      label="отличаются" color="violet" />
        </div>

        <div className="ml-auto flex items-center gap-3 text-xs text-gray-500">
          {live.duration_ms != null && <span className="font-mono">live {live.duration_ms} ms</span>}
          {totalDiff === 0 ? (
            <span className="text-emerald-400 flex items-center gap-1">
              <CheckCircle2 size={11} /> идентично
            </span>
          ) : (
            <span className="text-amber-400">{totalDiff} расхождений</span>
          )}
        </div>
      </button>

      {open && (
        <div className="border-t border-gray-800 p-3 space-y-3 bg-gray-950/40">
          {(cache.error || live.error) && (
            <div className="text-xs text-red-300 space-y-1">
              {cache.error && <div>cache.error: <span className="font-mono">{cache.error}</span></div>}
              {live.error && <div>live.error: <span className="font-mono">{live.error}</span></div>}
            </div>
          )}

          {/* Counts header */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="bg-gray-900 rounded p-2">
              <div className="text-gray-500">cache (refresh=false)</div>
              <div className="text-gray-200 font-mono mt-0.5">{cache.count} товаров</div>
            </div>
            <div className="bg-gray-900 rounded p-2">
              <div className="text-gray-500">live (мимо кеша)</div>
              <div className="text-gray-200 font-mono mt-0.5">{live.count} товаров</div>
            </div>
          </div>

          {/* Changed */}
          {diff.changed.length > 0 && (
            <Section title={`Различаются — ${diff.changed.length}`} color="violet">
              <ul className="space-y-1.5">
                {diff.changed.map((c, i) => (
                  <li key={i} className="bg-gray-900 rounded p-2 space-y-1">
                    <a href={c.url} target="_blank" rel="noreferrer"
                       className="block text-xs text-violet-300 hover:underline truncate">
                      {c.url}
                    </a>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <CompareSide label="cache" title={c.cache.title} price={c.cache.price_rub} />
                      <CompareSide label="live"  title={c.live.title}  price={c.live.price_rub} />
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/* Only live */}
          {diff.only_live.length > 0 && (
            <Section title={`Только в live — ${diff.only_live.length}`} color="emerald">
              <ul className="space-y-0.5">
                {diff.only_live.map(u => <UrlRow key={u} url={u} />)}
              </ul>
            </Section>
          )}

          {/* Only cache */}
          {diff.only_cache.length > 0 && (
            <Section title={`Только в кеше — ${diff.only_cache.length}`} color="amber">
              <ul className="space-y-0.5">
                {diff.only_cache.map(u => <UrlRow key={u} url={u} />)}
              </ul>
            </Section>
          )}

          {totalDiff === 0 && !hasError && (
            <div className="text-xs text-emerald-400 italic">Парсер возвращает идентичный набор.</div>
          )}
        </div>
      )}
    </div>
  )
}

function CountBadge({
  icon, value, label, color = 'gray', muted = false,
}: {
  icon: React.ReactNode
  value: number
  label: string
  color?: 'gray' | 'emerald' | 'amber' | 'violet'
  muted?: boolean
}) {
  const colorMap: Record<string, string> = {
    gray: muted ? 'text-gray-500' : 'text-gray-300',
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    violet: 'text-violet-300',
  }
  return (
    <span className={clsx('flex items-center gap-1', colorMap[color])} title={label}>
      {icon} <span className="font-mono">{value}</span>
    </span>
  )
}

function Section({ title, color, children }: {
  title: string
  color: 'emerald' | 'amber' | 'violet'
  children: React.ReactNode
}) {
  const headerColor: Record<string, string> = {
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    violet: 'text-violet-300',
  }
  return (
    <div>
      <div className={clsx('text-xs mb-1.5 font-medium', headerColor[color])}>{title}</div>
      {children}
    </div>
  )
}

function UrlRow({ url }: { url: string }) {
  return (
    <li>
      <a href={url} target="_blank" rel="noreferrer"
         className="block text-xs text-gray-400 hover:text-violet-300 hover:underline truncate font-mono">
        {url}
      </a>
    </li>
  )
}

function CompareSide({
  label, title, price,
}: {
  label: string
  title: string | null
  price: number | null
}) {
  return (
    <div className="bg-gray-950 rounded p-1.5">
      <div className="text-gray-500 text-[10px] uppercase tracking-wide">{label}</div>
      <div className="text-gray-200 truncate" title={title || ''}>{title || <span className="italic text-gray-600">—</span>}</div>
      <div className="text-emerald-400 font-mono mt-0.5">
        {price != null ? `${price.toFixed(0)} ₽` : <span className="text-gray-600">—</span>}
      </div>
    </div>
  )
}
