import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Trash2, GitCompare, Star, Play, FlaskConical } from 'lucide-react'
import clsx from 'clsx'
import {
  fetchSnapshots, deleteSnapshot, fetchSuites, createSuite,
  fetchFavorites, deleteFavorite,
} from '../lib/api'
import { useSearchStore } from '../store/search'
import { useLoyaltyStore } from '../store/loyalty'
import { SuiteRunner } from '../components/testing/SuiteRunner'
import type { FavoriteOut, SnapshotMeta, SuiteOut, SuiteQuery } from '../types/api'

type Tab = 'snapshots' | 'suites' | 'favorites'

export function TestingPage() {
  const [tab, setTab] = useState<Tab>('snapshots')

  return (
    <div className="space-y-4 max-w-6xl">
      <div>
        <h1 className="text-lg font-semibold text-gray-100 flex items-center gap-2">
          <FlaskConical size={18} /> Тестирование
        </h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Snapshots, регрессионный diff, test-сьюты, избранное
        </p>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="flex border-b border-gray-800">
          <TabButton active={tab === 'snapshots'} onClick={() => setTab('snapshots')}>Snapshots</TabButton>
          <TabButton active={tab === 'suites'} onClick={() => setTab('suites')}>Сьюты</TabButton>
          <TabButton active={tab === 'favorites'} onClick={() => setTab('favorites')}>Избранное</TabButton>
        </div>
        <div className="p-4">
          {tab === 'snapshots' && <SnapshotsTab />}
          {tab === 'suites' && <SuitesTab />}
          {tab === 'favorites' && <FavoritesTab />}
        </div>
      </div>
    </div>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
        active ? 'border-violet-500 text-violet-400' : 'border-transparent text-gray-500 hover:text-gray-300',
      )}
    >
      {children}
    </button>
  )
}

// ── Snapshots ──────────────────────────────────────────────────────────────

function SnapshotsTab() {
  const [selected, setSelected] = useState<number[]>([])
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['snapshots'],
    queryFn: () => fetchSnapshots(1, 100),
  })

  const items = data?.items ?? []

  const toggle = (id: number) => {
    setSelected(s => {
      if (s.includes(id)) return s.filter(x => x !== id)
      // Максимум два выделенных — для diff
      const next = [...s, id]
      return next.slice(-2)
    })
  }

  const handleDelete = async (id: number) => {
    if (!confirm(`Удалить snapshot #${id}?`)) return
    await deleteSnapshot(id)
    void queryClient.invalidateQueries({ queryKey: ['snapshots'] })
  }

  if (isLoading) return <div className="text-sm text-gray-500 py-8 text-center">Загрузка…</div>

  if (items.length === 0) {
    return (
      <div className="text-sm text-gray-500 py-12 text-center">
        Snapshots пока нет. Запусти поиск и нажми «💾 Snapshot» на странице поиска.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {selected.length === 2 && (
        <div className="flex items-center gap-2 bg-violet-950/30 border border-violet-800 rounded p-2.5">
          <span className="text-xs text-violet-300">Выбрано 2 snapshot-а</span>
          <Link
            to={`/testing/diff?a=${selected[0]}&b=${selected[1]}`}
            className="ml-auto flex items-center gap-1.5 px-3 py-1 rounded bg-violet-700 hover:bg-violet-600 text-white text-xs font-medium"
          >
            <GitCompare size={12} /> Сравнить
          </Link>
        </div>
      )}

      <div className="space-y-1.5">
        {items.map(s => <SnapshotRow key={s.id} snap={s} selected={selected.includes(s.id)}
          onToggle={() => toggle(s.id)} onDelete={() => handleDelete(s.id)} />)}
      </div>
    </div>
  )
}

function SnapshotRow({
  snap, selected, onToggle, onDelete,
}: {
  snap: SnapshotMeta; selected: boolean
  onToggle: () => void; onDelete: () => void
}) {
  return (
    <div className={clsx(
      'flex items-center gap-3 px-3 py-2 rounded border',
      selected ? 'border-violet-700 bg-violet-950/20' : 'border-gray-800 bg-gray-950/40',
    )}>
      <input type="checkbox" checked={selected} onChange={onToggle} className="cursor-pointer" />
      <span className="font-mono text-xs text-gray-500 w-12">#{snap.id}</span>
      <span className="font-medium text-gray-200 truncate flex-1" title={snap.name ?? snap.query}>
        {snap.name ?? snap.query}
      </span>
      <span className="text-xs text-gray-500">{snap.summary.products_count ?? 0} товаров</span>
      {snap.source && (
        <span className={clsx(
          'px-1.5 py-0.5 rounded text-xs font-mono',
          snap.source === 'cache' ? 'bg-yellow-950 text-yellow-400'
            : snap.source === 'network' ? 'bg-green-950 text-green-400'
            : 'bg-gray-800 text-gray-400',
        )}>
          {snap.source}
        </span>
      )}
      {snap.total_ms != null && <span className="text-xs text-gray-500 font-mono">{snap.total_ms}ms</span>}
      <span className="text-xs text-gray-600 hidden md:inline">
        {new Date(snap.created_at).toLocaleString('ru-RU')}
      </span>
      <button
        type="button"
        onClick={onDelete}
        className="p-1 rounded text-gray-500 hover:text-red-400 hover:bg-red-950/30"
      >
        <Trash2 size={13} />
      </button>
    </div>
  )
}

// ── Suites ─────────────────────────────────────────────────────────────────

