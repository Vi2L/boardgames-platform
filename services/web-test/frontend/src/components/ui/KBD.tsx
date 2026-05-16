/**
 * KBD — keyboard-shortcut визуальный примитив.
 *
 * Используется в Tooltip-ах, CommandPalette, hints.
 * Mac-keyboard symbols: ⌘ (cmd), ⌥ (alt), ⌃ (ctrl), ⇧ (shift), ⏎ (enter).
 */
import type { HTMLAttributes } from 'react'
import clsx from 'clsx'

export function KBD({ className, children, ...rest }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={clsx(
        'inline-flex items-center justify-center',
        'min-w-[18px] h-[18px] px-1',
        'border border-zinc-700 rounded bg-zinc-900',
        'font-mono text-[10px] text-zinc-300',
        'shadow-[inset_0_-1px_0_0_rgba(0,0,0,0.4)]',
        className,
      )}
      {...rest}
    >
      {children}
    </kbd>
  )
}
