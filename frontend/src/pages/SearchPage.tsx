import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Clock, Zap, AlertCircle, CheckCircle2 } from 'lucide-react'
import clsx from 'clsx'
import { fetchRecentDeltas, fetchStores } from '../lib/api'
import { useSSE } from '../lib/sse'
import { useSearchStore } from '../store/search'
import { SearchForm } from '../components/search/SearchForm'
import { StoreProgressBadge } from '../components/search/StoreProgressBadge'
import { ResultsTable } from '../components/search/ResultsTable'
import { ProductDrawer } from '../components/search/ProductDrawer'
import type { PriceDeltaOut, ProductOut } from '../types/api'

type Tab = 'results' | 'api-log'

export function SearchPage() {
  const [tab, setTab] = useState<Tab>('results')
  const [selectedProduct, setSelectedProduct] = useState<ProductOut | null>(null)

  const {
    sseUrl, storeProgress, results, apiLogs, totalMs, source,
    startSearch, stopSearch, handleSSEEvent, isSearching,
  } = useSearchStore()

  const { data: stores = [] } = useQuery({ queryKey: ['stores'], queryFn: fetchStores })

  // Δ-цена: грузим пакетом для всех id из текущих результатов. Ключ —
  // сортированный список id, чтобы кэш переиспользовался между ре-рендерами
  // и сбрасывался при новом поиске.
  const productIds = useMemo(() => results.map(p => p.id).sort((a, b) => a - b), [results])
  const { data: deltasArray = [] } = useQuery({
    queryKey: ['recent-deltas', productIds.join(',')],
    queryFn: () => fetchRecentDeltas(productIds),
    enabled: productIds.length > 0,
    staleTime: 60_000,
  })
  const deltas = useMemo<Map<number, PriceDeltaOut>>(() =>
    new Map(deltasArray.map(d => [d.product_id, d])),
    [deltasArray],
  )

  const onEvent = useCallback((event: string, data: unknown) => {
    handleSSEEvent(event, data)
  }, [handleSSEEvent])

  useSSE(sseUrl, onEvent)

  const hasActivity = Object.keys(storeProgress).length > 0
  const progressList = Object.values(storeProgress)
  const tabCls = (t: Tab) =>
    `px-3 py-2 text-xs font-medium border-b-2 transition-colors ${tab === t
      ? 'border-violet-500 text-violet-400'
      : 'border-transparent text-gray-500 hover:text-gray-300'}`

  // Единственный api-request лог для отображения
  const apiReq = apiLogs.find(l => l.type === 'request')
  const apiResp = apiLogs.find(l => l.type === 'response')
  const apiErr = apiLogs.find(l => l.type === 'error')

  return (
    <div className="space-y-4 max-w-5xl">
      <div>
        <h1 className="text-lg font-semibold text-gray-100">Поиск</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Поиск через parsers API с отображением прогресса по магазинам
        </p>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <SearchForm
          stores={stores}
          onSearch={() => startSearch(stores.map(s => s.slug))}
          onStop={stopSearch}
        />
      </div>

      {/* Прогресс парсеров */}
      {hasActivity && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Прогресс</span>
            {totalMs != null && (
              <span className="text-xs text-gray-500 flex items-center gap-1">
                <Clock size={11} /> {totalMs}ms
                {source && (
                  <span className={clsx('ml-2 px-1.5 py-0.5 rounded text-xs',
                    source === 'cache' ? 'bg-yellow-950 text-yellow-400' :
                    source === 'network' ? 'bg-green-950 text-green-400' :
                    'bg-gray-800 text-gray-400'
                  )}>
                    {source === 'cache' ? '⚡ кэш' : source === 'network' ? '🌐 сеть' : source}
                  </span>
                )}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {progressList.map(p => <StoreProgressBadge key={p.slug} progress={p} />)}
          </div>
        </div>
      )}

      {/* Результаты и API Log */}
      {(hasActivity || results.length > 0) && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <div className="flex px-4 border-b border-gray-800 bg-gray-900/50">
            <button className={tabCls('results')} onClick={() => setTab('results')}>
              Результаты{results.length > 0 && ` (${results.length})`}
            </button>
            <button className={tabCls('api-log')} onClick={() => setTab('api-log')}>
              API Log{apiLogs.length > 0 && ` (${apiLogs.length})`}
            </button>
          </div>

          <div className="p-4">
            {tab === 'results' && (
              <ResultsTable
                products={results}
                deltas={deltas}
                onSelect={setSelectedProduct}
              />
            )}

            {tab === 'api-log' && (
              <div className="space-y-3">
                {apiLogs.length === 0 && (
                  <div className="text-sm text-gray-500 text-center py-8">
                    {isSearching ? 'Ожидание ответа от parsers API…' : 'Нет запросов'}
                  </div>
                )}

                {/* Запрос */}
                {apiReq && (
                  <div className="bg-gray-950 border border-gray-800 rounded p-3 space-y-1.5">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-blue-400 font-mono font-bold">↑ GET</span>
                      <span className="text-gray-300 font-mono truncate">{apiReq.url}</span>
                    </div>
                    <div className="text-xs text-gray-500 font-mono">
                      q={apiReq.q}
                      {apiReq.stores && ` stores=${apiReq.stores.join(',')}`}
                    </div>
                  </div>
                )}

                {/* Ответ */}
                {apiResp && (
                  <div className="bg-gray-950 border border-gray-800 rounded p-3 space-y-2">
                    <div className="flex items-center gap-3 text-xs">
                      <CheckCircle2 size={13} className="text-green-400" />
                      <span className="text-green-400 font-mono font-bold">↓ {apiResp.status}</span>
                      <span className="text-gray-400">{apiResp.elapsed_ms}ms</span>
                      <span className={clsx('px-1.5 py-0.5 rounded',
                        apiResp.source === 'cache' ? 'bg-yellow-950 text-yellow-400' :
                        'bg-green-950 text-green-400'
                      )}>
                        {apiResp.source}
                      </span>
                    </div>
                    <div className="flex gap-4 text-xs text-gray-400">
                      <span>Продуктов: <span className="text-gray-200">{apiResp.products_count}</span></span>
                      {(apiResp.error_count ?? 0) > 0 && (
                        <span className="text-red-400">Ошибок магазинов: {apiResp.error_count}</span>
                      )}
                    </div>
                  </div>
                )}

                {/* Ошибка */}
                {apiErr && (
                  <div className="bg-red-950/30 border border-red-900 rounded p-3 text-xs">
                    <div className="flex items-center gap-2 text-red-400 mb-1">
                      <AlertCircle size={13} /> parsers API недоступен
                    </div>
                    <div className="text-red-300 font-mono">{apiErr.error}</div>
                    <div className="text-gray-500 mt-1">{apiErr.elapsed_ms}ms</div>
                  </div>
                )}

                {/* Ошибки магазинов из store-done */}
                {progressList.filter(p => p.status === 'error').map(p => (
                  <div key={p.slug} className="bg-yellow-950/20 border border-yellow-900/50 rounded p-2.5 text-xs">
                    <div className="flex items-center gap-2 text-yellow-400">
                      <Zap size={11} /> Частичная ошибка: {p.name}
                    </div>
                    <div className="text-gray-400 mt-0.5 font-mono">{p.error}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Drawer с деталями товара */}
      <ProductDrawer
        product={selectedProduct}
        pool={results}
        onClose={() => setSelectedProduct(null)}
        onSelect={setSelectedProduct}
      />
    </div>
  )
}