function SuitesTab() {
  const queryClient = useQueryClient()
  const { data: suites = [], isLoading } = useQuery({ queryKey: ['suites'], queryFn: fetchSuites })
  const [selected, setSelected] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)

  if (isLoading) return <div className="text-sm text-gray-500 py-8 text-center">Загрузка…</div>

  const current = suites.find(s => s.id === selected) ?? null

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <select
          value={selected ?? ''}
          onChange={e => setSelected(e.target.value ? Number(e.target.value) : null)}
          className="flex-1 px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200"
        >
          <option value="">Выбери сьют…</option>
          {suites.map(s => <option key={s.id} value={s.id}>{s.name} ({s.queries.length})</option>)}
        </select>
        <button
          type="button"
          onClick={() => setCreating(c => !c)}
          className="px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-200"
        >
          {creating ? 'Отмена' : '+ Создать'}
        </button>
      </div>

      {creating && (
        <SuiteEditor
          onCreated={(s) => {
            void queryClient.invalidateQueries({ queryKey: ['suites'] })
            setSelected(s.id)
            setCreating(false)
          }}
        />
      )}

      {current && (
        <SuiteRunner
          suite={current}
          onDeleted={() => {
            void queryClient.invalidateQueries({ queryKey: ['suites'] })
            setSelected(null)
          }}
        />
      )}
    </div>
  )
}

function SuiteEditor({ onCreated }: { onCreated: (s: SuiteOut) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [queriesText, setQueriesText] = useState('Каркассон\nМанчкин')
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setError(null)
    const queries: SuiteQuery[] = queriesText
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)
      .map(q => ({ q }))
    if (!name.trim() || queries.length === 0) {
      setError('Имя и хотя бы один запрос обязательны')
      return
    }
    try {
      const created = await createSuite({
        name: name.trim(),
        description: description.trim() || undefined,
        queries,
      })
      onCreated(created)
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <div className="bg-gray-950/40 border border-gray-800 rounded p-3 space-y-2">
      <input
        type="text"
        placeholder="Имя сьюта"
        value={name}
        onChange={e => setName(e.target.value)}
        className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200"
      />
      <input
        type="text"
        placeholder="Описание (опц.)"
        value={description}
        onChange={e => setDescription(e.target.value)}
        className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200"
      />
      <textarea
        rows={5}
        placeholder="Запросы — по одному на строку"
        value={queriesText}
        onChange={e => setQueriesText(e.target.value)}
        className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 font-mono"
      />
      {error && <div className="text-xs text-red-400">{error}</div>}
      <button
        type="button"
        onClick={submit}
        className="px-3 py-1.5 rounded bg-violet-700 hover:bg-violet-600 text-white text-xs font-medium"
      >
        Сохранить
      </button>
    </div>
  )
}

// ── Favorites ──────────────────────────────────────────────────────────────

function FavoritesTab() {
  const queryClient = useQueryClient()
  const { data: items = [], isLoading } = useQuery({ queryKey: ['favorites'], queryFn: fetchFavorites })
  const { setQuery, setRefresh, setLimit, setAllStores, setShowOutOfStock } = useSearchStore()
  const { setEnabled: setLoyaltyEnabled, setHobby, setLavka } = useLoyaltyStore()

  const handleDelete = async (id: number) => {
    if (!confirm(`Удалить избранное #${id}?`)) return
    await deleteFavorite(id)
    void queryClient.invalidateQueries({ queryKey: ['favorites'] })
  }

  const handleRun = (f: FavoriteOut) => {
    setQuery(f.query)
    if (f.stores) setAllStores(f.stores.split(',').map(s => s.trim()).filter(Boolean))
    setRefresh(f.refresh)
    if (f.limit_n != null) setLimit(f.limit_n)
    if (typeof f.show_out_of_stock === 'boolean') setShowOutOfStock(f.show_out_of_stock)
    // Распаковка loyalty preset. Опциональные поля: если в favorite их нет —
    // не трогаем текущий стор (бэкаппчат пользовательский конфиг).
    const ly = f.loyalty as undefined | {
      enabled?: boolean
      hobbygames?: { enabled?: boolean; bonuses?: 'unlim' | number }
      lavkaigr?: { enabled?: boolean; percent?: number; vkDon?: boolean }
    }
    if (ly) {
      if (typeof ly.enabled === 'boolean') setLoyaltyEnabled(ly.enabled)
      if (ly.hobbygames) setHobby(ly.hobbygames)
      if (ly.lavkaigr) setLavka(ly.lavkaigr)
    }
  }

  if (isLoading) return <div className="text-sm text-gray-500 py-8 text-center">Загрузка…</div>
  if (items.length === 0) {
    return (
      <div className="text-sm text-gray-500 py-12 text-center">
        Избранного нет. На странице поиска нажми ⭐ рядом с результатами.
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      {items.map(f => (
        <div key={f.id} className="flex items-center gap-3 px-3 py-2 rounded bg-gray-950/40 border border-gray-800">
          <Star size={13} className="text-yellow-400" fill="currentColor" />
          <span className="font-medium text-gray-200 truncate flex-1">{f.query}</span>
          {f.stores && <span className="text-xs text-gray-500">{f.stores}</span>}
          {f.refresh && <span className="text-xs text-orange-400">refresh</span>}
          <Link
            to="/"
            onClick={() => handleRun(f)}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-violet-900/40 hover:bg-violet-900/60 text-violet-300 text-xs"
          >
            <Play size={10} /> Запустить
          </Link>
          <button
            type="button"
            onClick={() => handleDelete(f.id)}
            className="p-1 rounded text-gray-500 hover:text-red-400 hover:bg-red-950/30"
          >
            <Trash2 size={13} />
          </button>
        </div>
      ))}
    </div>
  )
}
