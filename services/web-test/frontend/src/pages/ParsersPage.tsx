import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Cpu } from 'lucide-react'
import { fetchParsers } from '../lib/api'
import { ParserCard } from '../components/parsers/ParserCard'
import { Badge, Button, EmptyState } from '../components/ui'

export function ParsersPage() {
  const { data: parsers = [], isLoading, refetch, isFetching } = useQuery({
    queryKey: ['parsers'],
    queryFn: fetchParsers,
    refetchInterval: 15_000,
  })

  const allAvailable = parsers.length > 0 && parsers.every(p => p.available)
  const anyError = parsers.some(p => p.available === false)

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Парсеры</h1>
          <p className="text-xs text-zinc-500 mt-0.5">
            Ручной запуск и диагностика каждого магазина
          </p>
        </div>
        <div className="flex items-center gap-3">
          {!isLoading && parsers.length > 0 && (
            allAvailable
              ? <Badge status="done" size="sm">parsers API доступен</Badge>
              : anyError
                ? <Badge status="failed" size="sm">ошибка подключения</Badge>
                : <Badge status="processing" size="sm">проверка</Badge>
          )}
          <Button
            variant="ghost"
            size="sm"
            icon={RefreshCw}
            loading={isFetching}
            onClick={() => refetch()}
          >
            Обновить
          </Button>
        </div>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-52 bg-zinc-900 border border-zinc-800 rounded-lg animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && parsers.length === 0 && (
        <EmptyState
          icon={Cpu}
          title="parsers API недоступен"
          description="Запусти: uvicorn parsers.api:app --port 8001"
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {parsers.map(p => <ParserCard key={p.slug} parser={p} />)}
      </div>
    </div>
  )
}
