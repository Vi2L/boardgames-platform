/**
 * Dialog — модальный диалог. Поверх Radix.
 *
 * Использование (compound API):
 *   <Dialog open={open} onOpenChange={setOpen}>
 *     <Dialog.Content title="Подтвердить" description="...">
 *       ...body
 *       <Dialog.Actions>
 *         <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
 *         <Button variant="primary" onClick={confirm}>OK</Button>
 *       </Dialog.Actions>
 *     </Dialog.Content>
 *   </Dialog>
 *
 * Centered, до 480px ширины. Backdrop blur ВЫКЛЮЧЕН (см. components.md).
 * Используется для confirm на bulk-action — не на per-row (medlenno).
 */
import { type ReactNode } from 'react'
import * as RadixDialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import clsx from 'clsx'

import { IconButton } from './IconButton'

export interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: ReactNode
}

function DialogRoot({ open, onOpenChange, children }: DialogProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      {children}
    </RadixDialog.Root>
  )
}

interface DialogContentProps {
  title?: string
  description?: string
  children: ReactNode
  /** Ширина контента в px. default 480, min 320. */
  width?: number
  className?: string
  /** Скрыть кнопку × в правом верхнем углу. */
  hideClose?: boolean
}

function DialogContent({
  title, description, children, width = 480, className, hideClose,
}: DialogContentProps) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay
        className={clsx(
          'fixed inset-0 z-40 bg-zinc-950/70',
          'data-[state=open]:animate-in data-[state=open]:fade-in-0',
          'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
        )}
      />
      <RadixDialog.Content
        className={clsx(
          'fixed top-1/2 left-1/2 z-50 -translate-x-1/2 -translate-y-1/2',
          'bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl shadow-black/40',
          'focus:outline-none',
          'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
          'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          className,
        )}
        style={{ width: `min(${width}px, calc(100vw - 32px))` }}
      >
        {title && (
          <header className="flex items-start justify-between gap-4 px-4 py-3 border-b border-zinc-800">
            <div className="flex-1 min-w-0">
              <RadixDialog.Title className="text-sm font-semibold text-zinc-100">
                {title}
              </RadixDialog.Title>
              {description && (
                <RadixDialog.Description className="mt-1 text-xs text-zinc-400 leading-relaxed">
                  {description}
                </RadixDialog.Description>
              )}
            </div>
            {!hideClose && (
              <RadixDialog.Close asChild>
                <IconButton
                  icon={X}
                  size="sm"
                  variant="ghost"
                  aria-label="Закрыть"
                />
              </RadixDialog.Close>
            )}
          </header>
        )}
        <div className="px-4 py-3">{children}</div>
      </RadixDialog.Content>
    </RadixDialog.Portal>
  )
}

function DialogActions({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx(
      'flex items-center justify-end gap-2 px-4 py-3 -mx-4 -mb-3 mt-3',
      'border-t border-zinc-800 bg-zinc-950/40',
      className,
    )}>
      {children}
    </div>
  )
}

export const Dialog = Object.assign(DialogRoot, {
  Trigger: RadixDialog.Trigger,
  Content: DialogContent,
  Actions: DialogActions,
  Close: RadixDialog.Close,
})
