/**
 * HelpBox — контекстная help-подсказка с popover'ом.
 *
 * Кликабельная иконка `HelpCircle`, при клике раскрывается popover с
 * JSX-контентом из словаря `lib/help-topics.tsx`. Закрывается кликом
 * вне, Escape или повторным кликом.
 *
 * Применение:
 *   <HelpBox topic="matching.tier_t1" />                       // только иконка
 *   <HelpBox topic="matching.tier_t1" label="T1" />            // иконка + label
 *   <HelpBox topic="matching.tier_t1" side="left" />           // позиционирование
 *
 * TopicId — string literal union из ключей HELP_TOPICS, поэтому передача
 * несуществующего topic = ошибка компиляции на месте вызова.
 *
 * Палитра help-механизмов (см. `frontend/CLAUDE.md` → «Help-контент»):
 *   - InfoTip   = 1-line plain-string tooltip к метрике (CSS-only)
 *   - Tooltip   = короткий JSX-тултип к action-кнопке (Radix)
 *   - HelpBox   = объяснение понятия 2-6 предложений, click-open (этот)
 *   - HowItWorks = collapsible-блок в шапке таба для всей подсистемы
 *   - help.html = standalone long-form справочник
 *
 * Сделано по WT-F13 (devlog 2026-05-21).
 */
import { type ReactNode } from 'react'
import { HelpCircle } from 'lucide-react'
import clsx from 'clsx'
import { Popover } from '../ui/Popover'
import { HELP_TOPICS, type TopicId } from '../../lib/help-topics'

export interface HelpBoxProps {
  /** Идентификатор топика из `lib/help-topics.tsx`. */
  topic: TopicId
  /** Опциональный label рядом с иконкой (обычно короткое слово/код, например «T1»). */
  label?: string
  /** Сторона popover'а относительно trigger'а. По умолчанию 'top'. */
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** Выравнивание popover'а. По умолчанию 'center'. */
  align?: 'start' | 'center' | 'end'
  /** Класс на trigger-кнопке (для inline-выравнивания). */
  className?: string
  /** Размер иконки в px. По умолчанию 12. */
  iconSize?: number
}

export function HelpBox({
  topic,
  label,
  side = 'top',
  align = 'center',
  className,
  iconSize = 12,
}: HelpBoxProps) {
  const t = HELP_TOPICS[topic]
  return (
    <Popover
      side={side}
      align={align}
      content={<HelpBoxContent title={t.title} body={t.body} learnMore={t.learnMore} />}
    >
      <button
        type="button"
        aria-label={`Подсказка: ${t.title}`}
        title={t.title}
        className={clsx(
          'inline-flex items-center gap-1 align-middle',
          'text-zinc-500 hover:text-indigo-400 transition-colors',
          'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-indigo-500',
          'rounded cursor-help',
          className,
        )}
      >
        <HelpCircle size={iconSize} className="flex-shrink-0" />
        {label && <span className="text-xs">{label}</span>}
      </button>
    </Popover>
  )
}

// ─── Внутренний content-renderer ────────────────────────────────────────────

function HelpBoxContent({
  title,
  body,
  learnMore,
}: {
  title: string
  body: ReactNode
  learnMore?: { label: string; href: string }
}) {
  return (
    <div className="text-xs leading-relaxed text-zinc-300 space-y-2 max-w-[20rem]">
      <div className="font-semibold text-zinc-100">{title}</div>
      <div className="space-y-1.5">{body}</div>
      {learnMore && (
        <a
          href={learnMore.href}
          target={learnMore.href.startsWith('http') ? '_blank' : undefined}
          rel={learnMore.href.startsWith('http') ? 'noopener noreferrer' : undefined}
          className="inline-block text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline"
        >
          {learnMore.label} →
        </a>
      )}
    </div>
  )
}
