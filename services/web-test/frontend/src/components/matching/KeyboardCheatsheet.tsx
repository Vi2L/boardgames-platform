/**
 * KeyboardCheatsheet — overlay со списком шорткатов, открывается `?`, закрывается `Esc`.
 *
 * Спека §F handoff. Legend генерируется из useMatchingShortcuts() — источник
 * правды одной строкой (id + label + keys). Это гарантирует что cheatsheet не
 * рассинхронизируется с реально работающими шорткатами.
 *
 * Открытие через global key listener — навешан в MatchingPage.tsx.
 */
import { useEffect } from 'react'
import { X } from 'lucide-react'
import clsx from 'clsx'

export interface ShortcutItem {
  /** Ключ-комбо как читаемая строка: `J`, `K`, `Cmd+K`, `Shift+Click`. */
  keys: string[]
  description: string
}

export interface ShortcutGroup {
  title: string
  items: ShortcutItem[]
}

export interface KeyboardCheatsheetProps {
  open: boolean
  onClose: () => void
  /** Группы шорткатов. Каждая — title + items. */
  groups: ShortcutGroup[]
  className?: string
}

export function KeyboardCheatsheet({
  open, onClose, groups, className,
}: KeyboardCheatsheetProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[60] bg-zinc-950/70 flex items-start justify-center pt-[8vh]"
      onClick={onClose}
      role="dialog"
      aria-label="Keyboard shortcuts"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={clsx(
          'w-full max-w-2xl bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl shadow-black/60',
          'p-5 max-h-[80vh] overflow-y-auto',
          className,
        )}
      >
        <header className="flex items-center justify-between mb-4 pb-3 border-b border-zinc-800">
          <h2 className="text-base font-semibold text-zinc-100">Keyboard shortcuts</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded text-zinc-500 hover:text-zinc-100 hover:bg-zinc-800/60"
            aria-label="Закрыть"
          >
            <X size={14} />
          </button>
        </header>

        <div className="grid grid-cols-2 gap-x-6 gap-y-4">
          {groups.map(group => (
            <section key={group.title}>
              <h3 className="text-xxs uppercase tracking-widest text-zinc-500 font-mono mb-2">
                {group.title}
              </h3>
              <ul className="space-y-1">
                {group.items.map((item, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 text-xs">
                    <span className="text-zinc-300 flex-1 min-w-0 truncate">{item.description}</span>
                    <span className="flex items-center gap-1 shrink-0">
                      {item.keys.map((k, j) => (
                        <kbd
                          key={j}
                          className={clsx(
                            'inline-flex items-center justify-center',
                            'min-w-[20px] h-5 px-1',
                            'border border-zinc-700 rounded bg-zinc-950',
                            'font-mono text-[10px] text-zinc-300',
                            'shadow-[inset_0_-1px_0_0_rgba(0,0,0,0.4)]',
                          )}
                        >
                          {k}
                        </kbd>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <footer className="mt-5 pt-3 border-t border-zinc-800 text-xxs font-mono text-zinc-600">
          Закрыть: <kbd className="px-1 border border-zinc-700 rounded">Esc</kbd> или клик вне окна
        </footer>
      </div>
    </div>
  )
}

// ── Default groups for /matching ────────────────────────────────────────────

export const MATCHING_SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: 'Навигация',
    items: [
      { keys: ['1'], description: 'Вкладка Контроль' },
      { keys: ['2'], description: 'Вкладка Очередь' },
      { keys: ['3'], description: 'Вкладка Журнал' },
      { keys: ['4'], description: 'Вкладка Штучный' },
      { keys: ['5'], description: 'Вкладка Help' },
      { keys: ['⌘', 'K'], description: 'Command palette' },
      { keys: ['?'], description: 'Открыть этот overlay' },
    ],
  },
  {
    title: 'Контроль',
    items: [
      { keys: ['K'], description: 'Toggle ML kill-switch' },
      { keys: ['R'], description: 'Запустить worker tick' },
      { keys: ['W'], description: 'Запустить warmup' },
      { keys: ['Shift', 'P'], description: 'Force probe моделей' },
    ],
  },
  {
    title: 'Очередь · таблица',
    items: [
      { keys: ['J', 'K'], description: 'Навигация по строкам' },
      { keys: ['Space'], description: 'Toggle select' },
      { keys: ['Shift+Click'], description: 'Select range' },
      { keys: ['A'], description: 'Select all matching filter' },
      { keys: ['⌘', '↵'], description: 'Bulk action на выбранных' },
      { keys: ['Esc'], description: 'Снять выделение' },
    ],
  },
  {
    title: 'Штучный',
    items: [
      { keys: ['↵'], description: 'Запустить v2 на найденном offer' },
      { keys: ['/'], description: 'Фокус search' },
      { keys: ['Esc'], description: 'Cancel pending запрос' },
    ],
  },
]
