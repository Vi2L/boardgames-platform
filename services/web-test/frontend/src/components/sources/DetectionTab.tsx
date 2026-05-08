/**
 * Detection: запуск сухого прогона + список последних runs + diff drawer.
 *
 * Полная имплементация будет в следующей итерации (#10): RunStartDialog,
 * таблица runs с polling'ом, RunDiffDrawer с field_diffs и apply/discard.
 * Сейчас — каркас с listing'ом для проверки api-плотности.
 */
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { fetchSourceRuns, type ScrapeRun, type ScrapeRunStatus } from '../../lib/sources'

type Props = { provider: string }

const STATUS_COLOR: Record<ScrapeRunStatus, string> = {
  running: 'bg-blue-900/40 text-blue-300',
  ready: 'bg-amber-900/40 text-amber-300',
  applied: 'bg-emerald-900/40 text-emerald-300',
  discarded: 'bg-gray-800 text-gray-400',
  failed: 'bg-red-900/40 text-red-300',
}

export function DetectionTab({ provider }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['sources', provider, 'runs'],
    queryFn: () => fetchSourceRuns(provider),
    // Часто хочется видеть свежий status — поллим раз в 3 секунды.
    refetchInterval: 3000,
  })

  return (
    <div className="space-y-4 max-w-5xl">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-100">Сухие прогоны</h2>
        <button
          type="button"
          disabled
          title="Запустить сухой прогон (UI в следующей итерации)"
          className="px-3 py-1.5 text-sm rounded-md bg-violet-700/50 text-violet-200 opacity-50 cursor-not-allowed"
        >
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
          Прогонов пока нет. Запустите первый — кнопка появится в следующей итерации.
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
              <th className="text-right font-normal">errors</th>
            </tr>
          </thead>
          <tbody className="text-gray-200">
            {data.runs.map(r => (
              <RunRow key={r.id} run={r} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function RunRow({ run }: { run: ScrapeRun }) {
  return (
    <tr className="border-t border-gray-800/60 hover:bg-gray-900/40">
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
      <td className="text-right tabular-nums text-red-400">
        {run.totals.errors ?? '—'}
      </td>
    </tr>
  )
}
