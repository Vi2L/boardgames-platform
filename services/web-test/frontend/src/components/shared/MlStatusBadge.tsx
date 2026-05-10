import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Cpu } from 'lucide-react'
import { fetchMlStatus } from '../../lib/catalog'

/**
 * Статус локальной Ollama (bge-m3 + qwen2.5) и размер очереди T2/T3.
 *
 * Вставляется в HealthBadge popover (третий блок после parsers/catalog).
 * Polling 30 сек — кэшированное значение от scheduler-job'а в catalog'е.
 */
export function MlStatusBadge() {
  const { data, isError } = useQuery({
    queryKey: ['catalog', 'ml-status'],
    queryFn: fetchMlStatus,
    refetchInterval: 30_000,
    retry: false,
  })

  if (isError || !data) {
    return (
      <div className="text-xs text-gray-500">
        ML: <span className="text-red-400 font-mono">недоступно</span>
      </div>
    )
  }

  const allUp = Object.values(data.models).every(Boolean)
  const anyUp = Object.values(data.models).some(Boolean)
  const dotClass = clsx(
    'w-2 h-2 rounded-full',
    allUp && 'bg-green-500',
    !allUp && anyUp && 'bg-amber-500',
    !anyUp && 'bg-red-500',
  )

  const pending = data.queue?.pending ?? 0
  const processing = data.queue?.processing ?? 0
  const failed = data.queue?.failed ?? 0

  return (
    <div>
      <div className="flex items-center gap-2">
        <span className={dotClass} />
        <Cpu size={11} className="text-gray-500" />
        <span className="text-gray-200 font-medium">ML matching</span>
      </div>
      <div className="space-y-0.5 mt-1 ml-3.5">
        {Object.entries(data.models).map(([model, available]) => (
          <div key={model} className="flex justify-between gap-2 text-xs">
            <span className="text-gray-500 font-mono truncate max-w-[160px]" title={model}>
              {model}
            </span>
            <span className={clsx('font-mono', available ? 'text-green-400' : 'text-red-400')}>
              {available ? 'online' : 'offline'}
            </span>
          </div>
        ))}
        {(pending > 0 || processing > 0 || failed > 0) && (
          <div className="text-xs text-gray-500 mt-1 pt-1 border-t border-gray-800">
            очередь:{' '}
            {pending > 0 && <span className="text-violet-400 font-mono">{pending} pend</span>}
            {processing > 0 && (
              <span className="text-blue-400 font-mono ml-1.5">{processing} proc</span>
            )}
            {failed > 0 && (
              <span className="text-red-400 font-mono ml-1.5">{failed} fail</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
