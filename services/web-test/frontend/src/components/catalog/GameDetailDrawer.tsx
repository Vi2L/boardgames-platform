/**
 * GameDetailDrawer — Tabbed Workbench для админа каталога.
 *
 * Дизайн (вариант C из обсуждения):
 *  - Header: title, #id, action-кнопки (edit/merge/copy SQL).
 *  - Tab bar: Обзор / Локализация РФ / Алиасы / Offers / Дети / Источники /
 *             Аудит / Raw.
 *  - Все поля видны всегда — пустые рендерятся серым «—», чтобы оператор
 *    видел полноту схемы и понимал, что данные отсутствуют, а не что
 *    UI их не показывает.
 *  - Подсветка несоответствий («inconsistencies») — жёлтый banner вверху
 *    каждого таба, если something off (bgg_id есть, но satellite пуст; и т.п.).
 *  - Inline-edit click-to-edit для текстовых/числовых полей (kind, year,
 *    ru_publisher, ...). Сохранение через PATCH /games/{id}.
 *
 * Drawer 1100px (раньше 900) — для табов и offers-таблицы тесно.
 */
import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  X, Loader2, ExternalLink, Pencil, GitMerge, Copy, AlertTriangle,
  RefreshCw, ChevronDown, ChevronRight, Check,
} from 'lucide-react'
import clsx from 'clsx'
import {
  fetchCatalogGame,
  fetchGameOffers,
  fetchGameChildren,
  fetchPromotionLogForGame,
  fetchPromotionDicefestRaw,
  patchGame,
  reassessAll,
  type CatalogGameDetail,
  type CatalogGameKind,
  type CatalogOffer,
  type CatalogGameChild,
  type PromotionLogEntry,
  type DicefestRawGame,
  type GamePatchPayload,
} from '../../lib/catalog'
import { AliasEditor } from './AliasEditor'
import { BggCard } from './BggCard'
import { WikidataCard } from './WikidataCard'
import { GameEditor } from './GameEditor'
import { MergeDialog } from './MergeDialog'

interface Props {
  gameId: number
  onClose: () => void
}

// Все метаданные игры (включая локализацию РФ, алиасы, источники, детей)
// собраны в одну вкладку «Обзор» — длинный скролл с collapsible-секциями
// удобнее, чем прыжки между мелкими табами.
type TabId = 'overview' | 'offers' | 'audit' | 'raw'

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'overview', label: 'Обзор' },
  { id: 'offers', label: 'Offers' },
  { id: 'audit', label: 'Аудит' },
  { id: 'raw', label: 'Raw' },
]

