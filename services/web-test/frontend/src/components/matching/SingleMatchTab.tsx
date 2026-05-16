/**
 * SingleMatchTab — вкладка `/matching → Штучный`.
 *
 * Кейс: оператор хочет прогнать конкретный оффер через полный v2 pipeline
 * (T2+T3), не дожидаясь обычного ingest-цикла.
 *
 * UX:
 *   1. Найти оффер: либо вбить offer_id, либо искать по title-substring.
 *   2. Карточка оффера: текущий match_status, score, tier, reason.
 *   3. Кнопка «Прогнать через v2» → enqueue с priority=10.
 *   4. Progress drawer открывается справа: 4 stage'а (T0-T3), polling каждые
 *      1.5 сек на match_log + ml-status пока stage не завершится.
 *
 * Polling: только когда drawer открыт.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Search, Crosshair, Loader2, CheckCircle2, Circle, Hourglass,
  ChevronRight, X, ExternalLink, Zap,
} from 'lucide-react'
import clsx from 'clsx'

import {
  findOfferById, findOffersByTitle, runV2OnOffer,
  type OfferLookup,
} from '../../lib/matching'
import { fetchMatchLog, fetchMlStatus } from '../../lib/catalog'
import { HowItWorks, TierChip } from './HowItWorks'
import { InfoTip } from './InfoTip'

// ── Main ──────────────────────────────────────────────────────────────────

export function SingleMatchTab() {
  const [offerId, setOfferId] = useState<string>('')
  const [titleQuery, setTitleQuery] = useState<string>('')
  const [searchMode, setSearchMode] = useState<'id' | 'title'>('id')
  const [selectedOffer, setSelectedOffer] = useState<OfferLookup | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null)

  // Lookup by id
  const offerByIdQuery = useQuery({
    queryKey: ['matching', 'offer-by-id', offerId],
    queryFn: () => findOfferById(Number(offerId)),
    enabled: false,  // запускается через refetch на submit
  })

  // Lookup by title (debounced)
  const [debouncedTitle, setDebouncedTitle] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebouncedTitle(titleQuery), 400)
    return () => clearTimeout(t)
  }, [titleQuery])

  const offersByTitle = useQuery({
    queryKey: ['matching', 'offers-by-title', debouncedTitle],
    queryFn: () => findOffersByTitle(debouncedTitle, 10),
    enabled: searchMode === 'title' && debouncedTitle.length >= 2,
  })

  const handleIdSubmit = async () => {
    if (!offerId || isNaN(Number(offerId))) return
    setSelectedOffer(null)
    try {
      const { data } = await offerByIdQuery.refetch()
      if (data) setSelectedOffer(data)
    } catch (e) {
      toast.error(`Оффер #${offerId} не найден`)
    }
  }

  // Run v2 mutation
  const qc = useQueryClient()
  const runV2 = useMutation({
    mutationFn: (id: number) => runV2OnOffer(id),
    onSuccess: (data) => {
      toast.success(`Оффер #${data.offer_id} в очереди (priority=${data.priority}). Жди результат…`)
      setRunStartedAt(Date.now())
      setDrawerOpen(true)
      qc.invalidateQueries({ queryKey: ['matching', 'stats-extended'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <div className="space-y-4 relative">
      <HowItWorks title="Как работает штучный матчинг">
        <SingleExplainer />
      </HowItWorks>

      {/* Search panel */}
      <section className={clsx(
        'rounded-lg border border-gray-800/80 bg-gray-900/40 overflow-hidden',
        'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
      )}>
        <header className="px-4 py-2.5 border-b border-gray-800/60 bg-black/20">
          <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-300 flex items-center gap-2">
            <Search size={11} /> найти оффер
            <InfoTip text="Можно по offer_id (точно) или по подстроке title (fuzzy). Поиск по unmatched+manual+auto одновременно." />
          </h3>
        </header>
        <div className="p-4 space-y-3">
          <div className="flex items-center gap-2">
            <ModeToggle mode={searchMode} onChange={setSearchMode} />
            {searchMode === 'id' && (
              <div className="flex-1 flex items-center gap-2">
                <input
                  type="number"
                  value={offerId}
                  onChange={e => setOfferId(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleIdSubmit()}
                  placeholder="например: 1247"
                  className="flex-1 px-3 py-1.5 bg-gray-900 border border-gray-800 rounded text-sm text-gray-200 font-mono focus:outline-none focus:border-violet-500"
                />
                <button
                  type="button"
                  onClick={handleIdSubmit}
                  disabled={!offerId || offerByIdQuery.isFetching}
                  className="px-3 py-1.5 bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white text-xs rounded inline-flex items-center gap-1"
                >
                  {offerByIdQuery.isFetching && <Loader2 size={11} className="animate-spin" />}
                  Найти
                </button>
              </div>
            )}
            {searchMode === 'title' && (
              <input
                type="text"
                value={titleQuery}
                onChange={e => setTitleQuery(e.target.value)}
                placeholder="Каркассон, Wingspan, …"
                className="flex-1 px-3 py-1.5 bg-gray-900 border border-gray-800 rounded text-sm text-gray-200 focus:outline-none focus:border-violet-500"
                autoFocus
              />
            )}
          </div>

          {/* Title results */}
          {searchMode === 'title' && offersByTitle.data?.items && offersByTitle.data.items.length > 0 && (
            <div className="border border-gray-800/60 rounded divide-y divide-gray-800/60 max-h-64 overflow-y-auto">
              {offersByTitle.data.items.map(item => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelectedOffer(item)}
                  className={clsx(
                    'w-full text-left px-3 py-2 hover:bg-gray-800/40 transition-colors',
                    'flex items-center gap-3',
                    selectedOffer?.id === item.id && 'bg-violet-950/30',
                  )}
                >
                  <code className="font-mono text-[11px] text-gray-500 w-12 flex-shrink-0">#{item.id}</code>
                  <span className="text-[11px] text-gray-600 font-mono w-20 flex-shrink-0">{item.store_slug}</span>
                  <span className="text-xs text-gray-200 flex-1 truncate">{item.title_raw}</span>
                  <StatusBadge status={item.match_status} />
                </button>
              ))}
            </div>
          )}
          {searchMode === 'title' && debouncedTitle.length >= 2 && offersByTitle.data?.items?.length === 0 && (
            <div className="text-xs text-gray-500 text-center py-3">оффер не найден</div>
          )}
        </div>
      </section>

      {/* Selected offer card */}
      {selectedOffer && (
        <OfferCard
          offer={selectedOffer}
          onRunV2={() => runV2.mutate(selectedOffer.id)}
          running={runV2.isPending}
        />
      )}

      {/* Progress drawer */}
      <ProgressDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        offer={selectedOffer}
        runStartedAt={runStartedAt}
      />
    </div>
  )
}

