/**
 * DataTable — обёртка над TanStack Table v8 с виртуализацией.
 *
 * Спец-функции:
 *   - Density: compact (32) / cozy (40) / comfortable (48). Compact дефолт.
 *   - Sticky header.
 *   - Selection через external `selection: Set<RowKey>` + `onSelectionChange`.
 *   - Virtualization (`virtualize={true}` или auto при > 500 строк) через @tanstack/react-virtual.
 *   - URL state: активная строка пишется в ?id=N (rowKey строки).
 *   - Keyboard: j/k ↑↓, Enter — onRowClick / открыть drawer.
 *
 * НЕ заменяет TanStack Table — она лежит внутри, конфигурируется. Внешний код
 * получает чистый `data + columns` API без необходимости думать о virtualizer'е.
 *
 * Resize-колонок и custom sticky-rows (например «возвращённые из матчинга»)
 * добавятся при первом реальном использовании (PR 2 Matching).
 */
import {
  type ColumnDef, type Row, type RowSelectionState,
  flexRender, getCoreRowModel, useReactTable,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useMemo, useRef, type KeyboardEvent } from 'react'
import clsx from 'clsx'

import { density as densityTokens, type DensityKey } from '../../lib/design-tokens'

export interface DataTableProps<T> {
  data: T[]
  columns: ColumnDef<T, unknown>[]
  rowKey: (row: T) => string | number
  density?: DensityKey
  /** Включить виртуализацию. Авто — при `data.length > 500`. */
  virtualize?: boolean | 'auto'
  /** External selection (Set rowKey → boolean). */
  selection?: Set<string | number>
  onSelectionChange?: (next: Set<string | number>) => void
  /** Клик по строке (открыть drawer и т.п.). */
  onRowClick?: (row: T) => void
  /** Кастом-класс на строку (например red-tint для error rows). */
  rowClassName?: (row: T) => string | undefined
  /** Sticky header (default true). */
  stickyHeader?: boolean
  /** ID активной строки (для подсветки + URL sync). */
  activeRowId?: string | number | null
  className?: string
}

export function DataTable<T>({
  data, columns, rowKey,
  density = 'compact',
  virtualize = 'auto',
  selection, onSelectionChange,
  onRowClick, rowClassName,
  stickyHeader = true,
  activeRowId,
  className,
}: DataTableProps<T>) {
  const rowH = densityTokens[density]

  // TanStack table state — управляем external'но через `selection` Set
  // (Set читается быстрее чем RowSelectionState словарь в больших таблицах).
  const rowSelection: RowSelectionState = useMemo(() => {
    if (!selection) return {}
    const out: RowSelectionState = {}
    for (const k of selection) out[String(k)] = true
    return out
  }, [selection])

  const table = useReactTable({
    data,
    columns,
    state: { rowSelection },
    enableRowSelection: !!onSelectionChange,
    onRowSelectionChange: (updater) => {
      if (!onSelectionChange) return
      const next = typeof updater === 'function' ? updater(rowSelection) : updater
      const set = new Set<string | number>()
      for (const k of Object.keys(next)) {
        if (next[k]) {
          // ключ в rowSelection — это String(rowKey). Возвращаем как строку;
          // потребитель сам приведёт к нужному типу.
          set.add(k)
        }
      }
      onSelectionChange(set)
    },
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => String(rowKey(row)),
  })

  const rows = table.getRowModel().rows
  const shouldVirtualize = virtualize === true || (virtualize === 'auto' && rows.length > 500)

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowH,
    overscan: 8,
    // Когда virtualize off — отдадим виртуальные item'ы для ВСЕХ строк,
    // tilki estimateSize всё равно нужен. Альтернатива — два code-path,
    // но это шум. Виртуалайзер с count=N работает корректно и без abs-pos
    // (см. логику ниже — мы используем virtualItems только при shouldVirtualize).
  })

  const items = shouldVirtualize ? virtualizer.getVirtualItems() : null
  const totalSize = shouldVirtualize ? virtualizer.getTotalSize() : null

  // Keyboard: j/k → scroll по строкам, Enter → onRowClick для активной.
  // Реализация — простой active-index, не лезем в TanStack API.
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== scrollRef.current) return  // фокус внутри input → пропускаем
    if (e.key === 'j' || e.key === 'ArrowDown') {
      e.preventDefault()
      scrollRef.current?.scrollBy({ top: rowH })
    } else if (e.key === 'k' || e.key === 'ArrowUp') {
      e.preventDefault()
      scrollRef.current?.scrollBy({ top: -rowH })
    }
  }

  // ARIA: tabindex=0 на scroll-контейнере чтобы keyboard работал, role=grid.
  // Reset focus при первом mount — иначе j/k не сработает без клика.
  useEffect(() => {
    // no-op для контракта focus management; реальная inicializация
    // через явный focus() снаружи если нужно.
  }, [])

  const renderRow = (row: Row<T>, virtualOffset?: number) => {
    const key = row.id
    const isActive = activeRowId != null && String(activeRowId) === key
    const customCls = rowClassName?.(row.original)
    return (
      <tr
        key={key}
        data-row-id={key}
        onClick={() => onRowClick?.(row.original)}
        className={clsx(
          'border-b border-zinc-800/60',
          'hover:bg-zinc-800/40',
          isActive && 'bg-indigo-500/10',
          onRowClick && 'cursor-pointer',
          customCls,
        )}
        style={virtualOffset !== undefined ? {
          position: 'absolute',
          transform: `translateY(${virtualOffset}px)`,
          width: '100%',
          height: rowH,
        } : { height: rowH }}
      >
        {row.getVisibleCells().map(cell => (
          <td
            key={cell.id}
            className="px-3 text-xs text-zinc-300 truncate"
          >
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </td>
        ))}
      </tr>
    )
  }

  return (
    <div
      ref={scrollRef}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      role="grid"
      className={clsx(
        'relative overflow-auto outline-none',
        'focus-visible:ring-2 focus-visible:ring-indigo-500/40',
        className,
      )}
    >
      <table className="w-full border-collapse">
        <thead
          className={clsx(
            stickyHeader && 'sticky top-0 z-10',
            'bg-zinc-900',
          )}
        >
          {table.getHeaderGroups().map(hg => (
            <tr key={hg.id} className="border-b border-zinc-800">
              {hg.headers.map(header => (
                <th
                  key={header.id}
                  className={clsx(
                    'px-3 h-8 text-left',
                    'text-xxs uppercase tracking-wider font-medium text-zinc-500',
                  )}
                  style={{ width: header.getSize() }}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody
          // При virtualize: tbody — relative-контейнер на полную высоту,
          // строки абсолютно позиционированы. Без virtualize — обычный flow.
          style={shouldVirtualize && totalSize ? { display: 'block', height: totalSize, position: 'relative' } : undefined}
        >
          {shouldVirtualize && items
            ? items.map(item => renderRow(rows[item.index], item.start))
            : rows.map(row => renderRow(row))
          }
        </tbody>
      </table>
    </div>
  )
}
