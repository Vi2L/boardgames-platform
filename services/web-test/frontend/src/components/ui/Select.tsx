/**
 * Select — single-select dropdown поверх Radix Select.
 *
 * Высоты как у Input: sm=28, md=32. Trigger открывает popup. Хорошо подходит
 * для коротких enum'ов (store, action, kind). Для длинных списков — Combobox.
 *
 * API:
 *   <Select
 *     value={store}
 *     onValueChange={setStore}
 *     options={[{value:'hg', label:'HobbyGames'}, ...]}
 *     placeholder="Все магазины"
 *   />
 */
import { useMemo } from 'react'
import * as RadixSelect from '@radix-ui/react-select'
import { Check, ChevronDown, ChevronUp } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'

export interface SelectOption {
  value: string
  label: string
  icon?: LucideIcon
  /** Если задан — рендерится мелким серым после label (например, count). */
  hint?: string
  disabled?: boolean
}

export interface SelectProps {
  value: string | undefined
  onValueChange: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  size?: 'sm' | 'md'
  disabled?: boolean
  className?: string
  /** Опциональный лейбл слева (например для prefixed combos). */
  prefix?: string
  /** aria-label если placeholder — не текст. */
  'aria-label'?: string
}

export function Select({
  value, onValueChange, options, placeholder = 'Выбрать…',
  size = 'sm', disabled, className, prefix, 'aria-label': ariaLabel,
}: SelectProps) {
  const height = size === 'md' ? 'h-8' : 'h-7'
  const selected = useMemo(
    () => options.find(o => o.value === value),
    [options, value],
  )

  return (
    <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <RadixSelect.Trigger
        aria-label={ariaLabel ?? placeholder}
        className={clsx(
          'inline-flex items-center justify-between gap-2 w-full',
          height, 'px-2.5',
          'bg-zinc-900 border border-zinc-800 rounded',
          'text-xs text-zinc-200',
          'hover:border-zinc-700',
          'focus:outline-none focus:border-indigo-500 focus-visible:ring-2 focus-visible:ring-indigo-500/40',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          className,
        )}
      >
        {prefix && <span className="text-zinc-500 mr-1">{prefix}</span>}
        <span className={clsx('flex items-center gap-1.5 truncate', !selected && 'text-zinc-600')}>
          {selected?.icon && <selected.icon size={12} className="text-zinc-400" />}
          <RadixSelect.Value placeholder={placeholder} />
        </span>
        <RadixSelect.Icon className="text-zinc-500 ml-auto">
          <ChevronDown size={12} />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>

      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={4}
          className={clsx(
            'z-50 min-w-[var(--radix-select-trigger-width)] max-h-72',
            'bg-zinc-900 border border-zinc-800 rounded',
            'shadow-xl shadow-black/40',
            'overflow-hidden',
          )}
        >
          <RadixSelect.ScrollUpButton className="flex items-center justify-center h-6 text-zinc-500 bg-zinc-900">
            <ChevronUp size={12} />
          </RadixSelect.ScrollUpButton>
          <RadixSelect.Viewport className="p-1">
            {options.map(opt => (
              <RadixSelect.Item
                key={opt.value}
                value={opt.value}
                disabled={opt.disabled}
                className={clsx(
                  'relative flex items-center gap-2 px-2 h-7 rounded text-xs',
                  'text-zinc-200',
                  'data-[highlighted]:bg-zinc-800 data-[highlighted]:outline-none',
                  'data-[disabled]:opacity-40 data-[disabled]:cursor-not-allowed',
                  'select-none cursor-pointer',
                )}
              >
                {opt.icon && <opt.icon size={12} className="text-zinc-400 flex-shrink-0" />}
                <RadixSelect.ItemText>{opt.label}</RadixSelect.ItemText>
                {opt.hint && (
                  <span className="ml-auto text-xxs font-mono text-zinc-500 tabular-nums">{opt.hint}</span>
                )}
                <RadixSelect.ItemIndicator className="ml-auto text-indigo-400">
                  <Check size={12} />
                </RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
          <RadixSelect.ScrollDownButton className="flex items-center justify-center h-6 text-zinc-500 bg-zinc-900">
            <ChevronDown size={12} />
          </RadixSelect.ScrollDownButton>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  )
}