// ── Mode toggle ────────────────────────────────────────────────────────────

function ModeToggle({ mode, onChange }: {
  mode: 'id' | 'title'; onChange: (m: 'id' | 'title') => void
}) {
  return (
    <div className="flex bg-gray-900 border border-gray-800 rounded overflow-hidden flex-shrink-0">
      {(['id', 'title'] as const).map(m => (
        <button
          key={m}
          type="button"
          onClick={() => onChange(m)}
          className={clsx(
            'px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider',
            mode === m
              ? 'bg-violet-700/80 text-white'
              : 'text-gray-500 hover:bg-gray-800 hover:text-gray-200',
          )}
        >
          {m === 'id' ? 'по ID' : 'по title'}
        </button>
      ))}
    </div>
  )
}

// ── Offer card ─────────────────────────────────────────────────────────────

function OfferCard({ offer, onRunV2, running }: {
  offer: OfferLookup; onRunV2: () => void; running: boolean
}) {
  return (
    <section className={clsx(
      'rounded-lg border border-gray-800/80 bg-gray-900/40 overflow-hidden',
      'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]',
    )}>
      <header className="px-4 py-2.5 border-b border-gray-800/60 bg-black/20 flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-300 flex items-center gap-2">
          <Crosshair size={11} />
          offer #{offer.id}
        </h3>
        <StatusBadge status={offer.match_status} />
      </header>
      <div className="p-4 space-y-4">
        <div className="flex items-start gap-4">
          {offer.image_url ? (
            <img src={offer.image_url} alt="" className="w-20 h-20 object-cover rounded border border-gray-800" />
          ) : (
            <div className="w-20 h-20 rounded border border-gray-800 bg-gray-900/60 flex items-center justify-center text-[10px] text-gray-600">
              no image
            </div>
          )}
          <div className="flex-1 space-y-1.5">
            <div className="text-base text-gray-100 font-medium">{offer.title_raw}</div>
            <div className="flex items-center gap-3 text-[11px] text-gray-500 font-mono">
              <span>{offer.store_slug}</span>
              <span className="text-gray-700">·</span>
              <span>external_id={offer.external_id}</span>
              {offer.last_price !== null && (
                <>
                  <span className="text-gray-700">·</span>
                  <span className="text-green-300">{(offer.last_price / 100).toFixed(0)} ₽</span>
                </>
              )}
              {offer.url && (
                <a
                  href={offer.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-0.5 text-gray-400 hover:text-violet-300"
                >
                  открыть <ExternalLink size={9} />
                </a>
              )}
            </div>
          </div>
        </div>

        {/* Current match diagnostics */}
        <div className="grid grid-cols-4 gap-3 pt-3 border-t border-gray-800/60">
          <DiagKV label="match_status" value={offer.match_status} />
          <DiagKV label="game_id" value={offer.game_id ? `#${offer.game_id}` : '—'} />
          <DiagKV label="match_tier" value={offer.match_tier !== null ? `T${offer.match_tier}` : '—'} />
          <DiagKV label="match_score" value={offer.match_score?.toFixed(3) ?? '—'} />
        </div>
        {offer.match_reason && (
          <div className="text-[10px] text-gray-500 font-mono pt-2">
            reason: <span className="text-amber-300/80">{offer.match_reason}</span>
          </div>
        )}

        {/* Action */}
        <div className="flex items-center justify-end gap-3 pt-3 border-t border-gray-800/60">
          <p className="flex-1 text-[11px] text-gray-500">
            Добавит в <code className="text-violet-300">match_queue</code> с priority=10. Воркер обработает в следующем тике (10с).
          </p>
          <button
            type="button"
            onClick={onRunV2}
            disabled={running}
            className={clsx(
              'inline-flex items-center gap-1.5 px-3 py-1.5 rounded',
              'bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white text-xs font-medium',
              'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.15)]',
            )}
          >
            {running ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
            Прогнать через v2
          </button>
        </div>
      </div>
    </section>
  )
}

function DiagKV({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-widest text-gray-500 font-mono">{label}</div>
      <div className="font-mono text-xs text-gray-200">{value}</div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { bg: string; text: string }> = {
    auto:      { bg: 'bg-green-900/40',   text: 'text-green-300' },
    manual:    { bg: 'bg-blue-900/40',    text: 'text-blue-300' },
    unmatched: { bg: 'bg-amber-900/40',   text: 'text-amber-300' },
    rejected:  { bg: 'bg-red-950/40',     text: 'text-red-300' },
  }
  const c = cfg[status] ?? { bg: 'bg-gray-800/40', text: 'text-gray-400' }
  return (
    <span className={clsx(
      'inline-flex items-center px-2 py-0.5 rounded font-mono text-[10px] uppercase tracking-wider',
      c.bg, c.text,
    )}>{status}</span>
  )
}

// ── Progress drawer ────────────────────────────────────────────────────────

interface Stage {
  tier: 'T0' | 'T1' | 'T2' | 'T3' | 'T4'
  title: string
  state: 'pending' | 'running' | 'done' | 'skipped'
  detail: string
}

function ProgressDrawer({ open, onClose, offer, runStartedAt }: {
  open: boolean
  onClose: () => void
  offer: OfferLookup | null
  runStartedAt: number | null
}) {
  // Poll ml-status to track queue progress
  const mlStatus = useQuery({
    queryKey: ['catalog', 'ml-status'],
    queryFn: fetchMlStatus,
    refetchInterval: open ? 2000 : false,
    enabled: open,
  })

  // Poll match_log for this offer to detect completion
  const log = useQuery({
    queryKey: ['matching', 'offer-log', offer?.id],
    queryFn: () => fetchMatchLog({ offer_id: offer!.id, limit: 5 }),
    refetchInterval: open ? 1500 : false,
    enabled: open && offer != null,
  })

  // Derive stages from latest match_log entry (created by worker after T2/T3)
  const stages = useMemo<Stage[]>(() => {
    const latest = log.data?.items?.find(
      l => runStartedAt && new Date(l.performed_at).getTime() >= runStartedAt,
    )
    const stages: Stage[] = [
      { tier: 'T0', title: 'cache lookup',  state: 'pending', detail: 'проверка match_decisions' },
      { tier: 'T1', title: 'pg_trgm',       state: 'pending', detail: 'триграммный поиск ≥ 0.92' },
      { tier: 'T2', title: 'bge-m3 cosine', state: 'pending', detail: 'embedding + cosine top-K' },
      { tier: 'T3', title: 'qwen LLM',      state: 'pending', detail: 'арбитр по 2-3 кандидатам' },
    ]
    if (!latest) {
      // ничего не получили — определяем текущий tier через worker progress
      // T0/T1 — если воркер ещё не взял, остаются pending. Если взял — T0/T1
      // не пишут лог при miss; пишут только winners. Без специального API мы
      // не знаем, прошёл ли уже T0+T1. Поэтому пока полагаемся на финальный лог.
      return stages
    }
    // tier > 0 means winner was T<tier>
    const winnerTier = latest.tier
    const stageIdx = ['T0', 'T1', 'T2', 'T3'].indexOf(`T${winnerTier}`)
    for (let i = 0; i < stages.length; i++) {
      if (i < stageIdx) stages[i].state = 'skipped'
      if (i === stageIdx) {
        stages[i].state = 'done'
        stages[i].detail = `${latest.action} → game_id #${latest.new_game_id} (score ${latest.score?.toFixed(2) ?? '—'})`
      }
      if (i > stageIdx) stages[i].state = 'skipped'
    }
    return stages
  }, [log.data, runStartedAt])

  const queuePending = mlStatus.data?.queue?.pending ?? 0
  const queueProcessing = mlStatus.data?.queue?.processing ?? 0
  const finished = stages.some(s => s.state === 'done')

  return (
    <div
      className={clsx(
        'fixed inset-y-0 right-0 w-[480px] max-w-[90vw] z-40',
        'bg-gray-950 border-l border-gray-800',
        'transform transition-transform duration-300',
        open ? 'translate-x-0' : 'translate-x-full',
        'shadow-2xl shadow-black/80',
      )}
    >
      <header className="flex items-center justify-between px-5 py-3 border-b border-gray-800 bg-black/40">
        <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-200 flex items-center gap-2">
          <Crosshair size={11} /> Прогон через v2
          {!finished && <Loader2 size={11} className="animate-spin text-violet-400" />}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="text-gray-500 hover:text-gray-200 p-1"
        >
          <X size={14} />
        </button>
      </header>

      <div className="p-5 space-y-4 overflow-y-auto max-h-[calc(100vh-64px)]">
        {offer && (
          <div className="text-xs text-gray-400 space-y-0.5">
            <div className="text-gray-200">{offer.title_raw}</div>
            <div className="font-mono text-[10px] text-gray-600">
              #{offer.id} · {offer.store_slug} · started {runStartedAt ? new Date(runStartedAt).toLocaleTimeString('ru-RU') : '—'}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 text-[10px] uppercase tracking-wider font-mono text-gray-500 border-t border-b border-gray-800 py-2">
          <span>queue:</span>
          <span className="text-amber-300">{queuePending} pending</span>
          <span className="text-gray-700">·</span>
          <span className="text-violet-300">{queueProcessing} processing</span>
        </div>

        <ol className="space-y-2.5">
          {stages.map((s, i) => (
            <StageRow key={s.tier} stage={s} index={i + 1} />
          ))}
        </ol>

        {finished && (
          <div className="border border-green-900/50 bg-green-950/30 rounded p-3 text-xs space-y-1.5">
            <div className="text-green-300 flex items-center gap-1.5 font-semibold">
              <CheckCircle2 size={12} /> Готово
            </div>
            <div className="text-gray-400">
              Результат записан в <code className="text-violet-300">match_log</code>.
              Если результат не устраивает — открой <strong>Журнал</strong> и сделай revert.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function StageRow({ stage, index }: { stage: Stage; index: number }) {
  const Icon = stage.state === 'done' ? CheckCircle2
    : stage.state === 'running' ? Hourglass
    : stage.state === 'skipped' ? Circle
    : Circle
  const colors = {
    done:    'text-green-400',
    running: 'text-violet-400 animate-pulse',
    skipped: 'text-gray-700',
    pending: 'text-gray-600',
  }[stage.state]

  return (
    <li className={clsx(
      'flex items-start gap-3 p-2.5 rounded border',
      stage.state === 'done' && 'bg-green-950/15 border-green-900/40',
      stage.state === 'running' && 'bg-violet-950/15 border-violet-900/40',
      (stage.state === 'pending' || stage.state === 'skipped') && 'bg-gray-900/30 border-gray-800/50',
    )}>
      <Icon size={18} className={clsx('mt-0.5 flex-shrink-0', colors)} />
      <div className="flex-1 space-y-0.5">
        <div className="flex items-center gap-2">
          <TierChip tier={stage.tier} />
          <span className="text-sm text-gray-200">{stage.title}</span>
          <span className="ml-auto text-[10px] uppercase tracking-wider font-mono text-gray-500">
            {stage.state}
          </span>
        </div>
        <div className="text-[11px] text-gray-500 font-mono pl-1">{stage.detail}</div>
      </div>
    </li>
  )
}

// ── Single explainer ───────────────────────────────────────────────────────

function SingleExplainer() {
  return (
    <>
      <p>
        Прогон одного оффера через <TierChip tier="T2" /> + <TierChip tier="T3" /> с приоритетом 10 —
        он встанет в начало очереди и обработается в ближайшем тике воркера.
      </p>
      <p>
        <strong className="text-gray-200">Когда использовать:</strong>
      </p>
      <ul className="ml-4 space-y-1 text-gray-300">
        <li>Конкретный оффер вызвал у тебя вопросы — хочешь увидеть полный «путь» решения.</li>
        <li>Только что обновил эмбеддинги конкретной игры — хочешь сразу подтянуть к ней оффер.</li>
        <li>LLM-арбитр выдал странное — хочешь повторно прогнать после обновления каталога.</li>
      </ul>
      <p className="text-gray-400">
        UI не ждёт результата inline (Ollama может отвечать 10-30 сек) — открывается drawer с polling.
        Если на странице есть открытый drawer, polling работает раз в 1.5 сек на <code className="text-violet-300">/matching/log</code>.
      </p>
    </>
  )
}
