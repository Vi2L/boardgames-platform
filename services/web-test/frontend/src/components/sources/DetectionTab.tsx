/**
 * Detection: запуск сухого прогона + список последних runs + diff drawer.
 *
 * Поток оператора:
 *  1. Жмёт «Запустить прогон» → RunStartDialog → POST /sources/{provider}/runs.
 *  2. Run появляется в таблице со status='running', автообновление каждые 3с.
 *  3. По переходе в 'ready' оператор открывает run → RunDiffDrawer.
 *  4. В drawer'е видит сводку и items (фильтр new/updated), apply / discard.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Play } from 'lucide-react'
import { fetchSourceRuns, type ScrapeRun, type ScrapeRunStatus } from '../../lib/sources'
import { RunStartDialog } from './RunStartDialog'
import { RunDiffDrawer } from './RunDiffDrawer'

type Props = { provider: string }

const STATUS_COLOR: Record<ScrapeRunStatus, string> = {
  running: 'bg-blue-900/40 text-blue-300',
  ready: 'bg-amber-900/40 text-amber-300',
  applied: 'bg-emerald-900/40 text-emerald-300',
  discarded: 'bg-gray-800 text-gray-400',
  failed: 'bg-red-900/40 text-red-300',
}

export function DetectionTab({ provider }: Props) {
  const [startOpen, setStartOpen] = useState(false)
  const [openRunId, setOpenRunId] = useState<number | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['sources', provider, 'runs'],
    queryFn: () => fetchSourceRuns(provider),
    // Поллим, чтобы свежий status running→ready подтянулся без F5.
    refetchInterval: 3000,
  })

  return (
    <div className="space-y-4 max-w-5xl">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-100">Сухие прогоны</h2>
        <button
          type="button"
          onClick={() => setStartOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-violet-700 text-white hover:bg-violet-600"
        >
          <Play size={14} />
          Запустить прогон
        </button>
      </div>

      <p className="text-sm text-gray-400">
        Сухой прогон скачивает свежее состояние сайта без записи в staging.
        После завершения — превью diff и решение «применить» / «отбросить».
      </p>

      {isLoading && <div className="text-gray-500 text-sm">загрузка…</div>}
      {error && <div className="text-red-400 text-sm">ошибка: {String(error)}</div>}

      {data && data.runs.length === 0 && (
        <div className="rounded-md border border-gray-800 p-6 text-center text-sm text-gray-500">
          Прогонов пока нет. Запустите первый выше.
        </div>
      )}

      {data && data.runs.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="text-left font-normal py-2 pr-4">id</th>
              <th className="text-left font-normal pr-4">когда</th>
              <th className="text-left font-normal pr-4">status</th>
              <th className="text-right font-normal pr-3">new</th>
              <th className="text-right font-normal pr-3">updated</th>
              <th className="text-right font-normal pr-3">unchanged</th>
              <th className="text-right font-normal pr-3">errors</th>
              <th />
            </tr>
          </thead>
          <tbody className="text-gray-200">
            {data.runs.map(r => (
              <RunRow key={r.id} run={r} onOpen={() => setOpenRunId(r.id)} />
            ))}
          </tbody>
        </table>
      )}

      <RunStartDialog
        provider={provider}
        open={startOpen}
        onClose={() => setStartOpen(false)}
      />
      <RunDiffDrawer
        provider={provider}
        runId={openRunId}
        onClose={() => setOpenRunId(null)}
      />
    </div>
  )
}

function RunRow({ run, onOpen }: { run: ScrapeRun; onOpen: () => void }) {
  return (
    <tr
      className="border-t border-gray-800/60 hover:bg-gray-900/40 cursor-pointer"
      onClick={onOpen}
    >
      <td className="py-2 pr-4 font-mono text-xs">#{run.id}</td>
      <td className="pr-4 text-gray-400">
        {new Date(run.started_at).toLocaleString()}
      </td>
      <td className="pr-4">
        <span className={clsx('px-1.5 py-0.5 rounded text-[11px]', STATUS_COLOR[run.status])}>
          {run.status}
        </span>
      </td>
      <td className="pr-3 text-right tabular-nums text-emerald-300">
        {run.totals.new ?? '—'}
      </td>
      <td className="pr-3 text-right tabular-nums text-amber-300">
        {run.totals.updated ?? '—'}
      </td>
      <td className="pr-3 text-right tabular-nums text-gray-500">
        {run.totals.unchanged ?? '—'}
      </td>
      <td className="pr-3 text-right tabular-nums text-red-400">
        {run.totals.errors ?? '—'}
      </td>
      <td className="text-right text-violet-400 text-xs">→</td>
    </tr>
  )
}
