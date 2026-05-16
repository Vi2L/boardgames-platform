/**
 * Combobox — single-select dropdown с поиском, поверх cmdk + Popover.
 *
 * Для длинных списков (магазины, action types, batch IDs) где Select без
 * поиска становится unwieldy. Использует cmdk (уже в проекте) для fuzzy-filter
 * и Radix Popover для overlay.
 *
 * API:
 *   <Combobox
 *     value={value}
 *     onChange={setValue}
 *     options={items}
 *     searchPlaceholder="фильтр…"
 *     placeholder="Выбрать игру"
 *   />
 *
 * Вариант с custom-render элементами оставляем на потом — для UI WT-F11
 * (Search + Drawer) понадобится, добавим тогда.
 */
import { useState } from 'react'
import * as RadixPopover from '@radix-ui/react-popover'
import { Command } from 'cmdk'
import { Check, ChevronDown } from 'lucide-react'
import clsx from 'clsx'

export interface ComboboxOption {
  value: string
  label: string
  hint?: string
  disabled?: boolean
}

export interface ComboboxProps {
  value: string | undefined
  onChange: (value: string) => void
  options: ComboboxOption[]
  placeholder?: string
  searchPlaceholder?: string
  size?: 'sm' | 'md'
  className?: string
  disabled?: boolean
  emptyText?: string
}

export function Combobox({
  value, onChange, options,
  placeholder = 'Выбрать…',
  searchPlaceholder = 'фильтр…',
  size = 'sm', className, disabled, emptyText = 'нет вариантов',
}: ComboboxProps) {
  const [open, setOpen] = useState(false)
  const height = size === 'md' ? 'h-8' : 'h-7'
  const selected = options.find(o => o.value === value)

  return (
    <RadixPopover.Root open={open} onOpenChange={setOpen}>
      <RadixPopover.Trigger
        disabled={disabled}
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
        <span className={clsx('truncate', !selected && 'text-zinc-600')}>
          {selected?.label ?? placeholder}
        </span>
        <ChevronDown size={12} className="text-zinc-500 flex-shrink-0" />
      </RadixPopover.Trigger>

      <RadixPopover.Portal>
        <RadixPopover.Content
          align="start"
          sideOffset={4}
          className={clsx(
            'z-50 w-[var(--radix-popover-trigger-width)] max-h-72',
            'bg-zinc-900 border border-zinc-800 rounded',
            'shadow-xl shadow-black/40',
            'overflow-hidden flex flex-col',
          )}
        >
          <Command className="flex flex-col min-h-0">
            <div className="px-2 py-1.5 border-b border-zinc-800">
              <Command.Input
                placeholder={searchPlaceholder}
                className="w-full h-6 bg-transparent text-xs text-zinc-100 placeholder:text-zinc-600 outline-none"
              />
            </div>
            <Command.List className="overflow-y-auto p-1 flex-1">
              <Command.Empty className="px-2 py-3 text-xxs text-zinc-500 text-center">
                {emptyText}
              </Command.Empty>
              {options.map(opt => (
                <Command.Item
                  key={opt.value}
                  value={opt.value}
                  disabled={opt.disabled}
                  onSelect={() => {
                    onChange(opt.value)
                    setOpen(false)
                  }}
                  className={clsx(
                    'flex items-center gap-2 px-2 h-7 rounded text-xs cursor-pointer',
                    'text-zinc-200',
                    'data-[selected=true]:bg-zinc-800',
                    'data-[disabled=true]:opacity-40 data-[disabled=true]:cursor-not-allowed',
                  )}
                >
                  <span className="truncate flex-1">{opt.label}</span>
                  {opt.hint && (
                    <span className="text-xxs font-mono text-zinc-500 tabular-nums">{opt.hint}</span>
                  )}
                  {opt.value === value && (
                    <Check size={12} className="text-indigo-400" />
                  )}
                </Command.Item>
              ))}
            </Command.List>
          </Command>
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  )
}
