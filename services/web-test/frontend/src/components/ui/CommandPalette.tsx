/**
 * CommandPalette — глобальная Cmd+K палитра действий.
 *
 * Три секции (см. components.md):
 *   1. Страницы — переход по маршрутам (статика из NAV_ITEMS).
 *   2. Действия — зарегистрированы централизованно через `useCommand({id, label, run})`.
 *      Команды добавляются из любого места приложения — например, «Reassess
 *      всё» из MatchingPage, «Toggle ml_enabled» из ControlTab.
 *   3. Recent — топ-10 последних действий (localStorage).
 *
 * Глобальный hotkey Cmd+K / Ctrl+K. Fuzzy filter через cmdk.
 *
 * Старый компонент (`src/components/shared/CommandPalette.tsx`) помечен
 * @deprecated и пока остаётся параллельно — для backward compat пока страницы
 * мигрируют на новый ui.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Command } from 'cmdk'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Search as SearchIcon, ArrowRight, Clock,
  type LucideIcon,
} from 'lucide-react'
import { create } from 'zustand'
import clsx from 'clsx'

import { KBD } from './KBD'

// ─── Command registry (Zustand) ─────────────────────────────────────────────

export interface AppCommand {
  /** Уникальный id — для dedup при mount/unmount в разных страницах. */
  id: string
  label: string
  /** Категория, отображается как heading. Default — "Действия". */
  group?: string
  icon?: LucideIcon
  /** Подсказка справа от лейбла (например shortcut или контекст). */
  hint?: string
  run: () => void
  disabled?: boolean
  /** Доступна только на определённых маршрутах (например только `/matching/*`). */
  whenRoute?: (pathname: string) => boolean
}

interface CommandRegistry {
  commands: Map<string, AppCommand>
  register: (cmd: AppCommand) => void
  unregister: (id: string) => void
}

const useRegistry = create<CommandRegistry>((set) => ({
  commands: new Map(),
  register: (cmd) => set((s) => {
    const next = new Map(s.commands)
    next.set(cmd.id, cmd)
    return { commands: next }
  }),
  unregister: (id) => set((s) => {
    if (!s.commands.has(id)) return s
    const next = new Map(s.commands)
    next.delete(id)
    return { commands: next }
  }),
}))

/**
 * Хук для регистрации команды на время mount'а компонента. Pattern:
 *
 *   useCommand({
 *     id: 'matching:reassess-all',
 *     label: 'Reassess всё',
 *     group: 'Матчинг',
 *     run: () => mutation.mutate(),
 *   })
 *
 * При unmount — auto-unregister. Deps как у useEffect — пересоздаёт команду
 * при изменении (например, run-замыкание).
 */
