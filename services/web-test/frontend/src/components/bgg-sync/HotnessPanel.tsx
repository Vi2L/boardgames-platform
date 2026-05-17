/**
 * HotnessPanel — текущий снимок BGG /hot + history dropdown + diff (новые/выбывшие).
 *
 * Архитектура:
 *  - Левый столбец: select даты + 50 карточек hotness с обложкой, рангом, годом.
 *    Каждая карточка показывает «✓ в каталоге» если есть game_id.
 *  - Правый столбец: select сравнения + список added/removed (Set difference
 *    клиентом по двум снимкам — один JSON-запрос на каждую дату, никакой
 *    логики на бэке).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ExternalLink, ArrowDown, ArrowUp, Minus, CheckCircle2 } from 'lucide-react'
import clsx from 'clsx'

import {
  fetchHotnessDates,
  fetchHotnessSnapshot,
  type HotnessItem,
  type HotnessSnapshot,
} from '../../lib/bgg-sync'

export function HotnessPanel() {
  const dates = useQuery({
    queryKey: ['bgg-sync', 'hotness', 'dates'],
    queryFn: () => fetchHotnessDates(30),
  })

  const [primaryDate, setPrimaryDate] = useState<string | undefined>()
  const [compareDate, setCompareDate] = useState<string | undefined>()

  // Default: latest snapshot, без compare.
  const effectivePrimary = primaryDate ?? dates.data?.[0]

  const primarySnap = useQuery({
    queryKey: ['bgg-sync', 'hotness', 'snapshot', effectivePrimary],
    queryFn: () => fetchHotnessSnapshot(effectivePrimary),
    enabled: !!effectivePrimary,
  })
  const compareSnap = useQuery({
    queryKey: ['bgg-sync', 'hotness', 'snapshot', compareDate],
    queryFn: () => fetchHotnessSnapshot(compareDate!),
    enabled: !!compareDate,
  })

  if (dates.isLoading) {
    return <div className="text-xs text-gray-500 py-4 flex items-center gap-2">
      <Loader2 size={12} className="animate-spin" /> Загружаю даты…
    </div>
  }

  if (!dates.data || dates.data.length === 0) {
    return (
      <div className="text-xs text-gray-500 py-6 text-center border border-dashed border-gray-800 rounded">
        Hotness ещё не загружался. Перейдите на вкладку «Расписание» и нажмите
        «Запустить» рядом с <strong>BGG Hotness</strong>.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-200">Снимок</h3>
          <select
            value={effectivePrimary ?? ''}
            onChange={e => setPrimaryDate(e.target.value)}
            className="px-2 py-1 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            {dates.data.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
        <SnapshotList snapshot={primarySnap.data} loading={primarySnap.isLoading} />
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-200">Diff</h3>
          <select
            value={compareDate ?? ''}
            onChange={e => setCompareDate(e.target.value || undefined)}
            className="px-2 py-1 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="">— сравнить с… —</option>
            {dates.data
              .filter(d => d !== effectivePrimary)
              .map(d => (
                <option key={d} value={d}>{d}</option>
              ))}
          </select>
        </div>
        {compareDate && primarySnap.data && compareSnap.data ? (
          <DiffView a={compareSnap.data} b={primarySnap.data} />
        ) : (
          <div className="text-xs text-gray-500 py-8 text-center border border-dashed border-gray-800 rounded">
            Выберите дату слева для сравнения.
            <br />
            Будет показано: какие игры новые в текущем снимке, какие выпали,
            и кто изменил позицию.
          </div>
        )}
      </section>
    </div>
  )
}

// ── Subcomponents ────────────────────────────────────────────────────────────

function SnapshotList({
  snapshot,
  loading,
}: {
  snapshot: HotnessSnapshot | undefined
  loading: boolean
}) {
  if (loading) {
    return <div className="text-xs text-gray-500 py-4 flex items-center gap-2">
      <Loader2 size={12} className="animate-spin" /> Загружаю снимок…
    </div>
  }
  if (!snapshot || snapshot.items.length === 0) {
    return <div className="text-xs text-gray-500 py-4">Снимок пуст.</div>
  }

  return (
    <div className="border border-gray-800 rounded divide-y divide-gray-800/60">
      {snapshot.items.map(item => <HotnessRow key={item.bgg_id} item={item} />)}
    </div>
  )
}

function HotnessRow({ item }: { item: HotnessItem }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 hover:bg-gray-900/40">
      <div className="w-8 text-right text-indigo-400 font-mono text-xs flex-shrink-0">
        #{item.rank}
      </div>
      {item.thumbnail_url ? (
        <img
          src={item.thumbnail_url}
          alt=""
          className="w-10 h-10 rounded object-cover flex-shrink-0 bg-gray-900"
        />
      ) : (
        <div className="w-10 h-10 rounded bg-gray-900 flex-shrink-0" />
      )}
      <div className="flex-1 min-w-0">
        <div className="text-xs text-gray-200 truncate">{item.name}</div>
        <div className="text-[10px] text-gray-500">
          {item.year ?? '—'} · bgg_id={item.bgg_id}
          {item.game_id && (
            <span className="ml-2 text-emerald-400 inline-flex items-center gap-0.5">
              <CheckCircle2 size={10} /> в каталоге
            </span>
          )}
        </div>
      </div>
      <a
        href={`https://boardgamegeek.com/boardgame/${item.bgg_id}`}
        target="_blank"
        rel="noopener noreferrer"
        title="Открыть на BGG"
        className="text-gray-500 hover:text-indigo-300 flex-shrink-0"
      >
        <ExternalLink size={12} />
      </a>
    </div>
  )
}

// ── Diff: Set-difference на client-side ──────────────────────────────────────

function DiffView({ a, b }: { a: HotnessSnapshot; b: HotnessSnapshot }) {
  const diff = useMemo(() => {
    const aMap = new Map(a.items.map(i => [i.bgg_id, i] as const))
    const bMap = new Map(b.items.map(i => [i.bgg_id, i] as const))

    const added = b.items.filter(i => !aMap.has(i.bgg_id))
    const removed = a.items.filter(i => !bMap.has(i.bgg_id))

    // Persisted: есть в обоих → diff в rank (b.rank − a.rank, отрицательный = поднялся).
    type RankDelta = HotnessItem & { delta: number }
    const persisted: RankDelta[] = []
    for (const item of b.items) {
      const aItem = aMap.get(item.bgg_id)
      if (aItem) {
        persisted.push({ ...item, delta: item.rank - aItem.rank })
      }
    }
    persisted.sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta))

    return { added, removed, persisted }
  }, [a, b])

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="border border-emerald-900/40 bg-emerald-950/10 rounded p-2">
          <div className="text-[10px] uppercase tracking-wide text-emerald-400 mb-1">
            Новые ({diff.added.length})
          </div>
          {diff.added.length === 0 ? (
            <div className="text-[11px] text-gray-500">—</div>
          ) : (
            <ul className="space-y-0.5 text-[11px]">
              {diff.added.map(it => (
                <li key={it.bgg_id} className="text-emerald-300 truncate">
                  #{it.rank} {it.name}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="border border-red-900/40 bg-red-950/10 rounded p-2">
          <div className="text-[10px] uppercase tracking-wide text-red-400 mb-1">
            Выпали ({diff.removed.length})
          </div>
          {diff.removed.length === 0 ? (
            <div className="text-[11px] text-gray-500">—</div>
          ) : (
            <ul className="space-y-0.5 text-[11px]">
              {diff.removed.map(it => (
                <li key={it.bgg_id} className="text-red-300 truncate">
                  #{it.rank} {it.name}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <details>
        <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-200">
          Изменения позиции ({diff.persisted.filter(p => p.delta !== 0).length} игр сдвинулись)
        </summary>
        <div className="mt-2 max-h-72 overflow-y-auto border border-gray-800 rounded divide-y divide-gray-800/60">
          {diff.persisted.filter(p => p.delta !== 0).map(p => (
            <div key={p.bgg_id} className="flex items-center gap-2 px-3 py-1.5 text-[11px]">
              <span className="font-mono text-gray-500 w-12 text-right">
                #{p.rank}
              </span>
              <span className="flex-1 text-gray-300 truncate">{p.name}</span>
              <span className={clsx(
                'flex items-center gap-0.5 font-mono w-12 justify-end',
                p.delta < 0 ? 'text-emerald-400' : 'text-red-400',
              )}>
                {p.delta < 0 ? <ArrowUp size={10} /> : p.delta > 0 ? <ArrowDown size={10} /> : <Minus size={10} />}
                {Math.abs(p.delta)}
              </span>
            </div>
          ))}
          {diff.persisted.filter(p => p.delta !== 0).length === 0 && (
            <div className="px-3 py-2 text-[11px] text-gray-500">
              Все игры сохранили свои позиции.
            </div>
          )}
        </div>
      </details>
    </div>
  )
}
