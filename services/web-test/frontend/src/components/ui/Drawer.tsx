/**
 * Drawer — right-side split-view, НЕ модальный.
 *
 * Особенности (ТЗ §4.1):
 *   - Не overlay'ит таблицу полностью — оставляет её кликабельной.
 *   - Esc закрывает.
 *   - Width 380-520px (0.35-0.4 экрана). Default 440.
 *   - URL state: drawer-id отражается в `?id=…` (deep-link). Compound `useDrawerId()`
 *     можно добавить позже, сейчас просто prop-based open/close.
 *   - ARIA: focus возвращается на trigger (Radix делает сам).
 *
 * Compound API:
 *   <Drawer open onOpenChange>
 *     <Drawer.Content width={440}>
 *       <Drawer.Header>
 *         <Drawer.Title>...</Drawer.Title>
 *         <Drawer.Nav prev={...} next={...} />
 *       </Drawer.Header>
 *       <Drawer.Body>...</Drawer.Body>
 *       <Drawer.Footer>...</Drawer.Footer>
 *     </Drawer.Content>
 *   </Drawer>
 *
 * Внутри — Radix Dialog с modal=false для split-view UX.
 */
import { type ReactNode, type KeyboardEvent } from 'react'
import * as RadixDialog from '@radix-ui/react-dialog'
import { X, ChevronUp, ChevronDown } from 'lucide-react'
import clsx from 'clsx'

import { IconButton } from './IconButton'

export interface DrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: ReactNode
}

function DrawerRoot({ open, onOpenChange, children }: DrawerProps) {
  // `modal={false}` — это и есть split-view: таблица за drawer'ом кликабельна,
  // фокус не trap'нут внутри. Esc-handler нужен снаружи (через Radix или ручной),
  // мы используем Radix-вариант через `onEscapeKeyDown` на Content.
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange} modal={false}>
      {children}
    </RadixDialog.Root>
  )
}

interface DrawerContentProps {
  children: ReactNode
  /** 380..520 типично. */
  width?: number
  className?: string
  /** Дополнительный обработчик клавиш (например для Cmd+↑/↓ навигации). */
  onKeyDown?: (e: KeyboardEvent<HTMLDivElement>) => void
}

function DrawerContent({ children, width = 440, className, onKeyDown }: DrawerContentProps) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Content
        className={clsx(
          'fixed top-0 right-0 bottom-0 z-40',
          'bg-zinc-900 border-l border-zinc-800',
          'flex flex-col',
          'focus:outline-none',
          'data-[state=open]:animate-in data-[state=open]:slide-in-from-right-2',
          'data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right-2',
          className,
        )}
        style={{ width }}
        onKeyDown={onKeyDown}
        // НЕ закрываем при клике снаружи — split-view, оператор может тыкать в таблицу.
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        {/* Radix требует accessible name. Если кто-то забыл DrawerTitle —
            будет console warning. Это норм. */}
        {children}
      </RadixDialog.Content>
    </RadixDialog.Portal>
  )
}

function DrawerHeader({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <header
      className={clsx(
        'flex items-start justify-between gap-3',
        'px-4 py-3 border-b border-zinc-800 shrink-0',
        className,
      )}
    >
      {children}
    </header>
  )
}

function DrawerTitle({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <RadixDialog.Title
      className={clsx('text-sm font-semibold text-zinc-100 flex-1 min-w-0', className)}
    >
      {children}
    </RadixDialog.Title>
  )
}

function DrawerDescription({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <RadixDialog.Description className={clsx('text-xs text-zinc-400 mt-1', className)}>
      {children}
    </RadixDialog.Description>
  )
}

function DrawerClose({ className }: { className?: string }) {
  return (
    <RadixDialog.Close asChild>
      <IconButton
        icon={X}
        size="sm"
        variant="ghost"
        aria-label="Закрыть drawer"
        className={className}
      />
    </RadixDialog.Close>
  )
}

interface DrawerNavProps {
  /** Хэндлер ↑ (предыдущий элемент списка). Null → disabled. */
  onPrev?: (() => void) | null
  /** Хэндлер ↓. */
  onNext?: (() => void) | null
  className?: string
}

function DrawerNav({ onPrev, onNext, className }: DrawerNavProps) {
  return (
    <div className={clsx('flex items-center gap-1', className)}>
      <IconButton
        icon={ChevronUp}
        size="xs"
        variant="ghost"
        aria-label="Предыдущая запись"
        disabled={!onPrev}
        onClick={onPrev ?? undefined}
      />
      <IconButton
        icon={ChevronDown}
        size="xs"
        variant="ghost"
        aria-label="Следующая запись"
        disabled={!onNext}
        onClick={onNext ?? undefined}
      />
    </div>
  )
}

function DrawerBody({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx('flex-1 min-h-0 overflow-y-auto px-4 py-3', className)}>
      {children}
    </div>
  )
}

function DrawerFooter({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <footer
      className={clsx(
        'flex items-center gap-2 px-4 py-3',
        'border-t border-zinc-800 bg-zinc-950/40 shrink-0',
        className,
      )}
    >
      {children}
    </footer>
  )
}

export const Drawer = Object.assign(DrawerRoot, {
  Trigger: RadixDialog.Trigger,
  Content: DrawerContent,
  Header: DrawerHeader,
  Title: DrawerTitle,
  Description: DrawerDescription,
  Close: DrawerClose,
  Nav: DrawerNav,
  Body: DrawerBody,
  Footer: DrawerFooter,
})