export function useCommand(cmd: AppCommand, deps: unknown[] = []): void {
  const register = useRegistry((s) => s.register)
  const unregister = useRegistry((s) => s.unregister)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    register(cmd)
    return () => unregister(cmd.id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}

// ─── Recents (localStorage) ─────────────────────────────────────────────────

const RECENTS_KEY = 'cmdk:recents'
const RECENTS_LIMIT = 10

function readRecents(): string[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem(RECENTS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function pushRecent(id: string): void {
  if (typeof window === 'undefined') return
  try {
    const prev = readRecents().filter((x) => x !== id)
    const next = [id, ...prev].slice(0, RECENTS_LIMIT)
    localStorage.setItem(RECENTS_KEY, JSON.stringify(next))
  } catch {
    // quota / private mode — silent
  }
}

// ─── NAV pages (статика) ────────────────────────────────────────────────────

export interface NavCommandItem {
  to: string
  label: string
  icon: LucideIcon
}

interface CommandPaletteProps {
  /** NAV_ITEMS из App.tsx — для секции «Страницы». */
  navItems?: NavCommandItem[]
}

// ─── Component ──────────────────────────────────────────────────────────────

export function CommandPalette({ navItems = [] }: CommandPaletteProps) {
  const [open, setOpen] = useState(false)
  const [, setRecentsTick] = useState(0)        // re-render trigger при pushRecent
  const navigate = useNavigate()
  const location = useLocation()
  const commands = useRegistry((s) => s.commands)

  // Global Cmd+K / Ctrl+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const close = useCallback(() => setOpen(false), [])

  // Активные команды (фильтр whenRoute) + recents-ordering
  const activeCommands = useMemo(() => {
    const list: AppCommand[] = []
    for (const cmd of commands.values()) {
      if (cmd.whenRoute && !cmd.whenRoute(location.pathname)) continue
      list.push(cmd)
    }
    return list
  }, [commands, location.pathname])

  const recentIds = useMemo(() => readRecents(), [open])
  const recents = useMemo(() => {
    return recentIds
      .map((id) => activeCommands.find((c) => c.id === id))
      .filter((c): c is AppCommand => !!c)
  }, [recentIds, activeCommands])

  const grouped = useMemo(() => {
    const groups = new Map<string, AppCommand[]>()
    for (const cmd of activeCommands) {
      const g = cmd.group ?? 'Действия'
      const arr = groups.get(g) ?? []
      arr.push(cmd)
      groups.set(g, arr)
    }
    return [...groups.entries()]
  }, [activeCommands])

  const handleRun = (cmd: AppCommand) => {
    pushRecent(cmd.id)
    setRecentsTick((x) => x + 1)
    close()
    // Запускаем после закрытия — модальное закрытие требует frame.
    setTimeout(() => cmd.run(), 0)
  }

  const handleNav = (to: string) => {
    pushRecent(`nav:${to}`)
    setRecentsTick((x) => x + 1)
    close()
    navigate(to)
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 bg-zinc-950/70 z-[70] flex items-start justify-center pt-[12vh]"
      onClick={close}
    >
      <Command
        label="Command Palette"
        className="w-full max-w-xl bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl shadow-black/60 overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') close()
        }}
      >
        <div className="flex items-center gap-2 px-3 border-b border-zinc-800">
          <SearchIcon size={14} className="text-zinc-500" />
          <Command.Input
            autoFocus
            placeholder="Куда перейти / что выполнить…"
            className="flex-1 h-10 bg-transparent text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
          />
        </div>

        <Command.List className="max-h-[60vh] overflow-y-auto py-2">
          <Command.Empty className="px-3 py-6 text-center text-xs text-zinc-500">
            Ничего не найдено
          </Command.Empty>

          {recents.length > 0 && (
            <Command.Group heading="Недавно" className={GROUP_CLS}>
              {recents.slice(0, 5).map((cmd) => (
                <Item key={`recent-${cmd.id}`} cmd={cmd} icon={Clock} onSelect={() => handleRun(cmd)} />
              ))}
            </Command.Group>
          )}

          {navItems.length > 0 && (
            <Command.Group heading="Страницы" className={GROUP_CLS}>
              {navItems.map((n) => (
                <Command.Item
                  key={n.to}
                  onSelect={() => handleNav(n.to)}
                  className={ITEM_CLS}
                >
                  <n.icon size={14} className="text-zinc-500" />
                  <span className="flex-1">{n.label}</span>
                  <span className="text-xxs font-mono text-zinc-600">{n.to}</span>
                  <ArrowRight size={11} className="text-zinc-600" />
                </Command.Item>
              ))}
            </Command.Group>
          )}

          {grouped.map(([group, items]) => (
            <Command.Group key={group} heading={group} className={GROUP_CLS}>
              {items.map((cmd) => (
                <Item
                  key={cmd.id}
                  cmd={cmd}
                  onSelect={() => handleRun(cmd)}
                />
              ))}
            </Command.Group>
          ))}
        </Command.List>

        <footer className="border-t border-zinc-800 px-3 py-1.5 flex items-center gap-2 text-xxs text-zinc-500">
          <KBD>↑↓</KBD> навигация
          <KBD>↵</KBD> запуск
          <KBD>Esc</KBD> закрыть
        </footer>
      </Command>
    </div>
  )
}

const GROUP_CLS = '[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-xxs [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-zinc-500'
const ITEM_CLS = 'flex items-center gap-2.5 px-3 h-8 mx-2 rounded text-xs text-zinc-200 cursor-pointer data-[selected=true]:bg-indigo-500/15 data-[selected=true]:text-zinc-100 data-[disabled=true]:opacity-40 data-[disabled=true]:cursor-not-allowed'

function Item({
  cmd, icon: ForcedIcon, onSelect,
}: {
  cmd: AppCommand
  icon?: LucideIcon
  onSelect: () => void
}) {
  const Icon = ForcedIcon ?? cmd.icon
  return (
    <Command.Item
      value={cmd.id + ' ' + cmd.label}
      onSelect={onSelect}
      disabled={cmd.disabled}
      className={clsx(ITEM_CLS)}
    >
      {Icon && <Icon size={14} className="text-zinc-500" />}
      <span className="flex-1 truncate">{cmd.label}</span>
      {cmd.hint && <span className="text-xxs font-mono text-zinc-600 truncate max-w-[35%]">{cmd.hint}</span>}
    </Command.Item>
  )
}
