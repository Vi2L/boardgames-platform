/**
 * IconButton — квадратный вариант Button-only-icon.
 *
 * `aria-label` обязателен (без него screen reader ничего не услышит).
 * Sizes идентичны Button: xs=24, sm=28, md=32 (квадратные).
 */
import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Loader2, type LucideIcon } from 'lucide-react'
import { cva, type VariantProps } from 'class-variance-authority'
import clsx from 'clsx'

const iconButtonVariants = cva(
  [
    'inline-flex items-center justify-center border rounded',
    'transition-colors duration-100',
    'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-zinc-950',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ],
  {
    variants: {
      variant: {
        primary:   'bg-indigo-500 hover:bg-indigo-400 text-white border-indigo-500',
        secondary: 'bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border-zinc-700',
        ghost:     'bg-transparent hover:bg-zinc-800/60 text-zinc-400 hover:text-zinc-200 border-transparent',
        danger:    'bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border-rose-500/30',
        success:   'bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border-emerald-500/30',
      },
      size: {
        xs: 'h-6 w-6',
        sm: 'h-7 w-7',
        md: 'h-8 w-8',
      },
    },
    defaultVariants: {
      variant: 'ghost',
      size: 'sm',
    },
  },
)

export interface IconButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof iconButtonVariants> {
  icon: LucideIcon
  loading?: boolean
  /** Обязательно — без него a11y ломается. */
  'aria-label': string
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className, variant, size, icon: Icon, loading, disabled, ...rest }, ref) => {
    const iconSize = size === 'md' ? 16 : size === 'xs' ? 12 : 14
    return (
      <button
        ref={ref}
        type="button"
        className={clsx(iconButtonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        {...rest}
      >
        {loading ? <Loader2 size={iconSize} className="animate-spin" /> : <Icon size={iconSize} />}
      </button>
    )
  },
)
IconButton.displayName = 'IconButton'
