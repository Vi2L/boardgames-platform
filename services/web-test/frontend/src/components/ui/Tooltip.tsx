/**
 * Tooltip — Radix Tooltip wrapper.
 *
 * Delay 300ms (см. components.md). Без стрелки. Использует TooltipProvider
 * на уровне приложения (см. AppShell или main.tsx). Если провайдера нет —
 * показывается с дефолтным delayDuration=700ms внутри RadixTooltip.Root.
 *
 * Применение:
 *   <Tooltip content={<>Связать · <KBD>L</KBD></>}>
 *     <IconButton icon={Link} aria-label="Связать" />
 *   </Tooltip>
 *
 * Внутри Tooltip — любые children (IconButton, span, …). Дочерний элемент
 * получает trigger-обвязку (focus, hover, keyboard) автоматически.
 */
import { type ReactNode } from 'react'
import * as RadixTooltip from '@radix-ui/react-tooltip'
import clsx from 'clsx'

export interface TooltipProps {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  /** delay в ms. Default 300. */
  delay?: number
  /** Класс на Content (тулу с текстом). */
  className?: string
  /** Принудительный disable (например, если иконка disabled). */
  disabled?: boolean
}

export function Tooltip({
  content, children, side = 'top', align = 'center', delay = 300,
  className, disabled = false,
}: TooltipProps) {
  if (disabled) return <>{children}</>
  return (
    <RadixTooltip.Root delayDuration={delay}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          align={align}
          sideOffset={6}
          className={clsx(
            'z-50 px-2 py-1 rounded',
            'bg-zinc-800 border border-zinc-700 text-zinc-100',
            'text-xxs leading-snug',
            'shadow-lg shadow-black/40',
            'data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=delayed-open]:zoom-in-95',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
            className,
          )}
        >
          {content}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
}

/**
 * Провайдер для всех Tooltip в приложении. Должен быть смонтирован на уровне
 * App (один раз). См. AppShell.tsx.
 */
export const TooltipProvider = RadixTooltip.Provider
