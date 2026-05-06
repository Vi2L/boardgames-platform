import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Cpu, CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { fetchParsers } from '../lib/api'
import { ParserCard } from '../components/parsers/ParserCard'

export function ParsersPage() {
  const { data: parsers = [], isLoading, refetch, isFetching } = useQuery({
    queryKey: ['parsers'],
    queryFn: fetchParsers,
    refetchInterval: 15_000,
  })

  const allAvailable = parsers.length > 0 && parsers.every(p => p.available)
  const anyError = parsers.some(p => p.available === false)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-100">Парсеры</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Ручной запуск и диагностика каждого магазина
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Статус подключения к parsers API */}
          {!isLoading && parsers.length > 0 && (
            <div className={clsx('flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border',
              allAvailable
                ? 'bg-green-950/50 border-green-800 text-green-400'
                : anyError
                  ? 'bg-red-950/50 border-red-800 text-red-400'
                  : 'bg-gray-800 border-gray-700 text-gray-400'
            )}>
              {allAvailable
                ? <><CheckCircle2 size={11} /> parsers API доступен</>
                : <><XCircle size={11} /> ошибка подключения</>
              }
            </div>
          )}
          {isLoading && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Loader2 size={11} className="animate-spin" /> Проверка…
            </div>
          )}
          <button
            onClick={() => refetch()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
          >
            <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
            Обновить
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-52 bg-gray-900 border border-gray-800 rounded-lg animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && parsers.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-500 space-y-3">
          <Cpu size={32} className="opacity-30" />
          <div className="text-sm">parsers API недоступен</div>
          <div className="text-xs text-gray-600">
            Запусти: uvicorn parsers.api:app --port 8001
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {parsers.map(p => <ParserCard key={p.slug} parser={p} />)}
      </div>
    </div>
  )
}
