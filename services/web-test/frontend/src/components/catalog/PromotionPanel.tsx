/**
 * PromotionPanel — UI ручного промоушена staging-данных в canonical БД.
 *
 * Двухстадийная схема (см. /promotion/dicefest в catalog):
 *   raw (dicefest_raw_games) → match → apply → games + game_aliases + satellite
 *                                                   ↓
 *                                            import_promotion_log → revert
 *
 * Вкладки:
 *   - "Очередь" — фильтр по status (new/promoted/skipped/rejected), список raw,
 *     drawer с превью + кандидатами + действиями.
 *   - "Журнал"  — последние действия с кнопкой «Отменить».
 *
 * provider передаётся пропом — компонент generic под будущие источники
 * (BGA, dicebreaker), сейчас всегда 'dicefest'.
 */
import { useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CheckCircle2, AlertTriangle, RotateCcw, X, Plus, Loader2, Bot } from 'lucide-react'
import clsx from 'clsx'
import {
  fetchPromotionQueue, fetchPromotionCandidates,
  applyPromotion, revertPromotion, fetchPromotionLog,
  batchAutoLinkPromotion,
  type DicefestRawGame, type ExternalLink, type PromotionCandidate,
  type PromotionLogEntry, type BatchLinkResult, type BatchLinkRequest,
} from '../../lib/catalog'

// Цены везде в проекте хранятся в копейках. Форматируем в рубли с разделителем.
function formatRub(kopecks: number): string {
  const rub = Math.round(kopecks / 100)
  return rub.toLocaleString('ru-RU') + ' ₽'
}

const LINK_BADGE: Record<ExternalLink['kind'], string> = {
  bgg:      'bg-orange-900/50 text-orange-300 border border-orange-900/40',
  tesera:   'bg-blue-900/50 text-blue-300 border border-blue-900/40',
  nastolio: 'bg-emerald-900/50 text-emerald-300 border border-emerald-900/40',
  shop:     'bg-violet-900/50 text-violet-300 border border-violet-900/40',
  other:    'bg-gray-800 text-gray-300 border border-gray-700',
}

const LINK_LABEL: Record<ExternalLink['kind'], string> = {
  bgg: 'BGG', tesera: 'Tesera', nastolio: 'Nastolio', shop: 'Магазин', other: 'Ссылка',
}

type StatusFilter = DicefestRawGame['status']
type Tab = 'queue' | 'log'

// Bucket-пороги для UI (см. план PR-3): зелёный/жёлтый/серый.
const HIGH_THRESHOLD = 0.85
const MEDIUM_THRESHOLD = 0.5
// Минимальный threshold для запроса (≥0.5 — на серый bucket лимита нет в API).
const REQUEST_THRESHOLD = 0.3

const PAGE_SIZE = 50

interface Props {
  provider?: string  // зарезервировано под future BGA/dicebreaker, сейчас не используется
}

export function PromotionPanel(_props: Props = {}) {
  const [tab, setTab] = useState<Tab>('queue')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('new')
  const [openRawId, setOpenRawId] = useState<number | null>(null)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1 border-b border-gray-800">
          {([
            { v: 'queue', l: 'Очередь' },
            { v: 'log',   l: 'Журнал' },
          ] as { v: Tab; l: string }[]).map(t => (
            <button
              key={t.v}
              type="button"
              onClick={() => setTab(t.v)}
              className={clsx(
                'px-3 py-2 text-sm transition-colors border-b-2 -mb-px',
                tab === t.v
                  ? 'text-violet-300 border-violet-500'
                  : 'text-gray-400 border-transparent hover:text-gray-200',
              )}
            >
              {t.l}
            </button>
          ))}
        </div>
      </div>

      {tab === 'queue' && (
        <PromotionQueue
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          onOpenRaw={setOpenRawId}
        />
      )}
      {tab === 'log' && <PromotionLogList />}

      {openRawId !== null && (
        <PromotionDrawer
          rawId={openRawId}
          onClose={() => setOpenRawId(null)}
        />
      )}
    </div>
  )
}

