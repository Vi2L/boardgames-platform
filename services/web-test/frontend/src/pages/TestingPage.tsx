import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Trash2, GitCompare, Star, Play, FlaskConical, Save } from 'lucide-react'
import clsx from 'clsx'
import {
  fetchSnapshots, deleteSnapshot, fetchSuites, createSuite,
  fetchFavorites, deleteFavorite,
} from '../lib/api'
import { useSearchStore } from '../store/search'
import { useLoyaltyStore } from '../store/loyalty'
import { SuiteRunner } from '../components/testing/SuiteRunner'
import type { FavoriteOut, SnapshotMeta, SuiteOut, SuiteQuery } from '../types/api'
import { Tabs, Tag, Button, IconButton, EmptyState, Badge } from '../components/ui'

type Tab = 'snapshots' | 'suites' | 'favorites'

export function TestingPage() {
  const [tab, setTab] = useState<Tab>('snapshots')

  return (
    <div className="p-4 space-y-4 max-w-6xl">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
          <FlaskConical size={18} /> Тестирование
        </h1>
        <p className="text-xs text-zinc-500 mt-0.5">
          Snapshots, регрессионный diff, test-сьюты, избранное
        </p>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
        <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
          <Tabs.List className="px-3">
            <Tabs.Trigger value="snapshots">Snapshots</Tabs.Trigger>
            <Tabs.Trigger value="suites">Сьюты</Tabs.Trigger>
            <Tabs.Trigger value="favorites">Избранное</Tabs.Trigger>
          </Tabs.List>
          <div className="p-4">
            <Tabs.Content value="snapshots"><SnapshotsTab /></Tabs.Content>
            <Tabs.Content value="suites"><SuitesTab /></Tabs.Content>
            <Tabs.Content value="favorites"><FavoritesTab /></Tabs.Content>
          </div>
        </Tabs>
      </div>
    </div>
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

  if (isLoading) return <div className="text-sm text-zinc-500 py-8 text-center">Загрузка…</div>

  if (items.length === 0) {
    return (
      <EmptyState
        icon={Save}
        title="Snapshots пока нет"
        description="Запусти поиск и нажми «Snapshot» на странице поиска."
      />
    )
  }

  return (
    <div className="space-y-3">
      {selected.length === 2 && (
        <div className="flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/30 rounded p-2.5">
          <span className="text-xs text-indigo-200">Выбрано 2 snapshot-а</span>
          <Button asChild variant="primary" size="sm" icon={GitCompare} className="ml-auto">
            <Link to={`/testing/diff?a=${selected[0]}&b=${selected[1]}`}>Сравнить</Link>
          </Button>
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
  // source — это не статус пайплайна, а origin записи. Используем Tag,
  // а не Badge через statusSystem (см. tokens/status-system.md).
  const sourceTone =
    snap.source === 'cache' ? 'warn' :
    snap.source === 'network' ? 'ok' :
    'neutral'

  return (
    <div className={clsx(
      'flex items-center gap-3 px-3 py-2 rounded border',
      selected ? 'border-indigo-500/50 bg-indigo-500/10' : 'border-zinc-800 bg-zinc-950/40',
    )}>
      <input type="checkbox" checked={selected} onChange={onToggle} className="cursor-pointer" />
      <span className="font-mono text-xs text-zinc-500 w-12">#{snap.id}</span>
      <span className="font-medium text-zinc-200 truncate flex-1" title={snap.name ?? snap.query}>
        {snap.name ?? snap.query}
      </span>
      <span className="text-xs text-zinc-500 tabular-nums">{snap.summary.products_count ?? 0} товаров</span>
      {snap.source && <Tag tone={sourceTone}>{snap.source}</Tag>}
      {snap.total_ms != null && <span className="text-xs text-zinc-500 font-mono tabular-nums">{snap.total_ms}ms</span>}
      <span className="text-xs text-zinc-600 hidden md:inline">
        {new Date(snap.created_at).toLocaleString('ru-RU')}
      </span>
      <IconButton
        icon={Trash2}
        size="xs"
        variant="ghost"
        aria-label={`Удалить snapshot #${snap.id}`}
        onClick={onDelete}
      />
    </div>
  )
}

// ── Suites ─────────────────────────────────────────────────────────────────

function SuitesTab() {
  const queryClient = useQueryClient()
  const { data: suites = [], isLoading } = useQuery({ queryKey: ['suites'], queryFn: fetchSuites })
  const [selected, setSelected] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)

  if (isLoading) return <div className="text-sm text-zinc-500 py-8 text-center">Загрузка…</div>

  const current = suites.find(s => s.id === selected) ?? null

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <select
          value={selected ?? ''}
          onChange={e => setSelected(e.target.value ? Number(e.target.value) : null)}
          className="flex-1 h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
        >
          <option value="">Выбери сьют…</option>
          {suites.map(s => <option key={s.id} value={s.id}>{s.name} ({s.queries.length})</option>)}
        </select>
        <Button
          variant={creating ? 'ghost' : 'secondary'}
          size="sm"
          onClick={() => setCreating(c => !c)}
        >
          {creating ? 'Отмена' : '+ Создать'}
        </Button>
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
    <div className="bg-zinc-950/40 border border-zinc-800 rounded p-3 space-y-2">
      <input
        type="text"
        placeholder="Имя сьюта"
        value={name}
        onChange={e => setName(e.target.value)}
        className="w-full h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
      />
      <input
        type="text"
        placeholder="Описание (опц.)"
        value={description}
        onChange={e => setDescription(e.target.value)}
        className="w-full h-7 px-2.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
      />
      <textarea
        rows={5}
        placeholder="Запросы — по одному на строку"
        value={queriesText}
        onChange={e => setQueriesText(e.target.value)}
        className="w-full px-2.5 py-1.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-200 font-mono focus:outline-none focus:border-indigo-500"
      />
      {error && <div className="text-xs text-rose-400">{error}</div>}
      <Button variant="primary" size="sm" onClick={submit}>
        Сохранить
      </Button>
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

  if (isLoading) return <div className="text-sm text-zinc-500 py-8 text-center">Загрузка…</div>
  if (items.length === 0) {
    return (
      <EmptyState
        icon={Star}
        title="Избранного нет"
        description="На странице поиска нажми иконку звезды рядом с результатами."
      />
    )
  }

  return (
    <div className="space-y-1.5">
      {items.map(f => (
        <div key={f.id} className="flex items-center gap-3 px-3 py-2 rounded bg-zinc-950/40 border border-zinc-800">
          <Star size={13} className="text-amber-400" fill="currentColor" />
          <span className="font-medium text-zinc-200 truncate flex-1">{f.query}</span>
          {f.stores && <span className="text-xs text-zinc-500">{f.stores}</span>}
          {f.refresh && <Badge tone="warn" size="xs" dot={false}>refresh</Badge>}
          <Button asChild variant="primary" size="xs" icon={Play}>
            <Link to="/" onClick={() => handleRun(f)}>Запустить</Link>
          </Button>
          <IconButton
            icon={Trash2}
            size="xs"
            variant="ghost"
            aria-label={`Удалить избранное #${f.id}`}
            onClick={() => handleDelete(f.id)}
          />
        </div>
      ))}
    </div>
  )
}
