/**
 * Button — основная кнопка действия.
 *
 * 6 variants × 3 sizes. Variants определяют цвет и семантику:
 *   - primary  — главное CTA (indigo)
 *   - secondary — нейтральная (zinc-900)
 *   - ghost    — без фона (только hover)
 *   - danger / success / warn — статус-семантика, рядом со status-system
 *
 * forwardRef → focus management работает (Drawer auto-focus, и т.п.).
 * `asChild` через Radix Slot — для рендеринга как `<a>` / `<Link>` сохраняя
 * стили (типичный паттерн shadcn).
 */
import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Slot } from '@radix-ui/react-slot'
import { Loader2, type LucideIcon } from 'lucide-react'
import { cva, type VariantProps } from 'class-variance-authority'
import clsx from 'clsx'

const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-1.5 border rounded',
    'font-medium select-none whitespace-nowrap',
    'transition-colors duration-100',
    'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-zinc-950',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ],
  {
    variants: {
      variant: {
        primary:   'bg-indigo-500 hover:bg-indigo-400 text-white border-indigo-500',
        secondary: 'bg-zinc-900 hover:bg-zinc-800 text-zinc-200 border-zinc-700',
        ghost:     'bg-transparent hover:bg-zinc-800/60 text-zinc-300 border-transparent',
        danger:    'bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border-rose-500/30',
        success:   'bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border-emerald-500/30',
        warn:      'bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border-amber-500/30',
      },
      size: {
        xs: 'h-6 px-2 text-xxs',
        sm: 'h-7 px-2.5 text-xs',
        md: 'h-8 px-3 text-sm',
      },
    },
    defaultVariants: {
      variant: 'secondary',
      size: 'sm',
    },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  icon?: LucideIcon
  iconRight?: LucideIcon
  loading?: boolean
  /** Render as child element (e.g. <a> or React Router <Link>) keeping styles. */
  asChild?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, icon: Icon, iconRight: IconRight, loading, asChild, disabled, children, ...rest }, ref) => {
    // Размеры иконок согласованы с size: xs=10px, sm=12px, md=14px — чтобы не
    // ломали height строки. Стандартный шаг lucide.
    const iconSize = size === 'md' ? 14 : size === 'xs' ? 10 : 12
    const classes = clsx(buttonVariants({ variant, size }), className)

    // asChild-режим (Radix Slot): требует РОВНО один React-элемент в children.
    // Несколько слотов (icon + text + iconRight) ломают `React.Children.only`
    // внутри Slot — этот баг ронял /search в белый экран при появлении
    // <Button asChild><Link>…</Link></Button> в UnmatchedSection. Поэтому
    // в asChild-ветке прокидываем только children как есть.
    if (asChild) {
      return (
        <Slot
          ref={ref as never}
          className={classes}
          {...rest}
        >
          {children}
        </Slot>
      )
    }

    return (
      <button
        ref={ref}
        className={classes}
        disabled={disabled || loading}
        {...rest}
      >
        {loading ? (
          <Loader2 size={iconSize} className="animate-spin" />
        ) : Icon ? (
          <Icon size={iconSize} />
        ) : null}
        {children}
        {IconRight && !loading && <IconRight size={iconSize} />}
      </button>
    )
  },
)
Button.displayName = 'Button'