// ─── Queue ────────────────────────────────────────────────────────────────────

function PromotionQueue({
  statusFilter, setStatusFilter, onOpenRaw,
}: {
  statusFilter: StatusFilter
  setStatusFilter: (s: StatusFilter) => void
  onOpenRaw: (id: number) => void
}) {
  const [autoLinkOpen, setAutoLinkOpen] = useState(false)
  const queue = useInfiniteQuery({
    queryKey: ['catalog', 'promotion-queue', statusFilter],
    queryFn: ({ pageParam }) => fetchPromotionQueue(statusFilter, PAGE_SIZE, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((s, p) => s + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const items = queue.data?.pages.flatMap(p => p.items) ?? []
  const total = queue.data?.pages[0]?.total ?? 0

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-500">Статус:</label>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value as StatusFilter)}
          className="px-2 py-1 text-sm bg-gray-900 border border-gray-700 rounded text-gray-100"
        >
          <option value="new">new</option>
          <option value="promoted">promoted</option>
          <option value="skipped">skipped</option>
          <option value="rejected">rejected</option>
        </select>
        <span className="text-xs text-gray-500">
          {queue.isLoading ? 'загрузка...' : `${items.length} из ${total}`}
        </span>
        <div className="flex-1" />
        {statusFilter === 'new' && (
          <button
            type="button"
            onClick={() => setAutoLinkOpen(true)}
            className="px-3 py-1 text-xs bg-violet-700 hover:bg-violet-600 text-white rounded flex items-center gap-1"
          >
            <Bot size={12} /> Auto-link
          </button>
        )}
      </div>

      {autoLinkOpen && <AutoLinkModal onClose={() => setAutoLinkOpen(false)} />}

      <div className="border border-gray-800 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2">id</th>
              <th className="px-3 py-2">slug</th>
              <th className="px-3 py-2">title_ru</th>
              <th className="px-3 py-2">title_en</th>
              <th className="px-3 py-2">Издатель в РФ</th>
              <th className="px-3 py-2">цена ₽</th>
              <th className="px-3 py-2">links</th>
              <th className="px-3 py-2">status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {items.map(r => (
              <tr
                key={r.id}
                className="hover:bg-gray-900 cursor-pointer"
                onClick={() => onOpenRaw(r.id)}
              >
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{r.id}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-400 truncate max-w-[160px]">
                  {r.slug}
                </td>
                <td className="px-3 py-2 text-gray-100">{r.title_ru ?? '—'}</td>
                <td className="px-3 py-2 text-gray-300 text-xs">{r.title_en ?? '—'}</td>
                <td className="px-3 py-2 text-gray-300">{r.publisher ?? '—'}</td>
                <td className="px-3 py-2 text-gray-300 text-xs font-mono">
                  {r.preorder_price != null ? formatRub(r.preorder_price) : '—'}
                </td>
                <td className="px-3 py-2 text-xs">
                  {r.external_links.length > 0
                    ? r.external_links.map(l => l.kind).join(',')
                    : '—'}
                </td>
                <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
              </tr>
            ))}
            {!queue.isLoading && items.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-gray-500">
                Нет записей со статусом «{statusFilter}»
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {queue.hasNextPage && (
        <button
          type="button"
          onClick={() => queue.fetchNextPage()}
          disabled={queue.isFetchingNextPage}
          className="w-full px-3 py-2 text-sm bg-gray-900 hover:bg-gray-800 border border-gray-800 rounded text-gray-300 disabled:opacity-50"
        >
          {queue.isFetchingNextPage ? 'загрузка…' : `Показать ещё (осталось ${total - items.length})`}
        </button>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: StatusFilter }) {
  const m: Record<StatusFilter, string> = {
    new: 'bg-violet-900/50 text-violet-300',
    promoted: 'bg-emerald-900/50 text-emerald-300',
    skipped: 'bg-gray-800 text-gray-400',
    rejected: 'bg-red-900/50 text-red-300',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-mono uppercase ${m[status]}`}>
      {status}
    </span>
  )
}

// ─── Drawer (превью + кандидаты) ──────────────────────────────────────────────

function PromotionDrawer({ rawId, onClose }: { rawId: number; onClose: () => void }) {
  const queryClient = useQueryClient()
  // threshold ниже дефолтного 0.5 — показываем больше кандидатов с предупреждениями.
  const candidates = useQuery({
    queryKey: ['catalog', 'promotion-candidates', rawId],
    queryFn: () => fetchPromotionCandidates(rawId, REQUEST_THRESHOLD, 10),
  })

  const apply = useMutation({
    mutationFn: (payload: { action: 'link' | 'create' | 'skip' | 'reject'; target_game_id?: number }) =>
      applyPromotion(rawId, payload),
    onSuccess: (res) => {
      const verb = res.status === 'promoted' ? 'связано'
        : res.status === 'skipped' ? 'пропущено'
        : 'отклонено'
      toast.success(`raw #${rawId} ${verb} (log #${res.log_id})`)
      queryClient.invalidateQueries({ queryKey: ['catalog', 'promotion-queue'] })
      queryClient.invalidateQueries({ queryKey: ['catalog', 'promotion-log'] })
      onClose()
    },
    onError: (e: Error) => toast.error(`Не удалось: ${e.message}`),
  })

  if (candidates.isLoading) {
    return (
      <Modal onClose={onClose}>
        <div className="p-6 text-sm text-gray-400">
          <Loader2 size={14} className="animate-spin inline mr-2" /> Загрузка…
        </div>
      </Modal>
    )
  }
  if (candidates.isError || !candidates.data) {
    return (
      <Modal onClose={onClose}>
        <div className="p-4 text-sm text-red-400">
          Не удалось загрузить: {String(candidates.error)}
        </div>
      </Modal>
    )
  }

  const { raw, candidates: cands } = candidates.data

  // Разбиваем на bucket'ы.
  const high = cands.filter(c => c.score >= HIGH_THRESHOLD)
  const mid  = cands.filter(c => c.score >= MEDIUM_THRESHOLD && c.score < HIGH_THRESHOLD)
  const low  = cands.filter(c => c.score < MEDIUM_THRESHOLD)

  return (
    <Modal onClose={onClose}>
      <div className="flex items-start justify-between p-4 border-b border-gray-800 gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-gray-100 truncate">
            {raw.title_ru ?? raw.slug}
          </div>
          {raw.title_en && (
            <div className="text-xs text-gray-400 italic mt-0.5 truncate">{raw.title_en}</div>
          )}
          <div className="text-xs text-gray-500 font-mono mt-1 flex items-center gap-2 flex-wrap">
            <span>id={raw.id}</span>
            <a href={raw.page_url} target="_blank" rel="noreferrer"
               className="text-violet-300 hover:underline">{raw.slug}</a>
            {raw.publisher && <span>· Издатель в РФ: <b>{raw.publisher}</b></span>}
            {raw.release_status && <span>· {raw.release_status}</span>}
            {raw.preorder_price != null && (
              <span>· <b>{formatRub(raw.preorder_price)}</b></span>
            )}
          </div>
        </div>
        <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {raw.cover_url && (
          <img src={raw.cover_url} alt={raw.title_ru ?? raw.slug}
               className="max-h-48 rounded border border-gray-800" />
        )}

        {raw.external_links.length > 0 && (
          <div>
            <div className="text-xs text-gray-500 mb-1">Внешние ссылки</div>
            <div className="flex flex-wrap gap-1.5">
              {raw.external_links.map((link, i) => (
                <a
                  key={i}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className={`text-[11px] px-2 py-1 rounded font-mono hover:underline ${LINK_BADGE[link.kind]}`}
                  title={link.label}
                >
                  {LINK_LABEL[link.kind]}
                  {link.external_id && ` #${link.external_id}`}
                </a>
              ))}
            </div>
          </div>
        )}

        {raw.description && (
          <div>
            <div className="text-xs text-gray-500 mb-1">Описание</div>
            <div className="text-sm text-gray-300 whitespace-pre-wrap max-h-32 overflow-y-auto">
              {raw.description}
            </div>
          </div>
        )}

        {/* Buckets */}
        {high.length > 0 && (
          <CandidateBucket
            title={`Высокая похожесть (≥${HIGH_THRESHOLD}) — рекомендуется`}
            color="emerald"
            items={high}
            onLink={(gid) => apply.mutate({ action: 'link', target_game_id: gid })}
            disabled={apply.isPending}
          />
        )}
        {mid.length > 0 && (
          <CandidateBucket
            title={`Средняя похожесть (${MEDIUM_THRESHOLD}–${HIGH_THRESHOLD}) — проверьте перед привязкой`}
            color="amber"
            items={mid}
            onLink={(gid) => apply.mutate({ action: 'link', target_game_id: gid })}
            disabled={apply.isPending}
          />
        )}
        {low.length > 0 && (
          <CandidateBucket
            title={`Низкая (<${MEDIUM_THRESHOLD}) — обычно не подходит`}
            color="gray"
            items={low}
            onLink={(gid) => apply.mutate({ action: 'link', target_game_id: gid })}
            disabled={apply.isPending}
            collapsed
          />
        )}
        {cands.length === 0 && (
          <div className="text-sm text-gray-500 italic px-2 py-3 border border-gray-800 rounded">
            Кандидатов с подходящим score не найдено. Возможно, в основной БД нет
            русских локализаций для этой игры — обогатите через Wikidata-импорт и
            попробуйте снова.
          </div>
        )}

        {raw.status === 'new' && (
          <div className="border-t border-gray-800 pt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                if (window.confirm(`Создать новую canonical Game для «${raw.title_ru ?? raw.slug}»?`)) {
                  apply.mutate({ action: 'create' })
                }
              }}
              disabled={apply.isPending}
              className="px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white rounded flex items-center gap-1"
            >
              <Plus size={12} /> Создать новую игру
            </button>
            <button
              type="button"
              onClick={() => apply.mutate({ action: 'skip' })}
              disabled={apply.isPending}
              className="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-gray-200 rounded"
            >
              Пропустить
            </button>
            <button
              type="button"
              onClick={() => {
                if (window.confirm('Отклонить эту запись (это не игра)?')) {
                  apply.mutate({ action: 'reject' })
                }
              }}
              disabled={apply.isPending}
              className="px-3 py-1.5 text-xs bg-red-900/50 hover:bg-red-900 disabled:opacity-40 text-red-200 rounded"
            >
              Отклонить
            </button>
          </div>
        )}

        {raw.status !== 'new' && (
          <div className="text-xs text-gray-500 italic border-t border-gray-800 pt-3">
            Статус: <StatusBadge status={raw.status} />. Действия недоступны (используйте
            «Журнал» для отката).
          </div>
        )}
      </div>
    </Modal>
  )
}

function CandidateBucket({
  title, color, items, onLink, disabled, collapsed,
}: {
  title: string
  color: 'emerald' | 'amber' | 'gray'
  items: PromotionCandidate[]
  onLink: (gameId: number) => void
  disabled: boolean
  collapsed?: boolean
}) {
  const [open, setOpen] = useState(!collapsed)
  const colorMap = {
    emerald: 'bg-emerald-900/30 border-emerald-900/50',
    amber:   'bg-amber-900/20 border-amber-900/40',
    gray:    'bg-gray-900 border-gray-800',
  }
  return (
    <div className={`rounded border p-2 ${colorMap[color]}`}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full text-left text-xs font-medium text-gray-300 mb-2"
      >
        {open ? '▼' : '▶'} {title} ({items.length})
      </button>
      {open && (
        <div className="space-y-1.5">
          {items.map(c => (
            <CandidateRow
              key={c.game_id}
              c={c}
              onLink={onLink}
              disabled={disabled}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function CandidateRow({
  c, onLink, disabled,
}: {
  c: PromotionCandidate
  onLink: (gameId: number) => void
  disabled: boolean
}) {
  // year_diff УБРАН в PR-4 (release_year на dicefest относится к РФ-релизу,
  // не к оригиналу — давал ложно-тревожные warning'и). Поле в типах
  // оставлено на будущее, рендерим только если backend его пришлёт.
  const yearWarn = c.year_diff != null && c.year_diff >= 3
  return (
    <div className="bg-gray-950 rounded p-2 flex items-center gap-2">
      <span className="font-mono text-xs text-gray-500 flex-shrink-0">
        {c.score.toFixed(2)}
      </span>
      <span className="font-mono text-[10px] text-gray-600 flex-shrink-0">
        #{c.game_id}
      </span>
      <span className="text-sm text-gray-100 truncate flex-1">{c.title}</span>
      {c.year && <span className="text-xs text-gray-500 flex-shrink-0">({c.year})</span>}
      {yearWarn && (
        <span title={`candidate=${c.year}`}
              className="flex items-center gap-1 text-[10px] text-amber-300 px-1.5 py-0.5 bg-amber-900/40 rounded">
          <AlertTriangle size={10} /> Δ{c.year_diff}лет
        </span>
      )}
      {c.has_satellite_for_provider && (
        <span title="у этой игры уже есть привязка к dicefest"
              className="flex items-center gap-1 text-[10px] text-red-300 px-1.5 py-0.5 bg-red-900/40 rounded">
          <AlertTriangle size={10} /> уже привязан
        </span>
      )}
      <button
        type="button"
        onClick={() => onLink(c.game_id)}
        disabled={disabled}
        className="px-2 py-1 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white rounded flex-shrink-0"
      >
        Привязать
      </button>
    </div>
  )
}

// ─── Log ──────────────────────────────────────────────────────────────────────

function PromotionLogList() {
  const queryClient = useQueryClient()
  const log = useInfiniteQuery({
    queryKey: ['catalog', 'promotion-log'],
    queryFn: ({ pageParam }) => fetchPromotionLog(50, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((s, p) => s + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const items = log.data?.pages.flatMap(p => p.items) ?? []

  const revert = useMutation({
    mutationFn: (logId: number) => revertPromotion(logId),
    onSuccess: (res) => {
      toast.success(`Отменено: raw#${res.raw_id} → ${res.status_after_revert}`)
      queryClient.invalidateQueries({ queryKey: ['catalog', 'promotion-log'] })
      queryClient.invalidateQueries({ queryKey: ['catalog', 'promotion-queue'] })
    },
    onError: (e: Error) => toast.error(`Не удалось: ${e.message}`),
  })

  return (
    <div className="space-y-2">
      <div className="border border-gray-800 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2">id</th>
              <th className="px-3 py-2">action</th>
              <th className="px-3 py-2">raw_id</th>
              <th className="px-3 py-2">game_id</th>
              <th className="px-3 py-2">when</th>
              <th className="px-3 py-2">by</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {items.map(it => (
              <LogRow key={it.id} it={it} onRevert={revert.mutate} disabled={revert.isPending} />
            ))}
            {items.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-gray-500">
                Журнал пуст
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {log.hasNextPage && (
        <button
          type="button"
          onClick={() => log.fetchNextPage()}
          className="w-full px-3 py-2 text-sm bg-gray-900 hover:bg-gray-800 border border-gray-800 rounded text-gray-300"
        >
          Показать ещё
        </button>
      )}
    </div>
  )
}

function LogRow({
  it, onRevert, disabled,
}: {
  it: PromotionLogEntry
  onRevert: (id: number) => void
  disabled: boolean
}) {
  const reverted = it.reverted_at != null
  const isRevertEntry = it.action === 'revert'
  const canRevert = !reverted && !isRevertEntry
  return (
    <tr className={clsx('hover:bg-gray-900', reverted && 'opacity-50')}>
      <td className="px-3 py-2 font-mono text-xs text-gray-500">{it.id}</td>
      <td className="px-3 py-2">
        <span className="font-mono text-xs uppercase text-gray-300 flex items-center gap-1">
          {it.action === 'revert' ? <RotateCcw size={10} /> :
           it.action === 'link'   ? <CheckCircle2 size={10} className="text-emerald-400" /> :
           it.action === 'create' ? <Plus size={10} className="text-violet-400" /> :
           null}
          {it.action}
        </span>
      </td>
      <td className="px-3 py-2 font-mono text-xs text-gray-400">{it.raw_id}</td>
      <td className="px-3 py-2 font-mono text-xs text-gray-400">
        {it.game_id != null ? `#${it.game_id}` : '—'}
      </td>
      <td className="px-3 py-2 text-xs text-gray-500">
        {new Date(it.performed_at).toLocaleString('ru-RU')}
      </td>
      <td className="px-3 py-2 text-xs text-gray-400">{it.performed_by ?? '—'}</td>
      <td className="px-3 py-2">
        {reverted && (
          <span className="text-[10px] text-gray-500 italic">
            reverted {new Date(it.reverted_at!).toLocaleString('ru-RU')}
          </span>
        )}
        {canRevert && (
          <button
            type="button"
            onClick={() => {
              if (window.confirm(`Отменить действие «${it.action}» на raw#${it.raw_id}?`)) {
                onRevert(it.id)
              }
            }}
            disabled={disabled}
            className="px-2 py-1 text-xs bg-amber-900/40 hover:bg-amber-900 disabled:opacity-40 text-amber-200 rounded flex items-center gap-1"
          >
            <RotateCcw size={11} /> Отменить
          </button>
        )}
      </td>
    </tr>
  )
}

// ─── Modal helper ─────────────────────────────────────────────────────────────

function Modal({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-gray-900 border border-gray-800 rounded-lg shadow-2xl w-[min(720px,100%)] max-h-[90vh] flex flex-col overflow-hidden">
        {children}
      </div>
    </div>
  )
}

// ─── Auto-link модалка (PR-5) ────────────────────────────────────────────────

function AutoLinkModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [threshold, setThreshold] = useState(0.95)
  const [maxItems, setMaxItems] = useState(100)
  const [skipWithSatellite, setSkipWithSatellite] = useState(true)
  // Result последнего запроса. Если dry_run=true — это «preview» (linked=0, would_link=N).
  // Если dry_run=false — это «applied» (linked=N).
  const [result, setResult] = useState<BatchLinkResult | null>(null)

  const run = useMutation({
    mutationFn: (body: BatchLinkRequest) => batchAutoLinkPromotion(body),
    onSuccess: (res) => {
      setResult(res)
      if (!res.dry_run) {
        toast.success(`Привязано: ${res.linked}, пропущено: ${res.skipped.length}`)
        queryClient.invalidateQueries({ queryKey: ['catalog', 'promotion-queue'] })
        queryClient.invalidateQueries({ queryKey: ['catalog', 'promotion-log'] })
      }
    },
    onError: (e: Error) => toast.error(`Не удалось: ${e.message}`),
  })

  const inPreview = result?.dry_run === true
  const inApplied = result !== null && result.dry_run === false

  return (
    <Modal onClose={onClose}>
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-100 flex items-center gap-2">
          <Bot size={14} /> Auto-link по высоким score
        </h2>
        <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200 rounded">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {/* Форма параметров */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">
              Минимальный score (≥)
            </label>
            <input
              type="number"
              min={0.5} max={1} step={0.01}
              value={threshold}
              onChange={e => setThreshold(parseFloat(e.target.value) || 0.95)}
              disabled={run.isPending}
              className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100 font-mono"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">
              Max items
            </label>
            <input
              type="number"
              min={1} max={1000}
              value={maxItems}
              onChange={e => setMaxItems(parseInt(e.target.value, 10) || 100)}
              disabled={run.isPending}
              className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100 font-mono"
            />
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-200 cursor-pointer">
          <input
            type="checkbox"
            checked={skipWithSatellite}
            onChange={e => setSkipWithSatellite(e.target.checked)}
            disabled={run.isPending}
            className="accent-violet-500"
          />
          Пропускать игры с уже привязанной dicefest-страницей
        </label>

        {/* Кнопки действий */}
        <div className="flex gap-2 pt-2">
          {!inPreview && !inApplied && (
            <button
              type="button"
              onClick={() => run.mutate({
                threshold, max_items: maxItems, dry_run: true,
                skip_with_satellite: skipWithSatellite,
              })}
              disabled={run.isPending}
              className="flex-1 px-3 py-1.5 text-sm bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white rounded flex items-center justify-center gap-1"
            >
              {run.isPending
                ? <><Loader2 size={12} className="animate-spin" /> Запускаю dry-run…</>
                : <>👁 Preview (dry-run)</>}
            </button>
          )}
          {inPreview && result && (
            <>
              <button
                type="button"
                onClick={() => {
                  if (window.confirm(`Привязать ${result.would_link} raw-записей?`)) {
                    run.mutate({
                      threshold, max_items: maxItems, dry_run: false,
                      skip_with_satellite: skipWithSatellite,
                    })
                  }
                }}
                disabled={run.isPending || result.would_link === 0}
                className="flex-1 px-3 py-1.5 text-sm bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 text-white rounded flex items-center justify-center gap-1"
              >
                {run.isPending
                  ? <><Loader2 size={12} className="animate-spin" /> Применяю…</>
                  : <>✓ Применить ({result.would_link})</>}
              </button>
              <button
                type="button"
                onClick={() => setResult(null)}
                className="px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 text-gray-200 rounded"
              >
                Сбросить
              </button>
            </>
          )}
          {inApplied && (
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-3 py-1.5 text-sm bg-violet-700 hover:bg-violet-600 text-white rounded"
            >
              Готово, закрыть
            </button>
          )}
        </div>

        {/* Result preview */}
        {result && (
          <div className="border-t border-gray-800 pt-3 space-y-2">
            <div className={clsx(
              'text-xs',
              result.dry_run ? 'text-amber-300' : 'text-emerald-300',
            )}>
              {result.dry_run
                ? `Будет привязано: ${result.would_link} из ${result.scanned}.`
                : `Привязано: ${result.linked} из ${result.scanned}.`}
              {' Пропущено: '}{result.skipped.length}.
            </div>

            {result.items.length > 0 && (
              <div>
                <div className="text-xs text-gray-500 mb-1">
                  {result.dry_run ? 'Кандидаты' : 'Привязанные'} (топ-{result.items.length})
                </div>
                <div className="bg-gray-950 rounded p-2 space-y-1 max-h-48 overflow-y-auto">
                  {result.items.map((it, i) => (
                    <div key={i} className="text-xs flex items-center gap-2">
                      <span className="font-mono text-gray-500 flex-shrink-0">
                        {it.score.toFixed(2)}
                      </span>
                      <span className="text-gray-300 truncate flex-1" title={it.raw_title ?? it.slug}>
                        {it.raw_title ?? it.slug}
                      </span>
                      <span className="text-gray-500 flex-shrink-0">→</span>
                      <span className="font-mono text-[10px] text-gray-600 flex-shrink-0">
                        #{it.game_id}
                      </span>
                      <span className="text-gray-200 truncate flex-shrink-0 max-w-[40%]">
                        {it.game_title}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {result.skipped.length > 0 && (
              <div>
                <div className="text-xs text-gray-500 mb-1">
                  Пропущено ({result.skipped.length})
                </div>
                <div className="bg-gray-950 rounded p-2 space-y-1 max-h-32 overflow-y-auto">
                  {result.skipped.slice(0, 50).map((s, i) => (
                    <div key={i} className="text-xs flex items-center gap-2">
                      <span className="font-mono text-[10px] text-gray-600 flex-shrink-0">
                        #{s.raw_id}
                      </span>
                      <span className="text-gray-400 truncate flex-1">{s.slug}</span>
                      <span className="text-amber-300 flex-shrink-0">{s.reason}</span>
                      {s.top_score != null && (
                        <span className="font-mono text-gray-500 flex-shrink-0">
                          {s.top_score.toFixed(2)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
