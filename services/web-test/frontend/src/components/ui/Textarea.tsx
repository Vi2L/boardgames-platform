/**
 * Textarea — multi-line вариант Input.
 * Не auto-resize по умолчанию (явно — это «сюрприз» для оператора).
 * font-mono для текстов с кодом / JSON / прогрессом.
 */
import { forwardRef, type TextareaHTMLAttributes } from 'react'
import clsx from 'clsx'

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  mono?: boolean
  error?: boolean
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, mono = false, error = false, rows = 4, ...rest }, ref) => {
    return (
      <textarea
        ref={ref}
        rows={rows}
        className={clsx(
          'w-full px-2.5 py-1.5 bg-zinc-900 border rounded text-xs',
          mono && 'font-mono',
          'text-zinc-100 placeholder:text-zinc-600',
          error ? 'border-rose-500/40' : 'border-zinc-800',
          'focus:outline-none focus:border-indigo-500',
          'disabled:opacity-50',
          'resize-y',
          className,
        )}
        {...rest}
      />
    )
  },
)
Textarea.displayName = 'Textarea'
