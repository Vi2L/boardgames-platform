import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { toast } from 'sonner'
import type { ApiLog, ProductOut, StoreProgress } from '../types/api'

let logId = 0

interface SearchStore {
  query: string
  selectedStores: string[]
  refresh: boolean
  limit: number

  isSearching: boolean
  sseUrl: string | null
  storeProgress: Record<string, StoreProgress>
  apiLogs: ApiLog[]
  results: ProductOut[]
  totalMs: number | null
  source: string | null

  setQuery: (q: string) => void
  toggleStore: (slug: string) => void
  setAllStores: (slugs: string[]) => void
  clearStores: () => void
  setRefresh: (v: boolean) => void
  setLimit: (n: number) => void
  startSearch: (availableSlugs: string[]) => void
  stopSearch: () => void
  handleSSEEvent: (event: string, data: unknown) => void
  reset: () => void
}

/**
 * Zustand-стор поиска с частичной персистентностью в localStorage.
 *
 * Сохраняем только параметры формы (selectedStores/refresh/limit), не
 * результаты — иначе при reload пользователь увидел бы прошлые товары
 * до нового запроса. Query тоже не персистим: если он отражён в URL
 * (deep-link, фаза 5.2), URL — единственный источник правды.
 */
export const useSearchStore = create<SearchStore>()(persist((set, get) => ({
  query: '',
  selectedStores: [],
  refresh: false,
  limit: 10,
  isSearching: false,
  sseUrl: null,
  storeProgress: {},
  apiLogs: [],
  results: [],
  totalMs: null,
  source: null,

  setQuery: (q) => set({ query: q }),

  toggleStore: (slug) => set(s => ({
    selectedStores: s.selectedStores.includes(slug)
      ? s.selectedStores.filter(x => x !== slug)
      : [...s.selectedStores, slug],
  })),

  setAllStores: (slugs) => set({ selectedStores: slugs }),
  clearStores: () => set({ selectedStores: [] }),
  setRefresh: (v) => set({ refresh: v }),
  setLimit: (n) => set({ limit: n }),

  startSearch: (availableSlugs) => {
    const { query, selectedStores, refresh, limit } = get()
    if (!query.trim()) return

    const params = new URLSearchParams({ q: query.trim(), limit: String(limit) })
    if (refresh) params.set('refresh', 'true')
    if (selectedStores.length > 0) params.set('stores', selectedStores.join(','))

    const slugs = selectedStores.length > 0 ? selectedStores : availableSlugs
    const storeProgress: Record<string, StoreProgress> = {}
    slugs.forEach(slug => {
      storeProgress[slug] = { slug, name: slug, status: 'pending' }
    })

    set({
      isSearching: true,
      sseUrl: `/api/search?${params}`,
      storeProgress,
      apiLogs: [],
      results: [],
      totalMs: null,
      source: null,
    })
  },

  stopSearch: () => set({ sseUrl: null, isSearching: false }),

  handleSSEEvent: (event, data) => {
    const d = data as Record<string, unknown>

    set(s => {
      switch (event) {

        case 'store-start':
          return {
            storeProgress: {
              ...s.storeProgress,
              [d.slug as string]: {
                slug: d.slug as string,
                name: d.name as string,
                status: 'running' as const,
              },
            },
          }

        case 'store-done':
          return {
            storeProgress: {
              ...s.storeProgress,
              [d.slug as string]: {
                slug: d.slug as string,
                name: d.name as string,
                status: (d.error ? 'error' : 'done') as 'error' | 'done',
                count: d.count as number,
                elapsed_ms: d.elapsed_ms as number,
                error: d.error as string | undefined,
              },
            },
          }

        case 'api-request':
          return {
            apiLogs: [...s.apiLogs, {
              id: ++logId,
              type: 'request' as const,
              url: d.url as string,
              q: d.q as string,
              stores: d.stores as string[] | null,
              timestamp: Date.now(),
            }],
          }

        case 'api-response':
          return {
            apiLogs: [...s.apiLogs, {
              id: ++logId,
              type: 'response' as const,
              status: d.status as number,
              elapsed_ms: d.elapsed_ms as number,
              source: d.source as string,
              products_count: d.products_count as number,
              error_count: d.error_count as number,
              timestamp: Date.now(),
            }],
          }

        case 'api-error': {
          // Backend различает «нет данных» (status_code=503 от parsers) и
          // настоящую сетевую ошибку. UI выводит разные тосты, чтобы
          // пользователь не путал «ничего не нашлось» с «всё сломалось».
          const status = d.status_code as number | undefined
          const message = d.error as string
          if (status === 503) {
            toast.warning('Нет данных по запросу', { description: message })
          } else {
            toast.error('Ошибка parsers API', { description: message })
          }
          return {
            apiLogs: [...s.apiLogs, {
              id: ++logId,
              type: 'error' as const,
              error: message,
              elapsed_ms: d.elapsed_ms as number,
              timestamp: Date.now(),
            }],
            isSearching: false,
            sseUrl: null,
          }
        }

        case 'results':
          return {
            results: (d.products ?? []) as ProductOut[],
            totalMs: d.total_ms as number,
            source: d.source as string,
            isSearching: false,
            sseUrl: null,
          }

        default:
          return {}
      }
    })
  },

  reset: () => set({
    isSearching: false, sseUrl: null,
    storeProgress: {}, apiLogs: [], results: [], totalMs: null, source: null,
  }),
}), {
  name: 'search:form',
  storage: createJSONStorage(() => localStorage),
  // Только пользовательские настройки формы; рантайм-состояние не персистим.
  partialize: (s) => ({
    selectedStores: s.selectedStores,
    refresh: s.refresh,
    limit: s.limit,
  }),
}))
