/**
 * Logs: двухколоночный журнал — promotion log + scrape runs.
 *
 * Слева: promotion log (PromotionLogList переиспользуется из catalog/) — это
 * история действий promote/skip/reject/revert с возможностью отката.
 *
 * Справа: scrape runs — компактный список последних сухих прогонов, чтобы
 * оператор видел общую картину «когда мы видели что-то новое на сайте».
 */
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { PromotionLogList } from '../catalog/PromotionPanel'
import { fetchSourceRuns, type ScrapeRun, type ScrapeRunStatus } from '../../lib/sources'

type Props = { provider: string }

const STATUS_COLOR: Record<ScrapeRunStatus, string> = {
  running: 'bg-blue-900/40 text-blue-300',
  ready: 'bg-amber-900/40 text-amber-300',
  applied: 'bg-emerald-900/40 text-emerald-300',
  discarded: 'bg-gray-800 text-gray-400',
  failed: 'bg-red-900/40 text-red-300',
}

export function SourcesLogsTab({ provider }: Props) {
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_22rem] gap-6">
      <section>
        <h3 className="text-sm font-semibold text-gray-200 mb-3">
          Журнал промоушенов ({provider} → canonical)
        </h3>
        <PromotionLogList />
      </section>

      <section>
        <h3 className="text-sm font-semibold text-gray-200 mb-3">
          Сухие прогоны
        </h3>
        <ScrapeRunsList provider={provider} />
      </section>
    </div>
  )
}

function ScrapeRunsList({ provider }: { provider: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['sources', provider, 'runs', 'logs-tab'],
    queryFn: () => fetchSourceRuns(provider, 30),
  })

  if (isLoading) return <div className="text-sm text-gray-500">загрузка…</div>

  if (!data || data.runs.length === 0) {
    return (
      <div className="text-xs text-gray-500 rounded-md border border-gray-800 p-3">
        Пока ни одного прогона.
      </div>
    )
  }

  return (
    <ul className="space-y-1.5">
      {data.runs.map(r => (
        <RunCompactRow key={r.id} run={r} />
      ))}
    </ul>
  )
}

function RunCompactRow({ run }: { run: ScrapeRun }) {
  const totals = run.totals
  return (
    <li className="rounded-md border border-gray-800/60 bg-gray-900/40 px-3 py-2 text-xs">
      <div className="flex items-center justify-between gap-2 mb-0.5">
        <span className="font-mono text-gray-500">#{run.id}</span>
        <span className={clsx('px-1.5 py-0.5 rounded text-[10px]', STATUS_COLOR[run.status])}>
          {run.status}
        </span>
      </div>
      <div className="text-gray-400">
        {new Date(run.started_at).toLocaleString()}
      </div>
      <div className="mt-1 flex gap-3 text-[11px] tabular-nums">
        <span className="text-emerald-300">new {totals.new ?? 0}</span>
        <span className="text-amber-300">upd {totals.updated ?? 0}</span>
        <span className="text-gray-500">unc {totals.unchanged ?? 0}</span>
        {totals.errors ? (
          <span className="text-red-400">err {totals.errors}</span>
        ) : null}
        {totals.applied ? (
          <span className="text-indigo-300">applied {totals.applied}</span>
        ) : null}
      </div>
    </li>
  )
}
