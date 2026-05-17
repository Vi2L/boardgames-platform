/**
 * GameGroupDrawer — split-view drawer для канонической группы (WT-F11).
 *
 * Спека: `pages/05-search.md` § Drawer. 4 таба:
 *   - Офферы          · cover + price range hero + sorted offers list
 *   - История цен     · sparkline 90д (min без Avito + Avito отдельно) + last 10 changes
 *   - Матчинг         · top-3 catalog candidates через fetchMatchCandidates() + actions
 *   - Raw             · JSON dump группы
 *
 * Drawer = `ui/Drawer` (Radix Dialog modal=false) — таблица за drawer'ом
 * остаётся кликабельной (split-view). Cmd+↑/↓ навигация по соседним группам,
 * Esc закрывает (Radix).
 *
 * Особенность frontend-fallback (`pages/05-search.md` § Backend B): у нас нет
 * `game_id` от backend. Таб «Матчинг» использует best-effort poll по
 * `canonicalTitle` через `fetchMatchCandidates()` — это даёт оператору
 * подсказку «вероятно эта игра» с link на /catalog для подтверждения.
 */
import { useMemo, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import {
  ExternalLink, Library, Sparkles, FileJson, ListOrdered, History,
} from 'lucide-react'
import type { ProductOut, PricePointOut } from '../../types/api'
import { getStoreBadgeColor, getStoreLabel } from '../../lib/stores'
import { isInStock, isOnSale, originalPriceRub } from '../../lib/offer'
import { fetchHistory } from '../../lib/api'
import { fetchMatchCandidates, type MatchCandidate } from '../../lib/catalog'
import type { ProductGroup } from '../../lib/searchGrouping'
import { Drawer, Tabs, Tag, Badge, Button, EmptyState } from '../ui'
import { MetricSpark } from '../matching/MetricSpark'

/**
 * Avito — особый магазин: б/у рынок, цены могут быть значительно ниже.
 * Спека «история цен — вариант A, но Avito показывать отдельно».
 * Поэтому Avito отделяется от основной серии min-price.
 */
const AVITO_SLUG = 'avito'

export interface GameGroupDrawerProps {
  /** Открытая группа. null → drawer закрыт. */
  group: ProductGroup | null
  /** Все группы текущего поиска — для Cmd+↑/↓ навигации. */
  groups: ProductGroup[]
  onClose: () => void
  onSelectGroup: (g: ProductGroup) => void
}

type TabKey = 'offers' | 'history' | 'matching' | 'raw'

export function GameGroupDrawer({
  group, groups, onClose, onSelectGroup,
}: GameGroupDrawerProps) {
  // Hooks ALWAYS called — даже когда group=null. Скипаем рендер ниже.
  const currentIdx = useMemo(() => {
    if (!group) return -1
    return groups.findIndex(g => g.canonicalTitle === group.canonicalTitle)
  }, [group, groups])

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!group) return
    // Cmd+↑/↓ → prev/next group (как в MatchingPage drawer'е).
    // По спеке `04-jobui.md`/`01-matching.md`: единый pattern split-view drawer.
    if ((e.metaKey || e.ctrlKey) && e.key === 'ArrowUp') {
      e.preventDefault()
      if (currentIdx > 0) onSelectGroup(groups[currentIdx - 1])
    } else if ((e.metaKey || e.ctrlKey) && e.key === 'ArrowDown') {
      e.preventDefault()
      if (currentIdx >= 0 && currentIdx < groups.length - 1) {
        onSelectGroup(groups[currentIdx + 1])
      }
    }
  }

  if (!group) return null

  const total = groups.length
  const positionLabel = currentIdx >= 0 ? `${currentIdx + 1} / ${total}` : ''

  return (
    <Drawer open={group !== null} onOpenChange={open => !open && onClose()}>
      <Drawer.Content width={480} onKeyDown={handleKeyDown}>
        <Drawer.Header>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 text-xxs font-mono uppercase tracking-widest text-zinc-500">
              <Library size={11} />
              каноническая группа
              {positionLabel && (
                <span className="text-zinc-400">· {positionLabel}</span>
              )}
            </div>
            <Drawer.Title className="mt-1 truncate">
              <span title={group.canonicalTitle}>{group.canonicalTitle}</span>
            </Drawer.Title>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <Drawer.Nav
              onPrev={currentIdx > 0 ? () => onSelectGroup(groups[currentIdx - 1]) : null}
              onNext={currentIdx < total - 1 ? () => onSelectGroup(groups[currentIdx + 1]) : null}
            />
            <Drawer.Close />
          </div>
        </Drawer.Header>

        <GroupDrawerBody group={group} />

        <Drawer.Footer>
          <Button
            asChild
            variant="secondary"
            size="sm"
            icon={ExternalLink}
          >
            <Link to={`/catalog?tab=games&q=${encodeURIComponent(group.canonicalTitle)}`}>
              Открыть карточку игры
            </Link>
          </Button>
          <div className="ml-auto text-xxs text-zinc-500 font-mono">
            <kbd className="px-1 rounded bg-zinc-800 border border-zinc-700">⌘</kbd>
            <kbd className="ml-0.5 px-1 rounded bg-zinc-800 border border-zinc-700">↑↓</kbd>
            <span className="ml-1.5">соседняя группа</span>
          </div>
        </Drawer.Footer>
      </Drawer.Content>
    </Drawer>
  )
}

