import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { fetchHealth } from '../../lib/api'

interface Props {
  /** В коллапсе (узкий sidebar) рисуем только точку без текста. */
  compact?: boolean
}

/**
 * Индикатор подключения портала к parsers API.
 *
 * Стучимся раз в 30 секунд, чтобы пользователь видел реальный статус, а не
 * snapshot на момент загрузки. retry: false — иначе при недоступности
 * parsers React Query сделает несколько попыток и индикатор будет «дрожать».
 */
export function HealthBadge({ compact = false }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
    retry: false,
  })

  const status: 'loading' | 'ok' | 'down' =
    isLoading ? 'loading' :
    (isError || data?.parsers_api !== 'ok') ? 'down' :
    'ok'

  const dotClass = clsx(
    'inline-block w-2 h-2 rounded-full',
    status === 'ok' && 'bg-green-500',
    status === 'down' && 'bg-red-500',
    status === 'loading' && 'bg-gray-500 animate-pulse',
  )

  const label =
    status === 'loading' ? 'проверяю…' :
    status === 'ok' ? 'parsers ok' :
    'parsers недоступен'

  const Icon =
    status === 'loading' ? Loader2 :
    status === 'ok' ? CheckCircle2 :
    XCircle

  if (compact) {
    return (
      <span
        title={`${label}${data?.parsers_url ? ` · ${data.parsers_url}` : ''}`}
        className="inline-flex items-center"
      >
        <span className={dotClass} />
      </span>
    )
  }

  return (
    <div
      title={data?.error ?? label}
      className={clsx(
        'flex items-center gap-1.5 text-xs',
        status === 'ok' && 'text-green-400',
        status === 'down' && 'text-red-400',
        status === 'loading' && 'text-gray-500',
      )}
    >
      <Icon size={12} className={status === 'loading' ? 'animate-spin' : ''} />
      <span className="truncate">{label}</span>
    </div>
  )
}