export function GameDetailDrawer({ gameId, onClose }: Props) {
  const [tab, setTab] = useState<TabId>('overview')
  const [editing, setEditing] = useState(false)
  const [merging, setMerging] = useState(false)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['catalog', 'game-detail', gameId],
    queryFn: () => fetchCatalogGame(gameId),
  })

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="ml-auto w-[min(1100px,100vw)] h-full bg-gray-900 border-l border-gray-800 flex flex-col relative shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 flex-shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold text-gray-100 truncate">
              {data ? data.title : 'Карточка игры'}
            </span>
            <span className="text-xs font-mono text-gray-500">#{gameId}</span>
            {data?.kind && data.kind !== 'base' && (
              <KindBadge kind={data.kind} />
            )}
            {data?.is_localized_ru && (
              <span className="px-1.5 py-0.5 rounded text-[10px] bg-emerald-900/40 text-emerald-200 font-mono">
                RU
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {data && (
              <>
                <CopySqlButton game={data} />
                <button onClick={() => setMerging(true)} title="Объединить с другой игрой"
                        className="p-1 text-gray-400 hover:text-red-300 hover:bg-red-950/40 rounded">
                  <GitMerge size={14} />
                </button>
                <button onClick={() => setEditing(true)} title="Редактировать (полная форма)"
                        className="p-1 text-gray-400 hover:text-violet-300 hover:bg-violet-950/40 rounded">
                  <Pencil size={14} />
                </button>
              </>
            )}
            <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded">
              <X size={16} />
            </button>
          </div>
        </div>

        {editing && data && (
          <GameEditor mode="edit" game={data} onClose={() => setEditing(false)} />
        )}
        {merging && data && (
          <MergeDialog source={data} onClose={() => setMerging(false)} />
        )}

        {/* Tab bar */}
        <div className="flex border-b border-gray-800 flex-shrink-0 overflow-x-auto">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={clsx(
                'px-3 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap',
                tab === t.id
                  ? 'border-violet-500 text-violet-200'
                  : 'border-transparent text-gray-400 hover:text-gray-200',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-gray-500">
              <Loader2 size={18} className="animate-spin" />
            </div>
          )}
          {isError && (
            <div className="bg-red-950/50 border border-red-900/50 rounded p-3 text-sm text-red-400">
              {String(error)}
            </div>
          )}
          {data && (
            <>
              {/* Подсветка несоответствий — единый banner на всю карточку */}
              <Inconsistencies game={data} />

              {tab === 'overview' && <OverviewTab game={data} />}
              {tab === 'offers' && <OffersTab gameId={data.id} />}
              {tab === 'audit' && <AuditTab game={data} />}
              {tab === 'raw' && <RawTab game={data} />}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Inconsistencies banner ──────────────────────────────────────────

function Inconsistencies({ game }: { game: CatalogGameDetail }) {
  const issues: string[] = []
  if (game.bgg_id && !game.bgg) {
    issues.push('bgg_id указан, но game_bgg satellite пуст — запустите POST /import/bgg.')
  }
  if (game.is_localized_ru && !game.ru_publisher) {
    issues.push('is_localized_ru=true, но ru_publisher не заполнен.')
  }
  if (game.kind && game.kind !== 'base' && !game.parent_game_id) {
    issues.push(`kind='${game.kind}', но parent_game_id не указан — допы должны ссылаться на базу.`)
  }
  if (game.dicefest_id && !game.is_localized_ru) {
    issues.push('dicefest_id указан, но is_localized_ru=false (рассинхрон с промоушеном).')
  }
  if (game.status === 'merged' && !(game.meta as Record<string, unknown> | null)?.merged_into) {
    issues.push('status=merged, но meta.merged_into не указан — потеряна целевая игра.')
  }
  if (issues.length === 0) return null
  return (
    <div className="bg-amber-950/40 border border-amber-900/50 rounded p-2 space-y-1">
      <div className="flex items-center gap-2 text-xs text-amber-200 font-semibold">
        <AlertTriangle size={12} /> Несоответствия ({issues.length})
      </div>
      <ul className="text-xs text-amber-100/80 space-y-0.5 ml-4 list-disc">
        {issues.map((m, i) => <li key={i}>{m}</li>)}
      </ul>
    </div>
  )
}

// ─── Tab: Обзор ──────────────────────────────────────────────────────

function OverviewTab({ game }: { game: CatalogGameDetail }) {
  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        {game.cover_url ? (
          <img src={game.cover_url} alt="" className="w-40 h-40 object-contain rounded bg-gray-950 border border-gray-800 flex-shrink-0" />
        ) : (
          <div className="w-40 h-40 rounded bg-gray-950 border border-gray-800 flex-shrink-0
                          flex items-center justify-center text-xs text-gray-600">
            нет обложки
          </div>
        )}
        <div className="flex-1 min-w-0 space-y-1.5 text-xs">
          <Field label="id" value={String(game.id)} mono />
          <Field label="slug" value={game.slug} mono />
          <Field label="title" value={game.title} />
          <InlineEditField game={game} field="kind" type="select" options={['base','expansion','promo','accessory']} />
          <InlineEditField game={game} field="year" type="number" />
          <InlineEditField game={game} field="parent_game_id" type="number"
                           hint="ID базовой игры (для допов/промо/аксессуаров)" />
          <Field label="source" value={game.source} mono />
          <Field label="status" value={game.status} mono />
        </div>
      </div>

      <Section title="Параметры партии">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <InlineEditField game={game} field="players_min" type="number" label="игроков от" />
          <InlineEditField game={game} field="players_max" type="number" label="игроков до" />
          <InlineEditField game={game} field="age_min" type="number" label="возраст от" />
          <InlineEditField game={game} field="playtime_min" type="number" label="время мин" />
          <InlineEditField game={game} field="playtime_max" type="number" label="время макс" />
        </div>
      </Section>

      <Section title="Авторы">
        <div className="space-y-1.5 text-xs">
          <Field label="дизайнеры" value={fmtArr(game.designers)} />
          <Field label="издатели" value={fmtArr(game.publishers)} />
        </div>
      </Section>

      <Section title="Описание">
        {game.description ? (
          <div className="text-sm text-gray-300 leading-relaxed bg-gray-950 p-3 rounded max-h-48 overflow-y-auto">
            {game.description}
          </div>
        ) : (
          <Empty />
        )}
      </Section>

      <Section title="Локализация РФ">
        <div className="space-y-1.5 text-xs">
          <InlineEditField game={game} field="ru_publisher" type="text" label="издатель РФ" />
          <InlineEditField game={game} field="ru_release_year" type="number" label="год РФ" />
          <InlineEditField game={game} field="is_localized_ru" type="bool" label="is_localized_ru" />
          <InlineEditField game={game} field="preorder_price" type="kopecks" label="предзаказ" hint="копейки (1 ₽ = 100)" />
        </div>
      </Section>

      <Section title="Внешние ID и ссылки">
        <div className="space-y-1.5 text-xs">
          <Field label="bgg_id" value={game.bgg_id != null ? String(game.bgg_id) : ''} mono
                 link={game.bgg_id ? `https://boardgamegeek.com/boardgame/${game.bgg_id}` : undefined} />
          <Field label="tesera_id" value={game.tesera_id != null ? String(game.tesera_id) : ''} mono
                 link={game.tesera_id ? `https://tesera.ru/game/${game.tesera_id}/` : undefined} />
          <Field label="dicefest_id" value={game.dicefest_id != null ? String(game.dicefest_id) : ''} mono />
          <Field label="nastolio_id" value={game.nastolio_id ?? ''} mono
                 link={game.nastolio_id
                   ? (game.nastolio_id.startsWith('http')
                      ? game.nastolio_id
                      : `https://nastolio.ru/games/${game.nastolio_id}/`)
                   : undefined} />
          <Field label="wikidata" value={game.wikidata?.entity_id ?? ''} mono
                 link={game.wikidata?.entity_id
                   ? `https://www.wikidata.org/wiki/${game.wikidata.entity_id}`
                   : undefined} />
        </div>
      </Section>

      {/* Side-by-side с staging-записью dicefest. Lazy: запрос идёт только
          при первом раскрытии секции (render-prop в <Section>). */}
      {game.dicefest_id && (
        <Section title={`Raw из dicefest_raw_games #${game.dicefest_id}`} defaultOpen={false}>
          {() => <DicefestRawSidebar dicefestId={game.dicefest_id!} game={game} />}
        </Section>
      )}

      <Section title={`BGG satellite${game.bgg ? '' : ' — нет данных'}`} defaultOpen={false}>
        {game.bgg ? <BggCard bgg={game.bgg} /> : <Empty msg="Запустите POST /import/bgg для обогащения." />}
      </Section>

      <Section title={`Wikidata satellite${game.wikidata ? '' : ' — нет данных'}`} defaultOpen={false}>
        {game.wikidata ? <WikidataCard wikidata={game.wikidata} /> : <Empty msg="Запустите python -m catalog.scripts.import_wikidata." />}
      </Section>

      <Section title={`Алиасы (${game.aliases.length})`} defaultOpen={false}>
        <AliasesContent game={game} />
      </Section>

      {/* Lazy — useQuery запускается только когда секция открыта (mount при render-prop call). */}
      <Section title="Дети (допы / промо / аксессуары)" defaultOpen={false}>
        {() => <ChildrenContent gameId={game.id} />}
      </Section>

      <div className="text-[10px] text-gray-500 font-mono pt-2 border-t border-gray-800">
        created: {game.created_at.slice(0, 16).replace('T', ' ')} · updated: {game.updated_at.slice(0, 16).replace('T', ' ')}
      </div>
    </div>
  )
}

function DicefestRawSidebar({ dicefestId, game }: { dicefestId: number; game: CatalogGameDetail }) {
  // Lazy-mount внутри <Section> — запрос идёт только когда оператор раскрыл
  // секцию. <Section> уже обёрнута снаружи (см. OverviewTab).
  const { data, isLoading } = useQuery({
    queryKey: ['catalog', 'dicefest-raw', dicefestId],
    queryFn: () => fetchPromotionDicefestRaw(dicefestId),
  })
  if (isLoading) return <Loader2 size={14} className="animate-spin text-gray-500" />
  if (!data) return null
  return (
    <div className="grid grid-cols-2 gap-3 text-xs bg-gray-950/60 rounded p-3 border border-gray-800">
      <CompareCell label="title_ru" canonical={game.title} raw={data.title_ru} />
      <CompareCell label="publisher" canonical={game.ru_publisher} raw={data.publisher} />
      <CompareCell label="preorder" canonical={fmtKop(game.preorder_price)} raw={fmtKop(data.preorder_price)} />
      <CompareCell label="status (raw)" canonical={null} raw={data.status} />
      <div className="col-span-2 text-[10px] text-gray-500 font-mono">
        <a href={data.page_url} target="_blank" rel="noreferrer" className="hover:text-gray-300 underline">
          {data.page_url}
        </a>
      </div>
    </div>
  )
}

function CompareCell({ label, canonical, raw }: { label: string; canonical: string | null | undefined; raw: string | null | undefined }) {
  const same = (canonical ?? '') === (raw ?? '')
  return (
    <div>
      <div className="text-[10px] text-gray-500 uppercase">{label}</div>
      <div className={clsx('text-xs', same ? 'text-gray-400' : 'text-amber-200')}>
        canonical: <span className="text-gray-200">{canonical ?? '—'}</span>
      </div>
      <div className={clsx('text-xs', same ? 'text-gray-400' : 'text-amber-200')}>
        raw: <span className="text-gray-200">{raw ?? '—'}</span>
      </div>
    </div>
  )
}

// ─── Алиасы (inline-секция в OverviewTab) ────────────────────────────

function AliasesContent({ game }: { game: CatalogGameDetail }) {
  const groups = useMemo(() => {
    const by = new Map<string, typeof game.aliases>()
    for (const a of game.aliases) {
      const key = a.language ?? '—'
      const list = by.get(key) ?? []
      list.push(a)
      by.set(key, list)
    }
    // Сортировка ключей: ru, en, ..., '—' в конце.
    const keys = [...by.keys()].sort((x, y) => {
      if (x === '—') return 1
      if (y === '—') return -1
      if (x === 'ru') return -1
      if (y === 'ru') return 1
      return x.localeCompare(y)
    })
    return keys.map(k => ({ lang: k, items: by.get(k)! }))
  }, [game.aliases])

  return (
    <div className="space-y-3">
      {groups.map(g => (
        <div key={g.lang} className="space-y-1">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">
            {g.lang === '—' ? 'без языка' : g.lang} · {g.items.length}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {g.items.map(a => (
              <span key={a.id}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-gray-800 text-gray-200">
                {a.alias}
                <span className={clsx('text-[10px] px-1 rounded',
                  a.source === 'manual' ? 'bg-violet-900/60 text-violet-200' :
                  a.source === 'wikidata' ? 'bg-blue-900/60 text-blue-200' :
                  a.source === 'bgg' ? 'bg-orange-900/60 text-orange-200' :
                  a.source === 'dicefest' ? 'bg-purple-900/60 text-purple-200' :
                  a.source === 'auto-match' ? 'bg-gray-700 text-gray-300' :
                  'bg-gray-700 text-gray-300',
                )}>{a.source}</span>
                {a.verified && <Check size={10} className="text-emerald-400" />}
              </span>
            ))}
          </div>
        </div>
      ))}

      <div className="border-t border-gray-800 pt-3">
        <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-2">
          Управление (CRUD)
        </div>
        <AliasEditor gameId={game.id} aliases={game.aliases} />
      </div>
    </div>
  )
}

// ─── Tab: Offers ─────────────────────────────────────────────────────

function OffersTab({ gameId }: { gameId: number }) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['catalog', 'game-offers', gameId],
    queryFn: () => fetchGameOffers(gameId),
  })

  const reassess = useMutation({
    mutationFn: () => reassessAll({}),
    onSuccess: (r) => {
      toast.success(`Reassess: ${r.scanned} проверено, ${r.promoted_to_auto} → auto, ${r.score_improved} улучшено`)
      queryClient.invalidateQueries({ queryKey: ['catalog', 'game-offers', gameId] })
    },
    onError: (e) => toast.error(`Reassess failed: ${e}`),
  })

  if (isLoading) return <Loader2 size={14} className="animate-spin text-gray-500" />
  if (!data) return null

  // Группируем по магазину для удобства scanning'а.
  const byStore = new Map<string, CatalogOffer[]>()
  for (const o of data.items) {
    const list = byStore.get(o.store_slug) ?? []
    list.push(o)
    byStore.set(o.store_slug, list)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">
          Всего: {data.total} · группировка по магазину
        </div>
        <button
          onClick={() => reassess.mutate()}
          disabled={reassess.isPending}
          className="text-xs flex items-center gap-1 px-2 py-1 rounded bg-violet-900/40 text-violet-200 hover:bg-violet-900/60 disabled:opacity-50"
          title="Пересчитать матчинг для всех unmatched offers (глобально)"
        >
          <RefreshCw size={11} className={reassess.isPending ? 'animate-spin' : ''} />
          Reassess unmatched
        </button>
      </div>

      {data.total === 0 && <Empty msg="Нет offers, привязанных к этой игре." />}

      {[...byStore.entries()].map(([store, items]) => (
        <div key={store} className="border border-gray-800 rounded">
          <div className="px-3 py-1.5 bg-gray-950 border-b border-gray-800 flex items-center justify-between">
            <span className="text-xs font-mono text-gray-300">{store}</span>
            <span className="text-[10px] text-gray-500">{items.length} offer{items.length === 1 ? '' : 's'}</span>
          </div>
          <table className="w-full text-xs">
            <thead className="bg-gray-950/40">
              <tr className="text-left text-gray-500">
                <th className="px-2 py-1">title_raw</th>
                <th className="px-2 py-1">sku</th>
                <th className="px-2 py-1">цена</th>
                <th className="px-2 py-1">в наличии</th>
                <th className="px-2 py-1">match</th>
                <th className="px-2 py-1">last_seen</th>
                <th className="px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {items.map(o => (
                <tr key={o.id} className="border-t border-gray-800">
                  <td className="px-2 py-1 text-gray-200">{o.title_raw}</td>
                  <td className="px-2 py-1 font-mono text-gray-400">{o.sku ?? '—'}</td>
                  <td className="px-2 py-1">
                    {o.last_price != null ? (
                      <span>
                        <span className="text-gray-200">{fmtKop(o.last_price)}</span>
                        {o.original_price != null && o.original_price > o.last_price && (
                          <span className="ml-1 line-through text-gray-500">{fmtKop(o.original_price)}</span>
                        )}
                      </span>
                    ) : <span className="text-gray-500">—</span>}
                  </td>
                  <td className="px-2 py-1">
                    {o.in_stock === true && <span className="text-emerald-400">✓</span>}
                    {o.in_stock === false && <span className="text-red-400">✗</span>}
                    {o.in_stock === null && <span className="text-gray-500">?</span>}
                    {o.is_preorder && <span className="ml-1 text-[10px] px-1 rounded bg-blue-900/40 text-blue-200">preord</span>}
                  </td>
                  <td className="px-2 py-1">
                    <span className={clsx('text-[10px] px-1 rounded',
                      o.match_status === 'auto' ? 'bg-emerald-900/40 text-emerald-200' :
                      o.match_status === 'manual' ? 'bg-violet-900/40 text-violet-200' :
                      o.match_status === 'rejected' ? 'bg-red-900/40 text-red-200' :
                      'bg-gray-800 text-gray-400',
                    )}>{o.match_status}{o.match_score != null ? ` ${o.match_score.toFixed(2)}` : ''}</span>
                  </td>
                  <td className="px-2 py-1 text-gray-500 font-mono">
                    {o.last_seen_at.slice(0, 10)}
                  </td>
                  <td className="px-2 py-1">
                    <a href={o.url} target="_blank" rel="noreferrer"
                       className="text-gray-400 hover:text-gray-200">
                      <ExternalLink size={11} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

// ─── Дети (inline-секция в OverviewTab, lazy-mount) ──────────────────

function ChildrenContent({ gameId }: { gameId: number }) {
  // Монтируется только при раскрытии секции — useQuery стартует здесь же
  // и не нагружает первый рендер drawer.
  const { data, isLoading } = useQuery({
    queryKey: ['catalog', 'game-children', gameId],
    queryFn: () => fetchGameChildren(gameId),
  })
  if (isLoading) return <Loader2 size={14} className="animate-spin text-gray-500" />
  if (!data) return null
  if (data.total === 0) {
    return (
      <Empty msg="Нет дочерних записей. Допы/промо привязываются через поле parent_game_id (см. таб «Обзор»)." />
    )
  }
  return (
    <div className="space-y-2">
      <div className="text-xs text-gray-500">Всего: {data.total} (parent_game_id = {gameId})</div>
      <div className="space-y-1">
        {data.items.map((c: CatalogGameChild) => (
          <div key={c.id} className="flex items-center gap-3 px-2 py-1.5 border border-gray-800 rounded hover:bg-gray-950">
            {c.cover_url ? (
              <img src={c.cover_url} alt="" className="w-10 h-10 object-contain rounded bg-gray-950 flex-shrink-0" />
            ) : (
              <div className="w-10 h-10 rounded bg-gray-950 flex-shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <div className="text-xs text-gray-200 truncate">{c.title}</div>
              <div className="text-[10px] text-gray-500 font-mono">
                #{c.id} · {c.slug}{c.year ? ` · ${c.year}` : ''}
              </div>
            </div>
            <KindBadge kind={c.kind} />
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Tab: Аудит ──────────────────────────────────────────────────────

function AuditTab({ game }: { game: CatalogGameDetail }) {
  const { data, isLoading } = useQuery({
    queryKey: ['catalog', 'game-audit', game.id],
    queryFn: () => fetchPromotionLogForGame(game.id, 30),
  })
  return (
    <div className="space-y-3">
      <Section title="Метаданные">
        <div className="space-y-1 text-xs">
          <Field label="created_at" value={game.created_at.slice(0, 19).replace('T', ' ')} mono />
          <Field label="updated_at" value={game.updated_at.slice(0, 19).replace('T', ' ')} mono />
          <Field label="source" value={game.source} mono />
          <Field label="status" value={game.status} mono />
        </div>
      </Section>

      <Section title="Журнал промоушенов (import_promotion_log)">
        {isLoading && <Loader2 size={14} className="animate-spin text-gray-500" />}
        {data && data.total === 0 && (
          <Empty msg="Нет записей промоушена для этой игры." />
        )}
        {data && data.total > 0 && (
          <div className="space-y-1">
            {data.items.map((e: PromotionLogEntry) => (
              <div key={e.id} className="flex items-center gap-2 text-xs px-2 py-1 border border-gray-800 rounded">
                <span className="text-[10px] text-gray-500 font-mono w-32 flex-shrink-0">
                  {e.performed_at.slice(0, 19).replace('T', ' ')}
                </span>
                <span className="text-[10px] px-1 rounded bg-purple-900/40 text-purple-200 font-mono flex-shrink-0">
                  {e.provider}
                </span>
                <span className={clsx('text-[10px] px-1 rounded font-mono flex-shrink-0',
                  e.action === 'create' ? 'bg-emerald-900/40 text-emerald-200' :
                  e.action === 'link' ? 'bg-blue-900/40 text-blue-200' :
                  e.action === 'revert' ? 'bg-amber-900/40 text-amber-200' :
                  e.action === 'reject' ? 'bg-red-900/40 text-red-200' :
                  'bg-gray-800 text-gray-400',
                )}>{e.action}</span>
                <span className="text-gray-500 font-mono text-[10px]">raw#{e.raw_id}</span>
                {e.performed_by && <span className="text-gray-500 text-[10px]">{e.performed_by}</span>}
                {e.reverted_at && <span className="text-amber-300 text-[10px]">reverted</span>}
                {e.notes && <span className="text-gray-400 text-[10px] truncate flex-1">{e.notes}</span>}
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  )
}

// ─── Tab: Raw JSON ───────────────────────────────────────────────────

function RawTab({ game }: { game: CatalogGameDetail }) {
  const json = JSON.stringify(game, null, 2)
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">Raw ответ /games/{game.id}</div>
        <button
          onClick={() => { void navigator.clipboard.writeText(json); toast.success('JSON скопирован') }}
          className="text-xs flex items-center gap-1 px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-200"
        >
          <Copy size={11} /> Скопировать
        </button>
      </div>
      <pre className="text-[11px] font-mono leading-snug bg-gray-950 border border-gray-800 rounded p-3 overflow-x-auto">
        {json}
      </pre>
    </div>
  )
}

// ─── Inline-edit field ───────────────────────────────────────────────

type FieldType = 'text' | 'number' | 'bool' | 'select' | 'kopecks'

function InlineEditField({
  game, field, type, label, hint, options,
}: {
  game: CatalogGameDetail
  field: keyof CatalogGameDetail
  type: FieldType
  label?: string
  hint?: string
  options?: string[]
}) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const raw = game[field]
  const display = type === 'kopecks'
    ? fmtKop(raw as number | null)
    : type === 'bool'
      ? (raw === true ? 'true' : raw === false ? 'false' : '—')
      : raw == null || raw === '' ? '' : String(raw)

  const [val, setVal] = useState(display)

  const patch = useMutation({
    mutationFn: (payload: GamePatchPayload) => patchGame(game.id, payload),
    onSuccess: () => {
      toast.success(`${field} обновлено`)
      queryClient.invalidateQueries({ queryKey: ['catalog', 'game-detail', game.id] })
      queryClient.invalidateQueries({ queryKey: ['catalog', 'games'] })
      setEditing(false)
    },
    onError: (e) => toast.error(`Ошибка: ${e}`),
  })

  function save() {
    let parsed: unknown = val
    if (type === 'number') parsed = val === '' ? null : Number(val)
    if (type === 'kopecks') parsed = val === '' ? null : Math.round(parseFloat(val) * 100)
    if (type === 'bool') parsed = val === 'true'
    if (type === 'text' && val === '') parsed = null
    patch.mutate({ [field]: parsed } as GamePatchPayload)
  }

  const labelText = label ?? field
  return (
    <div className="flex items-center gap-2">
      <span className="text-gray-500 w-32 flex-shrink-0 truncate" title={hint}>{labelText}</span>
      {editing ? (
        <div className="flex items-center gap-1 flex-1">
          {type === 'select' && options ? (
            <select value={val} onChange={(e) => setVal(e.target.value)}
                    className="bg-gray-950 border border-gray-700 rounded px-1 py-0.5 text-xs text-gray-200">
              {options.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : type === 'bool' ? (
            <select value={val} onChange={(e) => setVal(e.target.value)}
                    className="bg-gray-950 border border-gray-700 rounded px-1 py-0.5 text-xs text-gray-200">
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          ) : type === 'kopecks' ? (
            <input value={val} onChange={(e) => setVal(e.target.value)}
                   placeholder="₽ (1990 = 1990 руб)"
                   className="bg-gray-950 border border-gray-700 rounded px-1 py-0.5 text-xs text-gray-200 flex-1" />
          ) : (
            <input
              type={type === 'number' ? 'number' : 'text'}
              value={val}
              onChange={(e) => setVal(e.target.value)}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') save()
                if (e.key === 'Escape') { setEditing(false); setVal(display) }
              }}
              className="bg-gray-950 border border-gray-700 rounded px-1 py-0.5 text-xs text-gray-200 flex-1"
            />
          )}
          <button onClick={save} disabled={patch.isPending}
                  className="text-xs px-1.5 py-0.5 rounded bg-emerald-800 text-emerald-100 hover:bg-emerald-700 disabled:opacity-50">
            {patch.isPending ? <Loader2 size={10} className="animate-spin" /> : 'OK'}
          </button>
          <button onClick={() => { setEditing(false); setVal(display) }}
                  className="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 hover:bg-gray-700">
            ✕
          </button>
        </div>
      ) : (
        <button onClick={() => { setVal(display); setEditing(true) }}
                className="flex-1 text-left text-gray-200 hover:bg-gray-800/40 rounded px-1 py-0.5 cursor-pointer group">
          {display === '' ? <span className="text-gray-600">—</span> : display}
          <Pencil size={9} className="inline-block ml-1 opacity-0 group-hover:opacity-50" />
        </button>
      )}
    </div>
  )
}

// ─── Helpers и вспомогательные UI ────────────────────────────────────

function CopySqlButton({ game }: { game: CatalogGameDetail }) {
  const onClick = () => {
    // Генерируем UPDATE для часто правимых полей. Не трогаем JSONB
    // (meta) и timestamps — оператор обычно правит их через PATCH.
    const set = (col: string, v: unknown) => {
      if (v === null || v === undefined) return `${col} = NULL`
      if (typeof v === 'string') return `${col} = ${quote(v)}`
      if (typeof v === 'boolean') return `${col} = ${v}`
      return `${col} = ${v}`
    }
    const quote = (s: string) => `'${s.replace(/'/g, "''")}'`
    const lines = [
      set('title', game.title),
      set('slug', game.slug),
      set('kind', game.kind),
      set('parent_game_id', game.parent_game_id),
      set('year', game.year),
      set('ru_publisher', game.ru_publisher),
      set('ru_release_year', game.ru_release_year),
      set('is_localized_ru', game.is_localized_ru),
      set('preorder_price', game.preorder_price),
      set('bgg_id', game.bgg_id),
      set('tesera_id', game.tesera_id),
      set('dicefest_id', game.dicefest_id),
      set('nastolio_id', game.nastolio_id),
    ]
    const sql = `UPDATE games SET\n  ${lines.join(',\n  ')}\nWHERE id = ${game.id};`
    void navigator.clipboard.writeText(sql)
    toast.success('SQL UPDATE скопирован в буфер')
  }
  return (
    <button onClick={onClick} title="Скопировать как UPDATE SQL (для psql)"
            className="p-1 text-gray-400 hover:text-amber-300 hover:bg-amber-950/40 rounded">
      <Copy size={14} />
    </button>
  )
}

function KindBadge({ kind }: { kind: CatalogGameKind }) {
  const colors: Record<CatalogGameKind, string> = {
    base: 'bg-gray-800 text-gray-300',
    expansion: 'bg-blue-900/40 text-blue-200',
    promo: 'bg-pink-900/40 text-pink-200',
    accessory: 'bg-amber-900/40 text-amber-200',
  }
  return (
    <span className={clsx('px-1.5 py-0.5 rounded text-[10px] font-mono', colors[kind] ?? colors.base)}>
      {kind}
    </span>
  )
}

function Section({
  title, children, defaultOpen = true,
}: {
  title: string
  // Render-prop форма (`(open) => ReactNode`) — для тяжёлых секций,
  // которые делают useQuery: пока секция закрыта, дочерний компонент
  // не смонтирован и запрос не идёт. Простая ReactNode подходит для
  // лёгкого статичного контента.
  children: React.ReactNode | ((open: boolean) => React.ReactNode)
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="space-y-2">
      <button onClick={() => setOpen(o => !o)}
              className="flex items-center gap-1 text-xs text-gray-500 uppercase tracking-wide hover:text-gray-300">
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {title}
      </button>
      {open && <div>{typeof children === 'function' ? children(open) : children}</div>}
    </div>
  )
}

function Field({
  label, value, mono = false, link,
}: {
  label: string
  value: string
  mono?: boolean
  link?: string
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-gray-500 w-32 flex-shrink-0">{label}</span>
      {value === '' || value == null ? (
        <span className="text-gray-600">—</span>
      ) : link ? (
        <a href={link} target="_blank" rel="noreferrer"
           className={clsx('inline-flex items-center gap-1 hover:underline',
             mono ? 'text-gray-300 font-mono' : 'text-gray-200')}>
          {value} <ExternalLink size={9} />
        </a>
      ) : (
        <span className={mono ? 'text-gray-300 font-mono break-all' : 'text-gray-200 break-words'}>
          {value}
        </span>
      )}
    </div>
  )
}

function Link({ href, label, color }: { href: string; label: string; color: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer"
       className={`flex items-center gap-1 px-2 py-1 rounded ${color} hover:brightness-125`}>
      <ExternalLink size={11} /> {label}
    </a>
  )
}

function Empty({ msg = 'Нет данных.' }: { msg?: string }) {
  return <div className="text-xs text-gray-500 italic">{msg}</div>
}

function fmtArr(arr: string[] | null | undefined): string {
  return arr && arr.length ? arr.join(', ') : ''
}

function fmtKop(kop: number | null | undefined): string {
  if (kop == null) return ''
  return `${(kop / 100).toLocaleString('ru-RU')} ₽`
}