// ── Body with tabs ─────────────────────────────────────────────────────────

function GroupDrawerBody({ group }: { group: ProductGroup }) {
  // Tabs-state локальный — каждое открытие drawer'а начинается с Офферы.
  // Если нужен URL-state (?tab=history) — можно перейти позже.
  const [tab, setTab] = useState<TabKey>('offers')
  return (
    <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
      <Tabs.List className="px-4 shrink-0">
        <Tabs.Trigger value="offers">
          <ListOrdered size={12} />
          Офферы
          <span className="ml-1 font-mono text-xxs tabular-nums text-zinc-500">
            {group.offers.length}
          </span>
        </Tabs.Trigger>
        <Tabs.Trigger value="history">
          <History size={12} />
          История цен
        </Tabs.Trigger>
        <Tabs.Trigger value="matching">
          <Sparkles size={12} />
          Матчинг
        </Tabs.Trigger>
        <Tabs.Trigger value="raw">
          <FileJson size={12} />
          Raw
        </Tabs.Trigger>
      </Tabs.List>

      <Drawer.Body className="px-0">
        <Tabs.Content value="offers" className="px-4 py-4">
          <OffersTabContent group={group} />
        </Tabs.Content>
        <Tabs.Content value="history" className="px-4 py-4">
          <HistoryTabContent group={group} />
        </Tabs.Content>
        <Tabs.Content value="matching" className="px-4 py-4">
          <MatchingTabContent group={group} />
        </Tabs.Content>
        <Tabs.Content value="raw" className="px-4 py-4">
          <RawTabContent group={group} />
        </Tabs.Content>
      </Drawer.Body>
    </Tabs>
  )
}

// ── Tab 1: Офферы ───────────────────────────────────────────────────────────

