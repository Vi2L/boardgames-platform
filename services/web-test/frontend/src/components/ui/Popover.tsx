/**
 * Popover — Radix Popover wrapper.
 *
 * Симметричен с `Tooltip` (`./Tooltip.tsx`), но click-based вместо hover:
 * сохраняет состояние «открыт» пока не кликнут вне или не нажат Esc.
 * Идеален для контента, который нужно прочитать (2-6 предложений) или
 * скопировать.
 *
 * В отличие от Tooltip, Popover работает per-instance — глобальный
 * Provider не нужен (Radix Popover не требует его).
 *
 * Применение:
 *   <Popover content={<div>Объяснение…</div>}>
 *     <IconButton icon={Info} aria-label="Подробнее" />
 *   </Popover>
 *
 * Поверх Popover-а строится `<HelpBox>` (`../shared/HelpBox.tsx`) — основной
 * пользовательский путь для контекстных help-боксов (см. WT-F13). Если
 * нужен другой UX (например, custom-trigger), Popover можно использовать
 * напрямую — но сначала проверь, не подойдёт ли HelpBox с уже типизированным
 * словарём топиков.
 */
import { type ReactNode } from 'react'
import * as RadixPopover from '@radix-ui/react-popover'
import clsx from 'clsx'

export interface PopoverProps {
  /** Содержимое popover-окна. */
  content: ReactNode
  /** Trigger-элемент (оборачивается в `asChild`). */
  children: ReactNode
  /** Controlled-режим: текущее состояние открытия. */
  open?: boolean
  /** Controlled-режим: колбэк при изменении состояния. */
  onOpenChange?: (open: boolean) => void
  /** С какой стороны trigger'а появляется popover. По умолчанию 'bottom'. */
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** Выравнивание по trigger'у. По умолчанию 'center'. */
  align?: 'start' | 'center' | 'end'
  /** Зазор между trigger'ом и контентом, px. По умолчанию 8. */
  sideOffset?: number
  /** Класс на Content (стиль контейнера). */
  className?: string
}

export function Popover({
  content,
  children,
  open,
  onOpenChange,
  side = 'bottom',
  align = 'center',
  sideOffset = 8,
  className,
}: PopoverProps) {
  return (
    <RadixPopover.Root open={open} onOpenChange={onOpenChange}>
      <RadixPopover.Trigger asChild>{children}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          side={side}
          align={align}
          sideOffset={sideOffset}
          collisionPadding={8}
          className={clsx(
            'z-50 px-3 py-2.5 rounded-lg max-w-sm',
            'bg-zinc-900 border border-zinc-800 text-zinc-200',
            'shadow-xl shadow-black/60',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
            'data-[side=top]:slide-in-from-bottom-1',
            'data-[side=bottom]:slide-in-from-top-1',
            'data-[side=left]:slide-in-from-right-1',
            'data-[side=right]:slide-in-from-left-1',
            'focus-visible:outline-none',
            className,
          )}
        >
          {content}
          {/* Arrow цветом фона контейнера, не border — иначе стрелка выглядит «прозрачной». */}
          <RadixPopover.Arrow className="fill-zinc-900" width={10} height={5} />
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  )
}
