/**
 * LiveTestPanel — основной UI Debug-страницы.
 *
 * Запускает GET /api/debug/parse через React Query mutation. Этот endpoint
 * проксирует /api/debug/parse parsers, который:
 *  - НЕ читает кеш и не пишет в products / price_observations;
 *  - В parser_log пишет с is_test=1 (исключается из аналитики);
 *  - Возвращает сырые ParsedProduct + детальные метрики per-store.
 *
 * Стейт умышленно локальный (не Zustand) — Debug одноразовая страница, не
 * нужно сохранять между навигацией.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Play, Loader2, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight } from 'lucide-react'
import clsx from 'clsx'
import { debugParse, fetchParsers } from '../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../lib/stores'
import type { DebugParseResponse, DebugStoreResult } from '../../types/api'
import { RawProductCard } from './RawProductCard'

const LIMIT_OPTIONS = [3, 5, 10, 20]

export function LiveTestPanel() {
  const [q, setQ] = useState('')
  const [selectedStores, setSelectedStores] = useState<string[]>([])
  const [limit, setLimit] = useState(5)

  const parsers = useQuery({ queryKey: ['parsers'], queryFn: fetchParsers })

  const mutation = useMutation<DebugParseResponse, Error>({
    mutationFn: () => debugParse({
      q: q.trim(),
      stores: selectedStores.length > 0 ? selectedStores : undefined,
      limit,
    }),
  })

  const toggleStore = (slug: string) =>
    setSelectedStores(s => s.includes(slug) ? s.filter(x => x !== slug) : [...s, slug])

  const submit = () => {
    if (!q.trim()) return
    mutation.mutate()
  }

  const results = mutation.data?.results

  return (
    <div className="space-y-4">
      {/* Form */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submit() }}
            placeholder="Запрос для всех парсеров (мимо кеша)…"
            className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500"
            disabled={mutation.isPending}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!q.trim() || mutation.isPending}
            className="px-4 py-2 rounded text-sm font-medium flex items-center gap-1.5 bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 disabled:cursor-not-allowed text-white"
          >
            {mutation.isPending
              ? <><Loader2 size={13} className="animate-spin" /> Парсим…</>
              : <><Play size={13} /> Запустить</>}
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
                className="accent-indigo-500"
              />
              <span className={clsx(
                'px-1.5 py-0.5 rounded',
                selectedStores.includes(p.slug) ? getStoreBadgeColor(p.slug) : 'text-gray-400',
              )}>
                {getStoreLabel(p.slug, p.name)}
              </span>
            </label>
          ))}
          <div className="text-xs text-gray-600 ml-auto">
            пусто = все
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span>Лимит:</span>
          {LIMIT_OPTIONS.map(n => (
            <button
              key={n}
              type="button"
              onClick={() => setLimit(n)}
              className={clsx(
                'px-2 py-0.5 rounded',
                limit === n
                  ? 'bg-indigo-900/60 text-indigo-200'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
              )}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Status */}
      {mutation.isError && (
        <div className="bg-red-950/50 border border-red-900/50 rounded p-3 text-sm text-red-400 flex items-start gap-2">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <div>
            <div className="font-medium">Не удалось запустить debug-парсер</div>
            <div className="text-xs text-red-300/80 mt-0.5">{String(mutation.error)}</div>
          </div>
        </div>
      )}

      {/* Results */}
      {results && (
        <div className="space-y-2">
          <div className="text-xs text-gray-500">
            Запрос: «{mutation.data!.query}». Магазинов: {Object.keys(results).length}.
          </div>
          {Object.entries(results).map(([slug, r]) => (
            <StoreResultBlock key={slug} slug={slug} result={r} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Per-store accordion ────────────────────────────────────────────────────

function StoreResultBlock({ slug, result }: { slug: string; result: DebugStoreResult }) {
  const [open, setOpen] = useState(true)
  const hasError = !!result.error
  const m = result.metrics

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

        {hasError ? (
          <span className="text-xs text-red-400 flex items-center gap-1">
            <AlertTriangle size={11} /> ошибка
          </span>
        ) : (
          <span className="text-xs text-emerald-400 flex items-center gap-1">
            <CheckCircle2 size={11} /> {result.count} товаров
          </span>
        )}

        <div className="ml-auto flex items-center gap-3 text-xs text-gray-500">
          <Metric label="total" value={`${result.duration_ms} ms`} />
          {m?.search_ms != null && <Metric label="search" value={`${m.search_ms} ms`} />}
          {m?.enrich_ms != null && <Metric label="enrich" value={`${m.enrich_ms} ms`} />}
          {m?.http_requests != null && <Metric label="http" value={String(m.http_requests)} />}
          {m?.result_after_enrich != null && <Metric label="post-enrich" value={String(m.result_after_enrich)} />}
        </div>
      </button>

      {open && (
        <div className="border-t border-gray-800 p-3 space-y-2 bg-gray-950/50">
          {hasError && (
            <div className="text-xs text-red-300 bg-red-950/40 border border-red-900/50 rounded p-2 font-mono">
              {result.error}
            </div>
          )}
          {result.products.length === 0 && !hasError && (
            <div className="text-xs text-gray-500 italic py-2">Парсер вернул пустой результат.</div>
          )}
          {result.products.map((p, i) => (
            <RawProductCard key={`${p.external_id}-${i}`} product={p} />
          ))}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-gray-600">{label}</span>
      <span className="font-mono text-gray-300">{value}</span>
    </div>
  )
}
