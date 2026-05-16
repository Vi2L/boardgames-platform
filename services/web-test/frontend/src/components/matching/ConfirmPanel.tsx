/**
 * ConfirmPanel — inline confirm-блок вместо `window.confirm`.
 *
 * Дизайн (§G handoff):
 *   - Появляется в потоке UI (не popup), сразу под кнопкой-триггером
 *   - Показывает breakdown эффекта ДО клика (filter summary + impact list)
 *   - Esc отменяет, Enter подтверждает
 *   - Цветовая дифференциация: amber (внимание) vs red (опасно)
 *   - «Не показывать confirm для ≤ N» persist в localStorage
 *
 * Использование:
 *   const [confirmOpen, setConfirmOpen] = useState(false)
 *   ...
 *   <Button onClick={() => setConfirmOpen(true)}>Re-enqueue 412</Button>
 *   <ConfirmPanel
 *     open={confirmOpen}
 *     variant="amber"
 *     title="re-enqueue all by filter"
 *     filterSummary={[{tone:'red', label:'reason · llm_unavailable'}]}
 *     impact={['все 412 → pending', '~412 LLM вызовов · ETA 1ч 8м']}
 *     onConfirm={() => { mutation.mutate(); setConfirmOpen(false) }}
 *     onCancel={() => setConfirmOpen(false)}
 *   />
 */
import { useEffect, useRef } from 'react'
import { AlertTriangle, AlertCircle } from 'lucide-react'
import clsx from 'clsx'

export type ConfirmTone = 'amber' | 'red'

export interface ConfirmPanelProps {
  open: boolean
  title: string
  /** Описание под title — что произойдёт. */
  description?: string
  /** Чипы фильтра/контекста — что именно затронет операция. */
  filterSummary?: Array<{
    tone?: 'red' | 'amber' | 'neutral'
    label: string
  }>
  /** Список «эффектов»: первый эффект первой строкой и т.д. */
  impact?: string[]
  variant?: ConfirmTone
  /** label кнопки confirm — например «re-enqueue 412» или «выключить ML». */
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
  /** Дизейблить confirm пока mutation в полёте. */
  loading?: boolean
  className?: string
}

const VARIANT_CLS: Record<ConfirmTone, { bg: string; border: string; icon: string; btn: string }> = {
  amber: {
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/40',
    icon: 'text-amber-400',
    btn: 'bg-amber-700 hover:bg-amber-600 text-white border-amber-600',
  },
  red: {
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/40',
    icon: 'text-rose-400',
    btn: 'bg-rose-700 hover:bg-rose-600 text-white border-rose-600',
  },
}

export function ConfirmPanel({
  open, title, description, filterSummary, impact,
  variant = 'amber', confirmLabel = 'Подтвердить', loading,
  onConfirm, onCancel, className,
}: ConfirmPanelProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null)

  // Esc / Enter — глобальные хоткеи пока панель открыта.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCancel()
      } else if (e.key === 'Enter' && !loading) {
        // Confirm только если фокус не в input/textarea (Enter в формах — submit).
        const t = e.target as HTMLElement
        if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') return
        e.preventDefault()
        onConfirm()
      }
    }
    document.addEventListener('keydown', onKey)
    confirmRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onConfirm, onCancel, loading])

  if (!open) return null

  const cls = VARIANT_CLS[variant]
  const Icon = variant === 'red' ? AlertCircle : AlertTriangle

  return (
    <div
      role="alert"
      className={clsx(
        'rounded border p-3 space-y-2',
        cls.bg, cls.border,
        'animate-in slide-in-from-top-1 fade-in-0 duration-150',
        className,
      )}
    >
      <div className="flex items-start gap-2">
        <Icon size={14} className={clsx('shrink-0 mt-0.5', cls.icon)} />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-zinc-100">{title}</div>
          {description && (
            <div className="mt-0.5 text-xs text-zinc-400 leading-relaxed">{description}</div>
          )}
        </div>
      </div>

      {filterSummary && filterSummary.length > 0 && (
        <div className="flex flex-wrap gap-1 pl-6">
          {filterSummary.map((f, i) => (
            <span
              key={i}
              className={clsx(
                'inline-flex items-center px-1.5 py-0.5 rounded text-xxs font-mono',
                'border',
                f.tone === 'red'
                  ? 'bg-rose-500/10 border-rose-500/30 text-rose-300'
                  : f.tone === 'amber'
                  ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                  : 'bg-zinc-800/60 border-zinc-700 text-zinc-400',
              )}
            >
              {f.label}
            </span>
          ))}
        </div>
      )}

      {impact && impact.length > 0 && (
        <ul className="pl-6 space-y-0.5 text-xxs text-zinc-400">
          {impact.map((line, i) => (
            <li key={i} className="flex items-start gap-1">
              <span className="text-zinc-600 shrink-0">·</span>
              <span>{line}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="pl-6 flex items-center gap-2 pt-1">
        <button
          ref={confirmRef}
          type="button"
          onClick={onConfirm}
          disabled={loading}
          className={clsx(
            'inline-flex items-center gap-1 px-2.5 h-7 rounded text-xs font-medium border',
            cls.btn,
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
          )}
        >
          {loading ? '…' : confirmLabel}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={loading}
          className="px-2.5 h-7 rounded text-xs text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60"
        >
          Отмена
        </button>
        <span className="text-xxs text-zinc-600 font-mono">
          Enter — подтвердить · Esc — отмена
        </span>
      </div>
    </div>
  )
}
