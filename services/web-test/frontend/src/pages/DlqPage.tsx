/**
 * DlqPage — Dead-Letter Queue для отправки оффер'ов в catalog.
 *
 * При сетевой ошибке или 5xx со стороны catalog parsers больше не
 * теряет батч, а сохраняет его в SQLite-таблицу catalog_dlq. Здесь
 * админ видит зависшие записи и может одной кнопкой replay'нуть.
 *
 * Это инструмент восстановления после downtime catalog'а: запустил
 * parsers до того как поднялся catalog → данные стопятся в DLQ →
 * после старта catalog нажал «replay all».
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Loader2, RefreshCw, Trash2, Inbox, AlertTriangle, PlayCircle,
} from 'lucide-react'
import {
  fetchDlq, replayDlq, replayDlqAll, deleteDlq,
} from '../lib/api'

export function DlqPage() {
  const queryClient = useQueryClient()
  const [limit] = useState(100)

  const list = useQuery({
    queryKey: ['dlq', limit],
    queryFn: () => fetchDlq(limit, 0),
    refetchInterval: 30_000,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['dlq'] })

  const replayOne = useMutation({
    mutationFn: (id: number) => replayDlq(id),
    onSuccess: (r) => {
      if (r.status === 'ok') toast.success('Replay успешен, запись удалена из DLQ')
      else toast.error(`Replay неудачен: ${r.error ?? '?'}`)
      invalidate()
    },
    onError: (e) => toast.error(`${e}`),
  })
  const replayAll = useMutation({
    mutationFn: () => replayDlqAll(50),
    onSuccess: (r) => {
      toast.success(`Replay all: ✓ ${r.success}, ✗ ${r.failed} (всего ${r.replayed})`)
      invalidate()
    },
    onError: (e) => toast.error(`${e}`),
  })
  const remove = useMutation({
    mutationFn: (id: number) => deleteDlq(id),
    onSuccess: () => { toast.success('Запись удалена из DLQ'); invalidate() },
    onError: (e) => toast.error(`${e}`),
  })

  const items = list.data?.items ?? []
  const total = list.data?.total ?? 0

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-gray-100 flex items-center gap-2">
          <Inbox size={18} /> DLQ — catalog ingest
        </h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Зависшие батчи с парсеров, которые catalog не принял (downtime,
          5xx и т.п.). Replay переотправляет payload — при успехе запись
          удаляется из DLQ.
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <span className={total > 0 ? 'text-amber-400 text-sm' : 'text-emerald-400 text-sm'}>
          {total > 0 ? <><AlertTriangle size={12} className="inline mr-1" />{total} зависших батчей</>
                     : '✓ DLQ пуст'}
        </span>
        <button
          onClick={() => list.refetch()}
          className="ml-auto flex items-center gap-1 px-2 py-1 text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded"
        >
          <RefreshCw size={11} className={list.isFetching ? 'animate-spin' : ''} /> Обновить
        </button>
        {total > 0 && (
          <button
            onClick={() => {
              if (window.confirm(`Replay всех ${Math.min(total, 50)} зависших батчей?`))
                replayAll.mutate()
            }}
            disabled={replayAll.isPending}
            className="px-3 py-1 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white rounded flex items-center gap-1"
          >
            {replayAll.isPending ? <Loader2 size={11} className="animate-spin" /> : <PlayCircle size={11} />}
            Replay all
          </button>
        )}
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-950 text-gray-500 text-left">
            <tr>
              <th className="px-3 py-2">id</th>
              <th className="px-3 py-2">создано</th>
              <th className="px-3 py-2">последняя попытка</th>
              <th className="px-3 py-2 text-right">попыток</th>
              <th className="px-3 py-2 text-right">payload</th>
              <th className="px-3 py-2">last_error</th>
              <th className="px-3 py-2 text-right w-32">действия</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {items.map(it => (
              <tr key={it.id} className="hover:bg-gray-850">
                <td className="px-3 py-2 font-mono text-gray-500">{it.id}</td>
                <td className="px-3 py-2 font-mono text-gray-400 whitespace-nowrap">
                  {new Date(it.created_at).toLocaleString('ru-RU', { hour12: false })}
                </td>
                <td className="px-3 py-2 font-mono text-gray-500 whitespace-nowrap">
                  {new Date(it.last_attempt_at).toLocaleString('ru-RU', { hour12: false })}
                </td>
                <td className="px-3 py-2 text-right font-mono text-amber-400">
                  {it.attempt_count}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-500">
                  {(it.payload_size / 1024).toFixed(1)} KB
                </td>
                <td className="px-3 py-2 text-red-300 truncate max-w-md font-mono"
                    title={it.last_error ?? ''}>
                  {it.last_error ?? '—'}
                </td>
                <td className="px-3 py-2 text-right space-x-1">
                  <button
                    type="button"
                    onClick={() => replayOne.mutate(it.id)}
                    disabled={replayOne.isPending}
                    title="Replay этой записи"
                    className="p-1 text-violet-300 hover:text-violet-200 hover:bg-violet-950/40 rounded disabled:opacity-40"
                  >
                    <PlayCircle size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Удалить DLQ #${it.id} без попытки replay?`))
                        remove.mutate(it.id)
                    }}
                    disabled={remove.isPending}
                    title="Удалить запись (отказ от данных)"
                    className="p-1 text-gray-500 hover:text-red-400 hover:bg-red-950/40 rounded disabled:opacity-40"
                  >
                    <Trash2 size={12} />
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && !list.isLoading && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-emerald-400">
                ✓ Зависших батчей нет — все ingest'ы успешны.
              </td></tr>
            )}
            {list.isLoading && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-500">
                <Loader2 size={14} className="animate-spin inline" />
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
