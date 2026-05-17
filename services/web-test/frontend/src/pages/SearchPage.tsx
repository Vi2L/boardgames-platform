import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Clock, Zap, AlertCircle, Save, Star, Eye, EyeOff, Download, ArrowUp, ArrowDown,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  createFavorite, createSnapshot, fetchPriceStats, fetchRecentDeltas, fetchStores,
} from '../lib/api'
import { downloadCsv, downloadJson } from '../lib/export'
import { useSSE } from '../lib/sse'
import { isInStock } from '../lib/offer'
import { applyLoyalty } from '../lib/loyalty'
import { useSearchStore } from '../store/search'
import { useLoyaltyStore } from '../store/loyalty'
import { SearchForm } from '../components/search/SearchForm'
import { StoreProgressBadge } from '../components/search/StoreProgressBadge'
import { ResultsTable } from '../components/search/ResultsTable'
import { ResultsTableGrouped } from '../components/search/ResultsTableGrouped'
import { UnmatchedSection } from '../components/search/UnmatchedSection'
import { ProductDrawer } from '../components/search/ProductDrawer'
import type { PriceDeltaOut, PriceStatsOut, ProductOut } from '../types/api'
import { Tabs, Button, Tag, Badge } from '../components/ui'
import { groupProducts, type ProductGroup } from '../lib/searchGrouping'
import { Layers, List } from 'lucide-react'

type Tab = 'results' | 'api-log'

