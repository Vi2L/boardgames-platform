/**
 * HowItWorks — expandable «пояснение» секции для admin'а.
 *
 * Дизайн: тонкая полоса с заголовком + ChevronDown/Right, при раскрытии
 * показывает prose-блок с пояснением. Использует CSS-only state через
 * `<details>` (нативный disclosure) — это даёт корректное keyboard-поведение
 * (Enter/Space toggle, screen-reader announce) без JS.
 *
 * Применение: в шапке каждой вкладки `/matching`, плюс inline-блоки внутри
 * (например, «Что такое skipped» под re-enqueue панелью).
 */
import { HelpCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import clsx from 'clsx'

interface HowItWorksProps {
  title: string
  children: ReactNode
  className?: string
  /** по умолчанию свёрнут; передать true чтобы раскрыть */
  defaultOpen?: boolean
  /** subtle "info" вариант с приглушённым фоном vs «hint» вариант с border */
  variant?: 'subtle' | 'hint'
}

export function HowItWorks({
  title,
  children,
  className,
  defaultOpen = false,
  variant = 'subtle',
}: HowItWorksProps) {
  return (
    <details
      open={defaultOpen}
      className={clsx(
        'group rounded-lg overflow-hidden',
        variant === 'subtle'
          ? 'bg-gray-900/40 border border-gray-800/60'
          : 'bg-violet-950/20 border border-violet-900/40',
        className,
      )}
    >
      <summary
        className={clsx(
          'flex items-center gap-2 px-3.5 py-2.5 cursor-pointer select-none',
          'text-[11px] uppercase tracking-wider',
          variant === 'subtle' ? 'text-gray-400 hover:text-gray-200' : 'text-violet-300 hover:text-violet-200',
          'list-none [&::-webkit-details-marker]:hidden',
        )}
      >
        <HelpCircle size={12} className="flex-shrink-0" />
        <span className="font-semibold">{title}</span>
        <span className="ml-auto text-gray-600 group-open:hidden">раскрыть</span>
        <span className="ml-auto text-gray-600 hidden group-open:inline">скрыть</span>
      </summary>
      <div className="px-3.5 pb-3.5 pt-1 text-xs leading-relaxed text-gray-300 space-y-2 border-t border-gray-800/40">
        {children}
      </div>
    </details>
  )
}

// ── TierBadge inline — для использования в HowItWorks-prose ────────────────

interface TierChipProps {
  tier: 'T0' | 'T1' | 'T2' | 'T3' | 'T4'
  label?: string
}

const TIER_CONFIG: Record<TierChipProps['tier'], { bg: string; text: string; title: string }> = {
  T0: { bg: 'bg-blue-900/30',   text: 'text-blue-300',   title: 'cache hit' },
  T1: { bg: 'bg-cyan-900/30',   text: 'text-cyan-300',   title: 'pg_trgm ≥ 0.92' },
  T2: { bg: 'bg-emerald-900/30',text: 'text-emerald-300',title: 'bge-m3 cosine ≥ 0.85' },
  T3: { bg: 'bg-violet-900/30', text: 'text-violet-300', title: 'qwen2.5 LLM-арбитр' },
  T4: { bg: 'bg-amber-900/30',  text: 'text-amber-300',  title: 'manual queue' },
}

export function TierChip({ tier, label }: TierChipProps) {
  const cfg = TIER_CONFIG[tier]
  return (
    <span
      title={cfg.title}
      className={clsx(
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px]',
        'border border-gray-700/50',
        cfg.bg, cfg.text,
      )}
    >
      <span className="font-semibold">{tier}</span>
      {label && <span className="opacity-70">{label}</span>}
    </span>
  )
}
