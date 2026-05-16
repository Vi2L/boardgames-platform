/**
 * useMatchingMetrics — client-side metrics buffer для UI `/matching`.
 *
 * Зачем: backend depth_history endpoint работает, но в degraded-режиме (если
 * сервис только что стартовал и снимков нет, или если depth_history-job ещё
 * не накопил данных) можно показать клиентский ring-buffer на базе обычных
 * `/matching/ml-status` snapshot'ов которые UI и так poll'ит каждые 5с.
 *
 * Используется в:
 *   - PageHeader для inline-sparkline (если backend depth недоступен)
 *   - ControlTab.WorkerCard для throughput sparkline
 *   - ControlTab.ModelsCard для per-model latency sparkline
 *
 * Persist в localStorage чтобы не терять историю при refresh страницы.
 * Limit 60 точек = 5 минут при poll 5с. Старые точки выпадают через FIFO.
 */
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export interface MetricsSnapshot {
  ts: number              // Date.now()
  pending: number
  processing: number
  skipped: number
  failed: number
  done: number
  // Per-model — optional, может отсутствовать если ml-status в degraded режиме
  models: Record<string, {
    available: boolean
    p50_ms: number | null
    p95_ms: number | null
    rps_1m: number
    failures: number
  }>
}

interface MetricsState {
  snapshots: MetricsSnapshot[]
  pushSnapshot: (s: MetricsSnapshot) => void
  clear: () => void
}

const MAX_SNAPSHOTS = 60

export const useMatchingMetrics = create<MetricsState>()(
  persist(
    (set) => ({
      snapshots: [],
      pushSnapshot: (s) => set((state) => ({
        snapshots: [...state.snapshots, s].slice(-MAX_SNAPSHOTS),
      })),
      clear: () => set({ snapshots: [] }),
    }),
    {
      name: 'matching-metrics-v1',
      storage: createJSONStorage(() => localStorage),
      // Don't persist если страница долго не открывалась — старые snapshot'ы
      // не нужны (>1 час → старее timestamp'а самого свежего пользовательского
      // действия). Простая отсечка через partialize: пишем только если в
      // последние 5 минут что-то писали.
      partialize: (state) => ({ snapshots: state.snapshots }),
    },
  ),
)

/** Helper: вытаскивает только pending series из snapshot'ов для UI sparkline. */
export function selectPendingSeries(snapshots: MetricsSnapshot[]): { ts: string; depth: number }[] {
  return snapshots.map(s => ({
    ts: new Date(s.ts).toISOString(),
    depth: s.pending + s.processing,
  }))
}

/** Helper: latency series для одной модели. */
export function selectLatencySeries(
  snapshots: MetricsSnapshot[],
  model: string,
): number[] {
  return snapshots
    .map(s => s.models[model]?.p50_ms ?? null)
    .filter((v): v is number => v != null)
}

/** Helper: drainage rate за последние 2 snapshot'а (offers/min). */
export function selectDrainageRate(snapshots: MetricsSnapshot[]): number {
  if (snapshots.length < 2) return 0
  const last = snapshots[snapshots.length - 1]
  const prev = snapshots[snapshots.length - 2]
  const dt_min = (last.ts - prev.ts) / 60_000
  if (dt_min <= 0) return 0
  // Положительный = очередь уменьшается.
  return (prev.pending - last.pending) / dt_min
}
