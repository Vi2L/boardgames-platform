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
  Loader2, RefreshCw, Trash2, Inbox, AlertTriangle, PlayCircle, CheckCircle2,
} from 'lucide-react'
import {
  fetchDlq, replayDlq, replayDlqAll, deleteDlq,
} from '../lib/api'
import { Button, IconButton, Badge, EmptyState } from '../components/ui'
import { HelpBox } from '../components/shared/HelpBox'

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
      toast.success(`Replay all: успех ${r.success}, ошибок ${r.failed} (всего ${r.replayed})`)
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
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
          <Inbox size={18} /> DLQ — catalog ingest
          <HelpBox topic="dlq.what_is_dlq" iconSize={14} />
        </h1>
        <p className="text-xs text-zinc-500 mt-0.5">
          Зависшие батчи с парсеров, которые catalog не принял (downtime,
          5xx и т.п.). Replay переотправляет payload — при успехе запись
          удаляется из DLQ.
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {total > 0 ? (
          <Badge tone="danger" size="sm" dot={false}>
            <AlertTriangle size={11} /> {total} зависших
          </Badge>
        ) : (
          <Badge tone="ok" size="sm" dot={false}>
            <CheckCircle2 size={11} /> DLQ пуст
          </Badge>
        )}
        <Button
          variant="ghost"
          icon={RefreshCw}
          loading={list.isFetching}
          onClick={() => list.refetch()}
          className="ml-auto"
        >
          Обновить
        </Button>
        {total > 0 && (
          <Button
            variant="primary"
            icon={PlayCircle}
            loading={replayAll.isPending}
            onClick={() => {
              if (window.confirm(`Replay всех ${Math.min(total, 50)} зависших батчей?`))
                replayAll.mutate()
            }}
          >
            Replay all
          </Button>
        )}
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-zinc-950 text-zinc-500 text-left">
            <tr>
              <th className="px-3 py-2 font-normal">id</th>
              <th className="px-3 py-2 font-normal">создано</th>
              <th className="px-3 py-2 font-normal">последняя попытка</th>
              <th className="px-3 py-2 font-normal text-right">
                <span className="inline-flex items-center gap-1 justify-end">
                  попыток <HelpBox topic="dlq.attempt_count" />
                </span>
              </th>
              <th className="px-3 py-2 font-normal text-right">payload</th>
              <th className="px-3 py-2 font-normal">last_error</th>
              <th className="px-3 py-2 font-normal text-right w-32">
                <span className="inline-flex items-center gap-1 justify-end">
                  действия <HelpBox topic="dlq.replay_vs_delete" />
                </span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {items.map(it => (
              <tr key={it.id} className="hover:bg-zinc-800/40">
                <td className="px-3 py-2 font-mono text-zinc-500">{it.id}</td>
                <td className="px-3 py-2 font-mono text-zinc-400 whitespace-nowrap">
                  {new Date(it.created_at).toLocaleString('ru-RU', { hour12: false })}
                </td>
                <td className="px-3 py-2 font-mono text-zinc-500 whitespace-nowrap">
                  {new Date(it.last_attempt_at).toLocaleString('ru-RU', { hour12: false })}
                </td>
                <td className="px-3 py-2 text-right font-mono text-amber-400 tabular-nums">
                  {it.attempt_count}
                </td>
                <td className="px-3 py-2 text-right font-mono text-zinc-500 tabular-nums">
                  {(it.payload_size / 1024).toFixed(1)} KB
                </td>
                <td className="px-3 py-2 text-rose-300 truncate max-w-md font-mono"
                    title={it.last_error ?? ''}>
                  {it.last_error ?? '—'}
                </td>
                <td className="px-3 py-2 text-right">
                  <div className="inline-flex items-center gap-1">
                    <IconButton
                      icon={PlayCircle}
                      size="xs"
                      variant="ghost"
                      aria-label="Replay этой записи"
                      title="Replay этой записи"
                      disabled={replayOne.isPending}
                      onClick={() => replayOne.mutate(it.id)}
                    />
                    <IconButton
                      icon={Trash2}
                      size="xs"
                      variant="ghost"
                      aria-label="Удалить запись"
                      title="Удалить запись (отказ от данных)"
                      disabled={remove.isPending}
                      onClick={() => {
                        if (window.confirm(`Удалить DLQ #${it.id} без попытки replay?`))
                          remove.mutate(it.id)
                      }}
                    />
                  </div>
                </td>
              </tr>
            ))}
            {items.length === 0 && !list.isLoading && (
              <tr>
                <td colSpan={7} className="px-3 py-8">
                  <EmptyState
                    icon={CheckCircle2}
                    title="Зависших батчей нет"
                    description="Все ingest'ы успешны."
                  />
                </td>
              </tr>
            )}
            {list.isLoading && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-zinc-500">
                <Loader2 size={14} className="animate-spin inline" />
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
