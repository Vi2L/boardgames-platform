/**
 * JobLogPanel — log-стрим с auto-scroll / pause / clear / copy.
 *
 * Использование (для long-running job UI — ImportJob, suite-run):
 *   <JobLogPanel
 *     lines={lines}        // string[] · ring buffer 200 строк снаружи
 *     onClear={() => …}
 *     onPause={() => …}
 *     paused={false}
 *   />
 *
 * Каждая строка — `[timestamp] LEVEL[12ch] source[…] message`. LEVEL цветится
 * по status-system (OK/WARN/FAIL/INFO/SKIP). Auto-scroll по умолчанию;
 * выключается при scroll-вверх (оператор смотрит историю — не дёргаем).
 *
 * Font-mono text-xxs (10px) — плотно. Width: full.
 */
import { useEffect, useRef, useState } from 'react'
import { Pause, Play, Copy, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import { toast } from 'sonner'

import { IconButton } from './IconButton'
import { Tooltip } from './Tooltip'

export interface JobLogPanelProps {
  lines: string[]
  className?: string
  paused?: boolean
  onPause?: () => void
  onResume?: () => void
  onClear?: () => void
  /** Высота в Tailwind-классе. По умолчанию h-64 (~256px). */
  height?: string
}

const LEVEL_COLORS: Record<string, string> = {
  OK:    'text-emerald-300',
  PASS:  'text-emerald-300',
  WARN:  'text-amber-300',
  WARNING: 'text-amber-300',
  FAIL:  'text-rose-300',
  ERR:   'text-rose-300',
  ERROR: 'text-rose-300',
  INFO:  'text-zinc-400',
  DEBUG: 'text-zinc-500',
  SKIP:  'text-zinc-500',
  SKIPPED: 'text-zinc-500',
}

function colorizeLine(line: string): JSX.Element {
  // Простая эвристика: ищем LEVEL в первых ~30 символах после timestamp.
  // Не строгий парсер — log format часто меняется, главное цвет угадать.
  const match = line.match(/\b(OK|PASS|WARN|WARNING|FAIL|ERR|ERROR|INFO|DEBUG|SKIP|SKIPPED)\b/)
  if (!match) {
    return <span className="text-zinc-400">{line}</span>
  }
  const level = match[1]
  const idx = match.index ?? 0
  const before = line.slice(0, idx)
  const after = line.slice(idx + level.length)
  return (
    <span>
      <span className="text-zinc-500">{before}</span>
      <span className={LEVEL_COLORS[level]}>{level}</span>
      <span className="text-zinc-400">{after}</span>
    </span>
  )
}

export function JobLogPanel({
  lines, className, paused, onPause, onResume, onClear, height = 'h-64',
}: JobLogPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  // Auto-scroll: при добавлении строки скроллим вниз, если оператор не уехал
  // в историю (autoScroll=false). Auto-scroll выключается при user-scroll
  // не в самом низу.
  useEffect(() => {
    if (!autoScroll) return
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [lines, autoScroll])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 16
    setAutoScroll(atBottom)
  }

  const handleCopy = () => {
    const text = lines.join('\n')
    navigator.clipboard.writeText(text).then(
      () => toast.success(`Скопировано ${lines.length} строк`),
      () => toast.error('Не удалось скопировать'),
    )
  }

  return (
    <div className={clsx(
      'flex flex-col bg-zinc-950 border border-zinc-800 rounded overflow-hidden',
      className,
    )}>
      <header className="flex items-center justify-between gap-2 px-2.5 h-8 border-b border-zinc-800 bg-zinc-900 shrink-0">
        <span className="text-xxs uppercase tracking-widest text-zinc-500 font-mono">
          log · {lines.length} строк
        </span>
        <div className="flex items-center gap-1">
          {(onPause || onResume) && (
            <Tooltip content={paused ? 'Resume' : 'Pause'}>
              <IconButton
                icon={paused ? Play : Pause}
                size="xs"
                aria-label={paused ? 'Resume' : 'Pause'}
                onClick={paused ? onResume : onPause}
              />
            </Tooltip>
          )}
          <Tooltip content="Скопировать">
            <IconButton icon={Copy} size="xs" aria-label="Скопировать log" onClick={handleCopy} />
          </Tooltip>
          {onClear && (
            <Tooltip content="Очистить">
              <IconButton icon={Trash2} size="xs" aria-label="Очистить log" onClick={onClear} />
            </Tooltip>
          )}
        </div>
      </header>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={clsx(
          'overflow-y-auto font-mono text-xxs leading-relaxed',
          'px-2.5 py-1.5',
          height,
        )}
      >
        {lines.length === 0 ? (
          <div className="text-zinc-600 italic">пусто — лог появится при запуске job'а</div>
        ) : (
          lines.map((l, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              {colorizeLine(l)}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