function OffersTabContent({ group }: { group: ProductGroup }) {
  // Hero: cover из первого offer'а с image_url, цена range.
  const coverUrl = group.offers.find(o => o.image_url)?.image_url ?? null
  const prices = group.offers.filter(isInStock).map(o => o.price_rub)
  const minPrice = prices.length > 0 ? Math.min(...prices) : null
  const maxPrice = prices.length > 0 ? Math.max(...prices) : null

  // Sorted asc by price (in-stock first, потом out-of-stock).
  const sorted = useMemo(() => {
    return [...group.offers].sort((a, b) => {
      const aIn = isInStock(a) ? 0 : 1
      const bIn = isInStock(b) ? 0 : 1
      if (aIn !== bIn) return aIn - bIn
      return a.price_rub - b.price_rub
    })
  }, [group.offers])

  return (
    <div className="space-y-4">
      {/* Hero block */}
      <div className="flex gap-3">
        {coverUrl ? (
          <img
            src={coverUrl}
            alt=""
            loading="lazy"
            className="w-20 h-28 object-cover rounded border border-zinc-800 shrink-0"
          />
        ) : (
          <div className="w-20 h-28 rounded border border-zinc-800 bg-zinc-950 flex items-center justify-center text-zinc-700 text-xxs shrink-0">
            cover
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="text-xs text-zinc-500">
            {group.totalStores} магазин{plural(group.totalStores, '', 'а', 'ов')} ·{' '}
            <span className={group.inStockCount > 0 ? 'text-emerald-400' : 'text-zinc-500'}>
              {group.inStockCount}/{group.totalStores} в наличии
            </span>
          </div>
          {minPrice != null && maxPrice != null && (
            <div className="mt-1.5 font-mono tabular-nums">
              <span className="text-lg text-emerald-300">{minPrice.toLocaleString('ru-RU')}</span>
              {maxPrice > minPrice && (
                <span className="text-xs text-zinc-500"> – {maxPrice.toLocaleString('ru-RU')}</span>
              )}
              <span className="text-xs text-zinc-500 ml-1">₽</span>
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-1">
            {group.hasSale && <Tag tone="warn">sale</Tag>}
          </div>
        </div>
      </div>

      {/* Sorted offers list */}
      <div className="space-y-1">
        {sorted.map(o => (
          <OfferRow key={o.id} offer={o} isMin={o.price_rub === minPrice && isInStock(o)} />
        ))}
      </div>
    </div>
  )
}

function OfferRow({ offer, isMin }: { offer: ProductOut; isMin: boolean }) {
  const inStock = isInStock(offer)
  const onSale = isOnSale(offer)
  const origPrice = originalPriceRub(offer)

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded border border-zinc-800 bg-zinc-950/40 hover:bg-zinc-800/30">
      <span
        title={getStoreLabel(offer.store_slug)}
        className={`text-xxs font-mono px-1.5 py-0.5 rounded shrink-0 ${getStoreBadgeColor(offer.store_slug)}`}
      >
        {offer.store_slug}
      </span>
      <span className="text-xs text-zinc-300 truncate flex-1 italic" title={offer.title}>
        {offer.title}
      </span>
      {!inStock && <Tag tone="neutral">нет</Tag>}
      {onSale && <Tag tone="warn">sale</Tag>}
      <div className="font-mono tabular-nums text-xs shrink-0 text-right min-w-[88px]">
        {onSale && origPrice != null && (
          <span className="text-xxs text-zinc-600 line-through mr-1">
            {origPrice.toLocaleString('ru-RU')}
          </span>
        )}
        <span className={isMin ? 'text-emerald-300 font-semibold' : 'text-zinc-300'}>
          {offer.price_rub.toLocaleString('ru-RU')} ₽
        </span>
      </div>
      <a
        href={offer.url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-zinc-500 hover:text-indigo-300 shrink-0"
        title="Открыть в магазине"
      >
        <ExternalLink size={12} />
      </a>
    </div>
  )
}

// ── Tab 2: История цен ──────────────────────────────────────────────────────

interface PriceChange {
  ts: string
  storeSlug: string
  fromRub: number | null
  toRub: number
  deltaPct: number | null
}

interface GroupHistory {
  /** Min-цена по дням (без Avito) — основная серия sparkline. */
  mainSeries: number[]
  /** Avito-серия — отдельная (б/у рынок, не сравнимый со store-новой). */
  avitoSeries: number[]
  /** Последние 10 изменений цен среди всех offers. */
  changes: PriceChange[]
  /** Идёт ли загрузка. */
  isLoading: boolean
}

/**
 * Агрегация истории цен по группе.
 *
 * Алгоритм:
 *   1. `fetchHistory(offer.id)` параллельно для всех offers через `useQueries`.
 *   2. По каждому offer строим diff соседних точек (`prev → curr`, `delta_pct`).
 *   3. Все изменения merge'им в один массив, сортируем by ts desc, берём top-10.
 *   4. Для sparkline: по дню берём min цену среди non-Avito магазинов
 *      → mainSeries; отдельно — min цена Avito по дню → avitoSeries.
 *   5. Cutoff 90 дней (handoff §05 «sparkline 90д»).
 */
function useGroupHistory(group: ProductGroup): GroupHistory {
  const queries = useQueries({
    queries: group.offers.map(o => ({
      queryKey: ['history', o.id],
      queryFn: () => fetchHistory(o.id),
      staleTime: 60_000,
    })),
  })

  const isLoading = queries.some(q => q.isLoading)

  return useMemo(() => {
    if (isLoading) {
      return { mainSeries: [], avitoSeries: [], changes: [], isLoading: true }
    }

    const cutoff = Date.now() - 90 * 86_400_000
    const offers = group.offers

    // Все изменения по всем offers.
    const changes: PriceChange[] = []
    // Группировка точек по дням: дата (YYYY-MM-DD) → min price (без avito) / avito.
    const byDayMain = new Map<string, number>()
    const byDayAvito = new Map<string, number>()

    queries.forEach((q, idx) => {
      const points: PricePointOut[] | undefined = q.data
      if (!points || points.length === 0) return
      const offer = offers[idx]
      const isAvito = offer.store_slug === AVITO_SLUG

      // Sort asc by ts — для корректного diff prev → curr.
      const sorted = [...points].sort(
        (a, b) => new Date(a.fetched_at).getTime() - new Date(b.fetched_at).getTime(),
      )

      let prev: PricePointOut | null = null
      for (const p of sorted) {
        const ms = new Date(p.fetched_at).getTime()
        if (ms < cutoff) {
          prev = p
          continue
        }
        const day = p.fetched_at.slice(0, 10)
        const target = isAvito ? byDayAvito : byDayMain
        const cur = target.get(day)
        if (cur == null || p.price_rub < cur) {
          target.set(day, p.price_rub)
        }
        // diff vs prev (всегда фиксируем — если цена не менялась, deltaPct=0,
        // но такие changes отфильтруем ниже).
        if (prev) {
          const fromRub = prev.price_rub
          const toRub = p.price_rub
          if (fromRub !== toRub) {
            const deltaPct = fromRub > 0 ? ((toRub - fromRub) / fromRub) * 100 : null
            changes.push({
              ts: p.fetched_at,
              storeSlug: offer.store_slug,
              fromRub,
              toRub,
              deltaPct,
            })
          }
        }
        prev = p
      }
    })

    // Сортированные серии sparkline-friendly (по дням).
    const mainSeries = [...byDayMain.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([, v]) => v)
    const avitoSeries = [...byDayAvito.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([, v]) => v)

    // Top-10 свежих changes.
    const sortedChanges = changes
      .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime())
      .slice(0, 10)

    return { mainSeries, avitoSeries, changes: sortedChanges, isLoading: false }
  }, [queries, group.offers, isLoading])
}

function HistoryTabContent({ group }: { group: ProductGroup }) {
  const { mainSeries, avitoSeries, changes, isLoading } = useGroupHistory(group)

  if (isLoading) {
    return <div className="text-xs text-zinc-500 py-4 text-center">Загружаю историю…</div>
  }

  const hasAnyData = mainSeries.length > 0 || avitoSeries.length > 0

  if (!hasAnyData) {
    return (
      <EmptyState
        icon={History}
        title="Истории пока нет"
        description="История цен накапливается с каждым поиском. Запусти поиск повторно через несколько дней."
      />
    )
  }

  // min / max только по non-Avito (основная серия — рынок новых).
  const mainMin = mainSeries.length > 0 ? Math.min(...mainSeries) : null
  const mainMax = mainSeries.length > 0 ? Math.max(...mainSeries) : null
  const avitoMin = avitoSeries.length > 0 ? Math.min(...avitoSeries) : null

  return (
    <div className="space-y-4">
      {/* Main sparkline (без Avito) */}
      {mainSeries.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-1">
            <div className="text-xxs uppercase tracking-widest text-zinc-500 font-mono">
              Цена · магазины · 90д
            </div>
            <div className="text-xxs font-mono tabular-nums text-zinc-400">
              min {mainMin?.toLocaleString('ru-RU')}{' '}
              · max {mainMax?.toLocaleString('ru-RU')} ₽
            </div>
          </div>
          <MetricSpark
            values={mainSeries}
            tone="info"
            width={420}
            height={48}
            showAnnotations
          />
        </section>
      )}

      {/* Avito sparkline — отдельно, рынок б/у */}
      {avitoSeries.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-1">
            <div className="text-xxs uppercase tracking-widest text-zinc-500 font-mono inline-flex items-center gap-1.5">
              <Tag tone="info">avito</Tag>
              б/у · 90д
            </div>
            <div className="text-xxs font-mono tabular-nums text-zinc-400">
              min {avitoMin?.toLocaleString('ru-RU')} ₽
            </div>
          </div>
          <MetricSpark
            values={avitoSeries}
            tone="warn"
            width={420}
            height={48}
            showAnnotations
          />
        </section>
      )}

      {/* Last 10 changes */}
      <section>
        <div className="text-xxs uppercase tracking-widest text-zinc-500 font-mono mb-1.5">
          Последние изменения
        </div>
        {changes.length === 0 ? (
          <div className="text-xs text-zinc-500 py-2">Изменений цены не зафиксировано.</div>
        ) : (
          <div className="border border-zinc-800 rounded overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-zinc-900 text-zinc-500 text-xxs">
                <tr>
                  <th className="text-left px-2 py-1 font-normal">Дата</th>
                  <th className="text-left px-2 py-1 font-normal">Магазин</th>
                  <th className="text-right px-2 py-1 font-normal">От</th>
                  <th className="text-right px-2 py-1 font-normal">До</th>
                  <th className="text-right px-2 py-1 font-normal">Δ</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {changes.map((c, i) => (
                  <tr key={i} className="hover:bg-zinc-800/30">
                    <td className="px-2 py-1 font-mono text-zinc-400 whitespace-nowrap">
                      {new Date(c.ts).toLocaleDateString('ru-RU', {
                        day: '2-digit', month: '2-digit',
                      })}
                    </td>
                    <td className="px-2 py-1">
                      <span className={`text-xxs font-mono px-1 py-0.5 rounded ${getStoreBadgeColor(c.storeSlug)}`}>
                        {c.storeSlug}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums text-zinc-500">
                      {c.fromRub != null ? c.fromRub.toLocaleString('ru-RU') : '—'}
                    </td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums text-zinc-200">
                      {c.toRub.toLocaleString('ru-RU')}
                    </td>
                    <td className={`px-2 py-1 text-right font-mono tabular-nums ${
                      c.deltaPct == null ? 'text-zinc-500' :
                      c.deltaPct < 0 ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                      {c.deltaPct == null
                        ? '—'
                        : `${c.deltaPct > 0 ? '+' : ''}${c.deltaPct.toFixed(1)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

// ── Tab 3: Матчинг ──────────────────────────────────────────────────────────

function MatchingTabContent({ group }: { group: ProductGroup }) {
  // Best-effort: poll catalog candidates по canonical title.
  // В frontend-fallback нет game_id, поэтому это не «список linked offers»
  // (как в proper спеке backend var. A), а «вероятные кандидаты».
  // Когда backend выкатит /search/grouped с linkage — этот блок заменится
  // отображением реальных linked records + кнопкой «отвязать».
  const candidates = useQuery({
    queryKey: ['catalog', 'match-candidates', group.canonicalTitle],
    queryFn: () => fetchMatchCandidates(group.canonicalTitle, 5),
    staleTime: 60_000,
  })

  return (
    <div className="space-y-3">
      <div className="text-xs text-zinc-400 leading-relaxed">
        Backend пока не возвращает <span className="font-mono text-zinc-500">game_id</span> в результатах
        поиска. Ниже — best-effort кандидаты из каталога по названию группы.
        Подтверди привязку в <Link to="/matching" className="text-indigo-300 hover:text-indigo-200 underline">очереди матчинга</Link>.
      </div>

      <section>
        <div className="text-xxs uppercase tracking-widest text-zinc-500 font-mono mb-1.5">
          Вероятные кандидаты
        </div>
        {candidates.isLoading ? (
          <div className="text-xs text-zinc-500 py-2">Поиск кандидатов…</div>
        ) : !candidates.data || candidates.data.items.length === 0 ? (
          <EmptyState
            icon={Sparkles}
            title="Кандидатов нет"
            description="Каталог не нашёл совпадений по этому названию. Импортируй из BGG/Tesera или создай вручную."
          />
        ) : (
          <div className="space-y-1">
            {candidates.data.items.map(c => (
              <CandidateRow key={c.game_id} candidate={c} thresholds={candidates.data} />
            ))}
          </div>
        )}
      </section>

      <section className="pt-3 border-t border-zinc-800">
        <div className="text-xxs uppercase tracking-widest text-zinc-500 font-mono mb-1.5">
          Офферы группы
        </div>
        <div className="text-xxs text-zinc-500">
          {group.offers.length} оффер{plural(group.offers.length, '', 'а', 'ов')} в {group.totalStores}{' '}
          магазин{plural(group.totalStores, 'е', 'ах', 'ах')}. После привязки они появятся как «связанные» в очереди.
        </div>
      </section>
    </div>
  )
}

function CandidateRow({
  candidate, thresholds,
}: {
  candidate: MatchCandidate
  thresholds: { auto_threshold: number; candidate_threshold: number }
}) {
  const score = candidate.score
  const isAuto = score >= thresholds.auto_threshold
  const isCandidate = score >= thresholds.candidate_threshold && !isAuto

  // Status-cls: ok если auto, info если candidate, neutral если cold.
  const badgeStatus = isAuto ? 'auto' : isCandidate ? 'manual' : 'pending'

  return (
    <Link
      to={`/catalog?tab=games&id=${candidate.game_id}`}
      className="flex items-center gap-2 px-2 py-1.5 rounded border border-zinc-800 bg-zinc-950/40 hover:bg-zinc-800/30 cursor-pointer text-xs"
    >
      <Badge status={badgeStatus} size="xs" />
      <span className="text-zinc-200 truncate flex-1" title={candidate.title}>
        {candidate.title}
      </span>
      {candidate.year != null && (
        <span className="text-xxs text-zinc-500 font-mono">{candidate.year}</span>
      )}
      <span className="font-mono tabular-nums text-xs shrink-0 min-w-[40px] text-right">
        <ScoreLabel score={score} thresholds={thresholds} />
      </span>
      <span className="text-xxs text-zinc-500">via {candidate.via}</span>
    </Link>
  )
}

function ScoreLabel({
  score, thresholds,
}: {
  score: number
  thresholds: { auto_threshold: number; candidate_threshold: number }
}) {
  const cls =
    score >= thresholds.auto_threshold ? 'text-emerald-400' :
    score >= thresholds.candidate_threshold ? 'text-amber-300' :
    'text-zinc-500'
  return <span className={cls}>{score.toFixed(2)}</span>
}

// ── Tab 4: Raw ──────────────────────────────────────────────────────────────

function RawTabContent({ group }: { group: ProductGroup }) {
  // JSON pretty-print без centroidTokens (Set не сериализуется наглядно).
  const dump = useMemo(() => {
    const { centroidTokens: _ignored, ...rest } = group
    return JSON.stringify(
      { ...rest, offers: group.offers },
      null,
      2,
    )
  }, [group])

  return (
    <div className="space-y-2">
      <div className="text-xxs uppercase tracking-widest text-zinc-500 font-mono">
        ProductGroup + ProductOut[]
      </div>
      <pre className="text-xxs font-mono text-zinc-400 bg-zinc-950 border border-zinc-800 rounded p-3 overflow-auto max-h-96 leading-relaxed">
        {dump}
      </pre>
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────

function plural(n: number, one: string, few: string, many: string): string {
  const n10 = n % 10
  const n100 = n % 100
  if (n10 === 1 && n100 !== 11) return one
  if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return few
  return many
}
