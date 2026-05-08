/**
 * Logs: журнал промоушенов + scrape runs (compact).
 * Полная имплементация на задаче #13 — двухколоночный layout.
 * Сейчас показываем только список scrape runs как заглушку.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchSourceRuns } from '../../lib/sources'

type Props = { provider: string }

export function SourcesLogsTab({ provider }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['sources', provider, 'runs', 'log-tab'],
    queryFn: () => fetchSourceRuns(provider, 50),
  })

  return (
    <div className="space-y-4 max-w-4xl">
      <h2 className="text-base font-semibold text-gray-100">
        Журнал событий
      </h2>
      <p className="text-sm text-gray-400">
        В следующей итерации сюда добавится журнал промоушенов с откатом.
        Сейчас — только список последних scrape runs.
      </p>

      {isLoading && <div className="text-gray-500 text-sm">загрузка…</div>}

      {data && (
        <ul className="space-y-1.5">
          {data.runs.map(r => (
            <li
              key={r.id}
              className="text-xs font-mono px-3 py-2 rounded bg-gray-900/40 border border-gray-800/60"
            >
              <span className="text-gray-500">#{r.id}</span>{' '}
              <span className="text-gray-400">
                {new Date(r.started_at).toLocaleString()}
              </span>{' '}
              <span className="text-gray-300">{r.status}</span>{' '}
              <span className="text-gray-500">
                new={r.totals.new ?? 0} upd={r.totals.updated ?? 0} unc=
                {r.totals.unchanged ?? 0} err={r.totals.errors ?? 0}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
