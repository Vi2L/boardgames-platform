import clsx from 'clsx'
import { Check, X, Zap, Loader2, Clock } from 'lucide-react'
import type { StoreProgress } from '../../types/api'

interface Props {
  progress: StoreProgress
}

export function StoreProgressBadge({ progress }: Props) {
  const { status, name, count, elapsed_ms, error } = progress

  const configs = {
    pending: {
      icon: <Clock size={12} />,
      color: 'text-gray-400',
      bg: 'bg-gray-800/60',
      border: 'border-gray-700',
      label: 'Ожидание',
    },
    running: {
      icon: <Loader2 size={12} className="animate-spin" />,
      color: 'text-blue-400',
      bg: 'bg-blue-950/50',
      border: 'border-blue-800',
      label: 'Запрос…',
    },
    done: {
      icon: <Check size={12} />,
      color: 'text-green-400',
      bg: 'bg-green-950/50',
      border: 'border-green-800',
      label: `${count ?? 0} шт.${elapsed_ms != null ? ` · ${elapsed_ms}ms` : ''}`,
    },
    error: {
      icon: <X size={12} />,
      color: 'text-red-400',
      bg: 'bg-red-950/50',
      border: 'border-red-800',
      label: error ? (error.length > 40 ? error.slice(0, 40) + '…' : error) : 'Ошибка',
    },
    cache: {
      icon: <Zap size={12} />,
      color: 'text-yellow-400',
      bg: 'bg-yellow-950/50',
      border: 'border-yellow-800',
      label: `Кэш · ${count ?? 0}`,
    },
  }

  const cfg = configs[status]

  return (
    <div className={clsx(
      'flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs border',
      cfg.color, cfg.bg, cfg.border,
    )}>
      {cfg.icon}
      <span className="font-semibold text-gray-200">{name}</span>
      <span className="text-gray-400">{cfg.label}</span>
    </div>
  )
}