export function SearchPage() {
  const [tab, setTab] = useState<Tab>('results')
  const [selectedProduct, setSelectedProduct] = useState<ProductOut | null>(null)
  const [savedSnapshotId, setSavedSnapshotId] = useState<number | null>(null)
  const [savingSnap, setSavingSnap] = useState(false)
  const [savingFav, setSavingFav] = useState(false)
  const [favSaved, setFavSaved] = useState(false)
  const [watchMin, setWatchMin] = useState<number>(0)   // 0 = выключено
  const watchTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const queryClient = useQueryClient()

  const {
    query, selectedStores, refresh, limit, showOutOfStock, groupMode,
    sseUrl, storeProgress, results, apiLogs, totalMs, source,
    setQuery, setAllStores, setRefresh, setLimit, setShowOutOfStock, setGroupMode,
    startSearch, stopSearch, handleSSEEvent, isSearching,
  } = useSearchStore()

  // Group-mode: выбранная группа для drawer'а (пока показываем первый
  // оффер группы через существующий ProductDrawer; полноценный
  // `<GameGroupDrawer>` с табами Офферы/История/Матчинг/Raw — отдельная
  // задача, см. roadmap WT-F11-DRAWER).
  const [selectedGroupKey, setSelectedGroupKey] = useState<string | null>(null)

  // ── URL sync (deep-link) ──────────────────────────────────────────────
  const [searchParams, setSearchParams] = useSearchParams()
  const initialUrlAppliedRef = useRef(false)
  useEffect(() => {
    if (initialUrlAppliedRef.current) return
    initialUrlAppliedRef.current = true

    const q = searchParams.get('q')
    const stores = searchParams.get('stores')
    const lim = searchParams.get('limit')
    const ref = searchParams.get('refresh')
    const auto = searchParams.get('auto')
    const productId = searchParams.get('product')

    if (q !== null) setQuery(q)
    if (stores !== null) setAllStores(stores ? stores.split(',').filter(Boolean) : [])
    if (lim !== null) {
      const n = Number(lim)
      if (Number.isFinite(n) && n > 0) setLimit(Math.min(500, Math.max(1, n)))
    }
    if (ref !== null) setRefresh(ref === '1' || ref === 'true')

    if (auto === '1' && q && q.trim()) {
      setTimeout(() => startSearch([]), 50)
    }

    if (productId) {
      const id = Number(productId)
      if (Number.isFinite(id) && id > 0) {
        // selectedProduct ставим заглушкой по id — настоящие данные подтянутся
        // когда найдёт в results, иначе пользователь должен открыть /products/:id
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!initialUrlAppliedRef.current) return
    const sp = new URLSearchParams()
    if (query.trim()) sp.set('q', query.trim())
    if (selectedStores.length > 0) sp.set('stores', selectedStores.join(','))
    if (limit !== 100) sp.set('limit', String(limit))
    if (refresh) sp.set('refresh', '1')
    setSearchParams(sp, { replace: true })
  }, [query, selectedStores, limit, refresh, setSearchParams])

  const { data: stores = [] } = useQuery({ queryKey: ['stores'], queryFn: fetchStores })

  const visibleResults = useMemo(
    () => showOutOfStock ? results : results.filter(isInStock),
    [results, showOutOfStock],
  )
  const hiddenCount = results.length - visibleResults.length

  const loyaltyCfg = useLoyaltyStore()
  const adjusted = useMemo(
    () => applyLoyalty(visibleResults, loyaltyCfg),
    [visibleResults, loyaltyCfg],
  )

  const productIds = useMemo(() => visibleResults.map(p => p.id).sort((a, b) => a - b), [visibleResults])
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

  const { data: priceStatsArray = [] } = useQuery({
    queryKey: ['price-stats', productIds.join(',')],
    queryFn: () => fetchPriceStats(productIds),
    enabled: productIds.length > 0,
    staleTime: 60_000,
  })
  const priceStats = useMemo<Map<number, PriceStatsOut>>(() =>
    new Map(priceStatsArray.map(s => [s.product_id, s])),
    [priceStatsArray],
  )

  // WT-F11: frontend-fallback группировка по titleSimilarity.
  // Дешёво (O(n×k), n≤500 — ≤10мс), greedy-clustering ≥ 0.6 Jaccard.
  // Когда backend выкатит /search/grouped с game_id — заменим на прямой group-by-id.
  const grouped = useMemo(
    () => groupMode === 'group' ? groupProducts(visibleResults) : null,
    [groupMode, visibleResults],
  )

  const handleSelectGroup = (g: ProductGroup) => {
    setSelectedGroupKey(g.canonicalTitle)
    // Минимальный UX: открываем drawer с min-price offer'ом группы.
    const minOffer = g.offers.reduce((best, o) =>
      best == null || o.price_rub < best.price_rub ? o : best,
      null as ProductOut | null,
    )
    if (minOffer) setSelectedProduct(minOffer)
  }

  const buildPayload = () => ({
    query: query.trim(),
    stores: selectedStores.length > 0 ? selectedStores : undefined,
    limit,
    refresh,
  })

  const buildFavoritePayload = () => ({
    ...buildPayload(),
    show_out_of_stock: showOutOfStock,
    loyalty: {
      enabled: loyaltyCfg.enabled,
      hobbygames: loyaltyCfg.hobbygames,
      lavkaigr: loyaltyCfg.lavkaigr,
    },
  })

  const handleSaveSnapshot = async () => {
    if (!query.trim()) return
    setSavingSnap(true)
    try {
      const res = await createSnapshot(buildPayload())
      setSavedSnapshotId(res.id)
      void queryClient.invalidateQueries({ queryKey: ['snapshots'] })
      toast.success(`Snapshot #${res.id} сохранён`, {
        action: { label: 'Открыть', onClick: () => { window.location.href = '/testing' } },
      })
    } catch (e) {
      toast.error('Не удалось сохранить snapshot', { description: String(e) })
    } finally {
      setSavingSnap(false)
    }
  }

  const handleSaveFavorite = async () => {
    if (!query.trim()) return
    setSavingFav(true)
    try {
      await createFavorite(buildFavoritePayload())
      setFavSaved(true)
      void queryClient.invalidateQueries({ queryKey: ['favorites'] })
      toast.success('Добавлено в избранное')
      setTimeout(() => setFavSaved(false), 2500)
    } catch (e) {
      toast.error('Не удалось сохранить', { description: String(e) })
    } finally {
      setSavingFav(false)
    }
  }

  useEffect(() => {
    if (watchTimerRef.current) {
      clearInterval(watchTimerRef.current)
      watchTimerRef.current = null
    }
    if (watchMin <= 0 || !query.trim()) return

    const intervalMs = watchMin * 60_000
    watchTimerRef.current = setInterval(() => {
      if (document.visibilityState !== 'visible') return
      void createSnapshot(buildPayload()).then(() => {
        void queryClient.invalidateQueries({ queryKey: ['snapshots'] })
      })
    }, intervalMs)

    return () => {
      if (watchTimerRef.current) clearInterval(watchTimerRef.current)
      watchTimerRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchMin, query, selectedStores.join(','), refresh, limit])

  const onEvent = useCallback((event: string, data: unknown) => {
    handleSSEEvent(event, data)
  }, [handleSSEEvent])

  useSSE(sseUrl, onEvent)

  const hasActivity = Object.keys(storeProgress).length > 0
  const progressList = Object.values(storeProgress)

  // source — origin записи (не статус); используем Tag с tone, а не Badge через statusSystem.
  const sourceTone =
    source === 'cache' ? 'warn' :
    source === 'network' ? 'ok' :
    'neutral'

  // Единственный api-request лог для отображения
  const apiReq = apiLogs.find(l => l.type === 'request')
  const apiResp = apiLogs.find(l => l.type === 'response')
  const apiErr = apiLogs.find(l => l.type === 'error')

  return (
    <div className="p-4 space-y-4 max-w-5xl">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Поиск</h1>
        <p className="text-xs text-zinc-500 mt-0.5">
          Поиск через parsers API с отображением прогресса по магазинам
        </p>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
        <SearchForm
          stores={stores}
          onSearch={() => startSearch(stores.map(s => s.slug))}
          onStop={stopSearch}
        />
      </div>

      {/* Прогресс парсеров */}
      {hasActivity && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xxs font-medium text-zinc-400 uppercase tracking-wider">Прогресс</span>
            {totalMs != null && (
              <span className="text-xs text-zinc-500 flex items-center gap-2">
                <Clock size={11} /> <span className="font-mono tabular-nums">{totalMs}ms</span>
                {source && <Tag tone={sourceTone}>{source}</Tag>}
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
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
            <div className="flex items-center px-4 gap-2 flex-wrap">
              <Tabs.List className="border-b-0">
                <Tabs.Trigger value="results">
                  Результаты
                  {visibleResults.length > 0 && (
                    <span className="ml-1 font-mono text-xxs tabular-nums text-zinc-500">
                      {visibleResults.length}
                      {hiddenCount > 0 && `/${results.length}`}
                    </span>
                  )}
                </Tabs.Trigger>
                <Tabs.Trigger value="api-log">
                  API Log
                  {apiLogs.length > 0 && (
                    <span className="ml-1 font-mono text-xxs tabular-nums text-zinc-500">{apiLogs.length}</span>
                  )}
                </Tabs.Trigger>
              </Tabs.List>

              {/* Action-кнопки */}
              <div className="ml-auto flex items-center gap-2 py-1.5">
                <Button
                  variant="secondary"
                  size="xs"
                  icon={Save}
                  disabled={savingSnap || !query.trim()}
                  loading={savingSnap}
                  onClick={handleSaveSnapshot}
                  title="Сохранить snapshot этого запроса"
                >
                  Snapshot
                </Button>
                {savedSnapshotId !== null && (
                  <Link
                    to={`/testing`}
                    className="text-xs text-indigo-300 hover:text-indigo-200 font-mono"
                    title={`Snapshot #${savedSnapshotId} сохранён`}
                  >
                    #{savedSnapshotId}
                  </Link>
                )}

                <Button
                  variant={favSaved ? 'warn' : 'secondary'}
                  size="xs"
                  icon={Star}
                  disabled={savingFav || !query.trim()}
                  onClick={handleSaveFavorite}
                  title="Сохранить запрос в избранное"
                >
                  {favSaved ? 'Сохр.' : 'Избр.'}
                </Button>

                <Button
                  variant="secondary"
                  size="xs"
                  icon={Download}
                  disabled={results.length === 0}
                  onClick={() => downloadJson(results, `search-${query.trim() || 'results'}.json`)}
                  title="Экспорт результатов в JSON"
                >
                  JSON
                </Button>
                <Button
                  variant="secondary"
                  size="xs"
                  icon={Download}
                  disabled={results.length === 0}
                  onClick={() => downloadCsv(
                    results as unknown as Array<Record<string, unknown>>,
                    [
                      { key: 'id', label: 'id' },
                      { key: 'store_slug', label: 'store' },
                      { key: 'title', label: 'title' },
                      { key: 'price_rub', label: 'price_rub' },
                      { key: 'url', label: 'url' },
                      { key: 'players', label: 'players' },
                      { key: 'age_min', label: 'age_min' },
                      { key: 'playtime', label: 'playtime' },
                    ],
                    `search-${query.trim() || 'results'}.csv`,
                  )}
                  title="Экспорт результатов в CSV"
                >
                  CSV
                </Button>

                <select
                  value={watchMin}
                  onChange={e => setWatchMin(Number(e.target.value))}
                  className="h-6 px-2 rounded text-xxs bg-zinc-900 border border-zinc-800 text-zinc-200 focus:outline-none focus:border-indigo-500"
                  title={watchMin > 0 ? `Watch включён: snapshot каждые ${watchMin} мин` : 'Watch — авто-snapshot по интервалу'}
                >
                  <option value={0}>Watch: off</option>
                  <option value={5}>каждые 5 мин</option>
                  <option value={15}>каждые 15 мин</option>
                  <option value={30}>каждые 30 мин</option>
                  <option value={60}>каждый час</option>
                </select>
                {watchMin > 0
                  ? <Eye size={12} className="text-emerald-400" />
                  : <EyeOff size={12} className="text-zinc-600" />
                }
              </div>
            </div>

            <div className="p-4 border-t border-zinc-800">
              <Tabs.Content value="results">
                {/* Header-bar: toggle group/flat + skipped-stock note */}
                <div className="flex items-center gap-2 mb-3 flex-wrap">
                  <div className="inline-flex rounded border border-zinc-800 overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setGroupMode('group')}
                      className={`inline-flex items-center gap-1 h-7 px-2.5 text-xs ${
                        groupMode === 'group'
                          ? 'bg-indigo-500/15 text-indigo-200'
                          : 'bg-transparent text-zinc-400 hover:bg-zinc-800/40'
                      }`}
                      title="По канонической игре (frontend-clustering)"
                    >
                      <Layers size={12} />
                      По игре
                      {grouped && (
                        <span className="ml-1 font-mono text-xxs tabular-nums text-zinc-500">
                          {grouped.stats.totalGroups}
                        </span>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => setGroupMode('flat')}
                      className={`inline-flex items-center gap-1 h-7 px-2.5 text-xs border-l border-zinc-800 ${
                        groupMode === 'flat'
                          ? 'bg-indigo-500/15 text-indigo-200'
                          : 'bg-transparent text-zinc-400 hover:bg-zinc-800/40'
                      }`}
                      title="Плоский список (debug)"
                    >
                      <List size={12} />
                      Плоский
                      <span className="ml-1 font-mono text-xxs tabular-nums text-zinc-500">
                        {visibleResults.length}
                      </span>
                    </button>
                  </div>

                  {hiddenCount > 0 && (
                    <span className="text-xs text-zinc-500">
                      Скрыто {hiddenCount}.
                      <button
                        type="button"
                        onClick={() => setShowOutOfStock(true)}
                        className="text-indigo-300 hover:text-indigo-200 underline ml-1"
                      >
                        Показать
                      </button>
                    </span>
                  )}

                  {grouped && (
                    <span className="ml-auto text-xxs text-zinc-500 font-mono tabular-nums">
                      {grouped.stats.totalGroups} игр · {grouped.stats.totalOffers} офферов
                      {grouped.stats.totalOrphans > 0 && (
                        <> · <span className="text-amber-300">{grouped.stats.totalOrphans} unmatched</span></>
                      )}
                    </span>
                  )}
                </div>

                {groupMode === 'group' && grouped ? (
                  <>
                    <ResultsTableGrouped
                      data={grouped}
                      selectedId={selectedGroupKey}
                      onSelectGroup={handleSelectGroup}
                    />
                    <UnmatchedSection
                      orphans={grouped.orphans}
                      onSelectOrphan={setSelectedProduct}
                    />
                  </>
                ) : (
                  <ResultsTable
                    products={visibleResults}
                    deltas={deltas}
                    adjusted={adjusted}
                    priceStats={priceStats}
                    showOutOfStock={showOutOfStock}
                    onSelect={setSelectedProduct}
                  />
                )}
              </Tabs.Content>

              <Tabs.Content value="api-log">
                <div className="space-y-3">
                  {apiLogs.length === 0 && (
                    <div className="text-sm text-zinc-500 text-center py-8">
                      {isSearching ? 'Ожидание ответа от parsers API…' : 'Нет запросов'}
                    </div>
                  )}

                  {apiReq && (
                    <div className="bg-zinc-950 border border-zinc-800 rounded p-3 space-y-1.5">
                      <div className="flex items-center gap-2 text-xs">
                        <ArrowUp size={11} className="text-indigo-400" />
                        <span className="text-indigo-300 font-mono font-bold">GET</span>
                        <span className="text-zinc-300 font-mono truncate">{apiReq.url}</span>
                      </div>
                      <div className="text-xs text-zinc-500 font-mono">
                        q={apiReq.q}
                        {apiReq.stores && ` stores=${apiReq.stores.join(',')}`}
                      </div>
                    </div>
                  )}

                  {apiResp && (
                    <div className="bg-zinc-950 border border-zinc-800 rounded p-3 space-y-2">
                      <div className="flex items-center gap-3 text-xs">
                        <ArrowDown size={11} className="text-emerald-400" />
                        <span className="text-emerald-300 font-mono font-bold">{apiResp.status}</span>
                        <span className="text-zinc-400 font-mono tabular-nums">{apiResp.elapsed_ms}ms</span>
                        <Tag tone={apiResp.source === 'cache' ? 'warn' : 'ok'}>
                          {apiResp.source}
                        </Tag>
                      </div>
                      <div className="flex gap-4 text-xs text-zinc-400">
                        <span>Продуктов: <span className="text-zinc-200 font-mono tabular-nums">{apiResp.products_count}</span></span>
                        {(apiResp.error_count ?? 0) > 0 && (
                          <Badge tone="danger" size="xs" dot={false}>
                            Ошибок магазинов: {apiResp.error_count}
                          </Badge>
                        )}
                      </div>
                    </div>
                  )}

                  {apiErr && (
                    <div className="bg-rose-500/10 border border-rose-500/30 rounded p-3 text-xs">
                      <div className="flex items-center gap-2 text-rose-300 mb-1">
                        <AlertCircle size={13} /> parsers API недоступен
                      </div>
                      <div className="text-rose-200 font-mono">{apiErr.error}</div>
                      <div className="text-zinc-500 mt-1">{apiErr.elapsed_ms}ms</div>
                    </div>
                  )}

                  {progressList.filter(p => p.status === 'error').map(p => (
                    <div key={p.slug} className="bg-amber-500/10 border border-amber-500/30 rounded p-2.5 text-xs">
                      <div className="flex items-center gap-2 text-amber-300">
                        <Zap size={11} /> Частичная ошибка: {p.name}
                      </div>
                      <div className="text-zinc-400 mt-0.5 font-mono">{p.error}</div>
                    </div>
                  ))}
                </div>
              </Tabs.Content>
            </div>
          </Tabs>
        </div>
      )}

      <ProductDrawer
        product={selectedProduct}
        pool={visibleResults}
        onClose={() => setSelectedProduct(null)}
        onSelect={setSelectedProduct}
      />
    </div>
  )
}
