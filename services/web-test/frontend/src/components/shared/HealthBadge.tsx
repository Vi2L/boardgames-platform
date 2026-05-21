import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { fetchHealthAll } from '../../lib/api'
import { Popover } from '../ui/Popover'
import { MlStatusBadge } from './MlStatusBadge'

interface Props {
  /** В коллапсе (узкий sidebar) рисуем только точку без текста. */
  compact?: boolean
}

/**
 * Индикатор подключения портала к parsers + catalog.
 *
 * Использует `/api/health/all` (deep-check с метриками обоих сервисов).
 * Клик открывает popover-карту со счётчиками: размер БД parsers, total
 * games в catalog, кол-во unmatched offer'ов и т.п.
 *
 * 30s polling. retry: false — иначе при недоступности React Query делает
 * несколько попыток и индикатор «дрожит».
 *
 * Popover рендерится через `ui/Popover` (Radix Portal) — обходит
 * `overflow-hidden` родителя автоматически, поэтому ранее нужный
 * `fixed inset-0` overlay для закрытия и предупреждение в CLAUDE.md
 * больше не актуальны.
 */
export function HealthBadge({ compact = false }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['health-all'],
    queryFn: fetchHealthAll,
    refetchInterval: 30_000,
    retry: false,
  })

  const parsersOk = data?.parsers.status === 'ok'
  const catalogOk = data?.catalog.status === 'ok'
  const status: 'loading' | 'ok' | 'partial' | 'down' =
    isLoading ? 'loading' :
    isError ? 'down' :
    (parsersOk && catalogOk) ? 'ok' :
    (parsersOk || catalogOk) ? 'partial' :
    'down'

  const dotClass = clsx(
    'inline-block w-2 h-2 rounded-full',
    status === 'ok' && 'bg-green-500',
    status === 'partial' && 'bg-amber-500',
    status === 'down' && 'bg-red-500',
    status === 'loading' && 'bg-zinc-500 animate-pulse',
  )

  const label =
    status === 'loading' ? 'проверяю…' :
    status === 'ok' ? 'oба сервиса ok' :
    status === 'partial' ? 'один сервис недоступен' :
    'оба недоступны'

  const Icon =
    status === 'loading' ? Loader2 :
    status === 'ok' ? CheckCircle2 :
    XCircle

  return (
    <Popover
      side="top"
      align="start"
      sideOffset={6}
      className="w-72 space-y-3 text-xs"
      content={
        data
          ? <HealthPopoverContent data={data} />
          : isError
            ? <div className="text-xs text-red-400">Health-check провалился.</div>
            : (
              <div className="text-xs text-zinc-400 inline-flex items-center gap-2">
                <Loader2 size={11} className="animate-spin" /> Загрузка…
              </div>
            )
      }
    >
      <button
        type="button"
        title={label}
        className={clsx(
          'flex items-center gap-1.5 text-xs cursor-pointer',
          'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-indigo-500 rounded',
          status === 'ok' && 'text-green-400',
          status === 'partial' && 'text-amber-400',
          status === 'down' && 'text-red-400',
          status === 'loading' && 'text-zinc-500',
          compact && 'justify-center',
        )}
      >
        {compact ? (
          <span className={dotClass} />
        ) : (
          <>
            <Icon size={12} className={status === 'loading' ? 'animate-spin' : ''} />
            <span className="truncate">{label}</span>
          </>
        )}
      </button>
    </Popover>
  )
}

function HealthPopoverContent({
  data,
}: {
  data: import('../../types/api').HealthAllResponse
}) {
  return (
    <>
      <ServiceBlock
        name="parsers"
        status={data.parsers.status}
        url={data.parsers.url}
        error={data.parsers.error}
      >
        {data.parsers.meta && (
          <div className="space-y-0.5 mt-1">
            <Stat label="размер БД" value={fmtBytes(data.parsers.meta.size_bytes)} />
            <Stat label="товаров" value={data.parsers.meta.product_count?.toLocaleString() ?? '—'} />
            <Stat label="наблюдений" value={data.parsers.meta.observation_count?.toLocaleString() ?? '—'} />
            <Stat label="последнее" value={data.parsers.meta.newest_observation?.slice(0, 16) ?? '—'} />
          </div>
        )}
      </ServiceBlock>

      <ServiceBlock
        name="catalog"
        status={data.catalog.status}
        url={data.catalog.url}
        error={data.catalog.error}
      >
        <div className="space-y-0.5 mt-1">
          <Stat label="игр в каталоге" value={data.catalog.total_games?.toLocaleString() ?? '—'} />
          <Stat label="unmatched оффер'ов"
                value={data.catalog.unmatched_offers?.toLocaleString() ?? '—'} />
          {data.catalog.unmatched_good != null && data.catalog.unmatched_good > 0 && (
            <Stat label="из них good ≥0.6"
                  value={`${data.catalog.unmatched_good}`}
                  color="text-emerald-400" />
          )}
        </div>
      </ServiceBlock>

      {/* Matcher v2: статус локальной Ollama (bge-m3 + qwen2.5) */}
      <div className="pt-1 border-t border-zinc-800">
        <MlStatusBadge />
      </div>

      <div className="text-[10px] text-zinc-600 font-mono pt-1 border-t border-zinc-800">
        checked: {new Date(data.checked_at).toLocaleString('ru-RU', { hour12: false })}
      </div>
    </>
  )
}

function ServiceBlock({
  name, status, url, error, children,
}: {
  name: string
  status: string
  url: string
  error?: string
  children?: React.ReactNode
}) {
  const ok = status === 'ok'
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className={clsx('w-2 h-2 rounded-full', ok ? 'bg-green-500' : 'bg-red-500')} />
        <span className="text-zinc-200 font-medium">{name}</span>
        <span className={clsx('font-mono ml-auto', ok ? 'text-green-400' : 'text-red-400')}>
          {status}
        </span>
      </div>
      <div className="text-zinc-500 font-mono truncate" title={url}>{url}</div>
      {error && <div className="text-red-300 font-mono text-[10px] mt-0.5 truncate" title={error}>{error}</div>}
      {children}
    </div>
  )
}

function Stat({
  label, value, color,
}: {
  label: string
  value: string
  color?: string
}) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-zinc-500">{label}</span>
      <span className={clsx('font-mono', color ?? 'text-zinc-300')}>{value}</span>
    </div>
  )
}

function fmtBytes(b?: number | null): string {
  if (b == null) return '—'
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
}
