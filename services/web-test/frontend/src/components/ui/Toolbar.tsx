/**
 * Toolbar — sticky-bottom для bulk-actions.
 *
 * Появляется когда есть selection (через `visible`-prop). Visual:
 * bg-zinc-900 + 2px indigo top border (signal что это active state),
 * h-11. Sticky `bottom-0` внутри scroll-контейнера.
 *
 * Использование:
 *   <Toolbar visible={selected.size > 0}>
 *     <Checkbox indeterminate /> <span>{selected.size} выбрано</span>
 *     <Button onClick={clear}>Снять</Button>
 *     <Toolbar.Spacer />
 *     <Button variant="danger">Отклонить</Button>
 *   </Toolbar>
 */
import { type ReactNode } from 'react'
import clsx from 'clsx'

export interface ToolbarProps {
  visible: boolean
  children: ReactNode
  className?: string
}

function ToolbarRoot({ visible, children, className }: ToolbarProps) {
  if (!visible) return null
  return (
    <div
      role="toolbar"
      className={clsx(
        'sticky bottom-0 z-20',
        'flex items-center gap-3 h-11 px-4',
        'bg-zinc-900 border-t-2 border-indigo-500/60',
        'shadow-[0_-4px_12px_rgba(0,0,0,0.4)]',
        'text-xs text-zinc-300',
        // slide-up на появлении
        'animate-in slide-in-from-bottom-2 fade-in-0 duration-150',
        className,
      )}
    >
      {children}
    </div>
  )
}

function ToolbarSpacer() {
  return <div className="flex-1" />
}

export const Toolbar = Object.assign(ToolbarRoot, { Spacer: ToolbarSpacer })
