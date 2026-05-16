/**
 * MatchingPage — admin-панель управления ML-матчингом offers → games.
 *
 * Дизайн-направление: «operator console» — плотная информационная панель в
 * стиле SRE-дашборда. Каждая вкладка решает одну задачу, без декоративных
 * деталей. Все важные элементы имеют tooltip-подсказку для оператора,
 * который видит панель впервые.
 *
 * Структура — 5 вкладок:
 *   1. Контроль — kill-switch, ML-модели, worker, warmup.
 *   2. Очередь — re-enqueue skipped с фильтрами.
 *   3. Журнал — переиспользует существующий MatchLogTab.
 *   4. Штучный — прогон одного offer через v2 с progress drawer.
 *   5. Help — полная документация для оператора.
 *
 * Header сверху — live-индикаторы (ML status + queue counts) в стиле
 * status-bar терминальных тулзов: моноширинный, dense, без лишних слов.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Cpu, ListChecks, ScrollText, Crosshair, HelpCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'

import { fetchMlStatus } from '../lib/catalog'
import { ControlTab } from '../components/matching/ControlTab'
import { QueuePanel } from '../components/matching/QueuePanel'
import { SingleMatchTab } from '../components/matching/SingleMatchTab'
import { MatchingHelpTab } from '../components/matching/MatchingHelpTab'
import { MatchLogTab } from '../components/catalog/MatchLogTab'
import { CircuitStateBadge, type CircuitState } from '../components/matching/CircuitStateBadge'

type Tab = 'control' | 'queue' | 'log' | 'single' | 'help'

const TABS: Array<{ id: Tab; label: string; icon: LucideIcon; hint: string }> = [
  { id: 'control', label: 'Контроль',         icon: Cpu,        hint: 'Kill-switch, модели Ollama, воркер, warmup' },
  { id: 'queue',   label: 'Очередь',          icon: ListChecks, hint: 'match_queue: re-enqueue skipped, breakdown' },
  { id: 'log',     label: 'Журнал',           icon: ScrollText, hint: 'match_log: история операций + revert' },
  { id: 'single',  label: 'Штучный',          icon: Crosshair,  hint: 'Прогон одного offer через v2 pipeline' },
  { id: 'help',    label: 'Help',             icon: HelpCircle, hint: 'Документация: pipeline, troubleshooting, глоссарий' },
]

type MlStatusWithCB = ReturnType<typeof fetchMlStatus> extends Promise<infer T>
  ? T & { circuit_state?: Record<string, CircuitState> }
  : never

export function MatchingPage() {
  const [tab, setTab] = useState<Tab>('control')

  return (
    <div className="space-y-4">
      <PageHeader />

      {/* Tab strip — operator console style: uppercase, mono, dense */}
      <nav
        className={clsx(
          'flex items-stretch border-b border-gray-800/80 -mx-4 md:-mx-6 px-4 md:px-6',
          'bg-gradient-to-b from-gray-900/40 to-transparent',
        )}
      >
        {TABS.map(t => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              title={t.hint}
              className={clsx(
                'group relative inline-flex items-center gap-2 px-4 py-2.5 transition-all',
                'text-[11px] uppercase tracking-wider font-medium',
                'border-b-2 -mb-px',
                active
                  ? 'border-violet-500 text-violet-200 bg-violet-950/20'
                  : 'border-transparent text-gray-500 hover:text-gray-200 hover:bg-gray-900/40',
              )}
            >
              <Icon size={12} className={active ? 'text-violet-300' : ''} />
              {t.label}
              {active && (
                <span className="absolute left-0 right-0 -bottom-px h-px bg-violet-400/40" />
              )}
            </button>
          )
        })}
      </nav>

      {/* Tab content */}
      <div>
        {tab === 'control' && <ControlTab />}
        {tab === 'queue'   && <QueuePanel />}
        {tab === 'log'     && <MatchLogTab />}
        {tab === 'single'  && <SingleMatchTab />}
        {tab === 'help'    && <MatchingHelpTab />}
      </div>
    </div>
  )
}

// ── Page header (live status strip) ────────────────────────────────────────

function PageHeader() {
  const mlStatus = useQuery({
    queryKey: ['catalog', 'ml-status'],
    queryFn: fetchMlStatus,
    refetchInterval: 5000,
  })

  const data = mlStatus.data as MlStatusWithCB | undefined
  const models = data?.models ?? {}
  const cb = data?.circuit_state ?? {}
  const q = data?.queue ?? {}

  const totalActive = (q.pending ?? 0) + (q.processing ?? 0)

  return (
    <header className={clsx(
      'rounded-lg border border-gray-800/80 bg-black/40 overflow-hidden',
      'shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]',
    )}>
      <div className="flex items-stretch divide-x divide-gray-800/60">
        {/* Title block */}
        <div className="px-5 py-3 flex-1 min-w-0">
          <div className="flex items-baseline gap-2.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-violet-400/80">
              [ ML ]
            </span>
            <h1 className="text-base font-semibold text-gray-100 tracking-wide">
              Матчинг — ML pipeline
            </h1>
          </div>
          <p className="text-[11px] text-gray-500 mt-0.5">
            Управление T0 → T3 матчингом offers → canonical games. Kill-switch, queue
            health, batch operations, journal с revert.
          </p>
        </div>

        {/* ML models status */}
        <div className="px-5 py-3 flex items-center gap-3">
          <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono">
            ollama
          </div>
          <div className="space-y-1">
            {Object.entries(models).map(([name, available]) => {
              const state = (cb[name] ?? (available ? 'closed' : 'open')) as CircuitState
              return (
                <CircuitStateBadge
                  key={name}
                  state={state}
                  compact
                  label={name.replace(':latest', '').replace(':7b-instruct', '')}
                />
              )
            })}
            {Object.keys(models).length === 0 && (
              <span className="text-[10px] text-gray-600 font-mono italic">no data</span>
            )}
          </div>
        </div>

        {/* Queue snapshot */}
        <div className="px-5 py-3 flex items-center gap-4">
          <div className="text-[9px] uppercase tracking-widest text-gray-600 font-mono">
            queue
          </div>
          <div className="flex items-baseline gap-3 font-mono text-xs">
            <Counter value={q.pending} label="pending" accent="amber" />
            <span className="text-gray-700">·</span>
            <Counter value={q.processing} label="processing" accent="violet" />
            <span className="text-gray-700">·</span>
            <Counter value={q.skipped} label="skipped" accent="gray" />
          </div>
          {totalActive > 0 && (
            <span className="relative flex items-center" title="воркер обрабатывает очередь">
              <span className="absolute inline-flex h-2 w-2 rounded-full bg-violet-400 opacity-75 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-violet-500" />
            </span>
          )}
        </div>
      </div>
    </header>
  )
}

function Counter({ value, label, accent }: {
  value: number | undefined
  label: string
  accent: 'amber' | 'violet' | 'gray'
}) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className={clsx(
        'tabular-nums',
        accent === 'amber'  && 'text-amber-300',
        accent === 'violet' && 'text-violet-300',
        accent === 'gray'   && 'text-gray-400',
      )}>{value ?? '—'}</span>
      <span className="text-[9px] uppercase tracking-wider text-gray-600">{label}</span>
    </span>
  )
}
