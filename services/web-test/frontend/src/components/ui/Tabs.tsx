/**
 * Tabs — горизонтальные underline-tabs.
 *
 * Активная — `text-zinc-100` + 2px indigo-400 underline. Inactive —
 * `text-zinc-500 hover:text-zinc-200`. Badge-каунтер справа inline.
 *
 * Compound API (Radix):
 *   <Tabs value={tab} onValueChange={setTab}>
 *     <Tabs.List>
 *       <Tabs.Trigger value="queue">Очередь <span>142</span></Tabs.Trigger>
 *       <Tabs.Trigger value="log">Журнал</Tabs.Trigger>
 *     </Tabs.List>
 *     <Tabs.Content value="queue">...</Tabs.Content>
 *     <Tabs.Content value="log">...</Tabs.Content>
 *   </Tabs>
 *
 * При overflow по ширине — scroll-clamp с тенью (не wrap).
 */
import { type ReactNode } from 'react'
import * as RadixTabs from '@radix-ui/react-tabs'
import clsx from 'clsx'

export interface TabsProps {
  value: string
  onValueChange: (value: string) => void
  defaultValue?: string
  children: ReactNode
  className?: string
}

function TabsRoot({ value, onValueChange, defaultValue, children, className }: TabsProps) {
  return (
    <RadixTabs.Root
      value={value}
      onValueChange={onValueChange}
      defaultValue={defaultValue}
      className={className}
    >
      {children}
    </RadixTabs.Root>
  )
}

function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <RadixTabs.List
      className={clsx(
        'flex items-stretch border-b border-zinc-800',
        // Overflow-scroll с fade на правой границе для long tab-strips
        'overflow-x-auto scrollbar-none',
        className,
      )}
    >
      {children}
    </RadixTabs.List>
  )
}

interface TabsTriggerProps {
  value: string
  children: ReactNode
  className?: string
  disabled?: boolean
}

function TabsTrigger({ value, children, className, disabled }: TabsTriggerProps) {
  return (
    <RadixTabs.Trigger
      value={value}
      disabled={disabled}
      className={clsx(
        'group relative flex items-center gap-1.5 px-3 h-9',
        'text-xs whitespace-nowrap',
        'border-b-2 border-transparent -mb-px',
        'transition-colors',
        // Inactive
        'text-zinc-500 hover:text-zinc-200',
        // Active
        'data-[state=active]:text-zinc-100',
        'data-[state=active]:border-indigo-400',
        // Disabled
        'disabled:opacity-40 disabled:cursor-not-allowed',
        // Focus
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-zinc-950',
        className,
      )}
    >
      {children}
    </RadixTabs.Trigger>
  )
}

function TabsContent({
  value, children, className,
}: { value: string; children: ReactNode; className?: string }) {
  return (
    <RadixTabs.Content
      value={value}
      className={clsx('focus:outline-none', className)}
    >
      {children}
    </RadixTabs.Content>
  )
}

export const Tabs = Object.assign(TabsRoot, {
  List: TabsList,
  Trigger: TabsTrigger,
  Content: TabsContent,
})
