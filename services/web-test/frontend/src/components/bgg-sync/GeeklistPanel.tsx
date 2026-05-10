/**
 * GeeklistPanel — импорт и просмотр кураторских BGG GeekList'ов.
 *
 * Структура:
 *  - Сверху: форма «Запустить импорт GeekList по ID» (с подсказкой про
 *    BGG Top 50 Most Played — id типа 367126).
 *  - Список ранее импортированных GeekList'ов (карточки с meta).
 *  - Кликнул карточку → раскрывается snapshot (50–N позиций с обложками,
 *    рангом, флагом «в каталоге»).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Loader2, Play, ExternalLink, BookOpen, ChevronDown, ChevronRight,
} from 'lucide-react'
import clsx from 'clsx'

import {
  fetchGeeklists,
  fetchGeeklistSnapshot,
  importBggGeeklist,
  type GeeklistMeta,
  type GeeklistSnapshot,
} from '../../lib/bgg-sync'

export function GeeklistPanel() {
  const qc = useQueryClient()
  const [geeklistIdInput, setGeeklistIdInput] = useState('')
  const [autoImport, setAutoImport] = useState(true)

  const lists = useQuery({
    queryKey: ['bgg-sync', 'geeklists'],
    queryFn: fetchGeeklists,
  })

  const startImport = useMutation({
    mutationFn: () => importBggGeeklist({
      geeklist_id: parseInt(geeklistIdInput, 10),
      auto_import: autoImport,
    }),
    onSuccess: (job) => {
      toast.success(`Geeklist импорт запущен (job #${job.id})`)
      // После небольшой паузы инвалидируем — даём backend'у время выполнить.
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['bgg-sync', 'geeklists'] })
        qc.invalidateQueries({ queryKey: ['bgg-sync', 'jobs'] })
      }, 1500)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const idValid = /^\d+$/.test(geeklistIdInput)

  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-sm font-semibold text-gray-200 mb-1">
          Импорт BGG GeekList
        </h3>
        <p className="text-xs text-gray-500 mb-3">
          Snapshot кураторского списка по ID (например,{' '}
          <a
            href="https://boardgamegeek.com/geeklist/367126/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-violet-400 hover:underline"
          >
            BGG Top 50 Most Played — October 2025 (id=367126) ↗
          </a>
          ). Каждый месяц BGG публикует новый список с инкрементным id —
          добавляйте сюда чтобы автоматически обогатить новые игры в каталоге.
        </p>

        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
              GeekList ID
            </label>
            <input
              type="text"
              value={geeklistIdInput}
              onChange={e => setGeeklistIdInput(e.target.value.replace(/\D/g, ''))}
              placeholder="367126"
              className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-sm font-mono text-gray-200 focus:outline-none focus:border-violet-500"
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer pb-1.5">
            <input
              type="checkbox"
              checked={autoImport}
              onChange={e => setAutoImport(e.target.checked)}
            />
            auto-import новых
          </label>
          <button
            type="button"
            onClick={() => startImport.mutate()}
            disabled={!idValid || startImport.isPending}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white rounded mb-0.5"
          >
            {startImport.isPending
              ? <Loader2 size={11} className="animate-spin" />
              : <Play size={11} />}
            Запустить
          </button>
        </div>
      </section>

      <div className="border-t border-gray-800" />

      <section>
        <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-1.5">
          <BookOpen size={14} />
          Импортированные списки
        </h3>
        {lists.isLoading ? (
          <div className="text-xs text-gray-500 py-3 flex items-center gap-2">
            <Loader2 size={11} className="animate-spin" /> Загружаю…
          </div>
        ) : (lists.data ?? []).length === 0 ? (
          <div className="text-xs text-gray-500 py-6 text-center border border-dashed border-gray-800 rounded">
            Ещё ничего не импортировали. Введите ID GeekList'а выше и нажмите
            «Запустить».
          </div>
        ) : (
          <div className="space-y-2">
            {(lists.data ?? []).map(meta => <GeeklistCard key={meta.geeklist_id} meta={meta} />)}
          </div>
        )}
      </section>
    </div>
  )
}

// ── Geeklist card with collapsible items ─────────────────────────────────────

function GeeklistCard({ meta }: { meta: GeeklistMeta }) {
  const [open, setOpen] = useState(false)

  const snap = useQuery({
    queryKey: ['bgg-sync', 'geeklist-snapshot', meta.geeklist_id, meta.latest_snapshot_date],
    queryFn: () => fetchGeeklistSnapshot(meta.geeklist_id, meta.latest_snapshot_date),
    enabled: open,
  })

  return (
    <div className="border border-gray-800 rounded">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-gray-900/40 text-left"
      >
        <div className="text-gray-500">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-gray-100 truncate">
            {meta.title ?? `GeekList #${meta.geeklist_id}`}
          </div>
          <div className="text-[11px] text-gray-500">
            id={meta.geeklist_id} · {meta.item_count} позиций · последний снимок: {meta.latest_snapshot_date}
            {meta.username && <> · by {meta.username}</>}
          </div>
        </div>
        <a
          onClick={e => e.stopPropagation()}
          href={`https://boardgamegeek.com/geeklist/${meta.geeklist_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-gray-500 hover:text-violet-300"
          title="Открыть на BGG"
        >
          <ExternalLink size={12} />
        </a>
      </button>

      {open && (
        <div className="border-t border-gray-800 max-h-[600px] overflow-y-auto">
          {snap.isLoading && (
            <div className="px-3 py-3 text-xs text-gray-500 flex items-center gap-2">
              <Loader2 size={11} className="animate-spin" /> Загружаю позиции…
            </div>
          )}
          {snap.data && <GeeklistItems snapshot={snap.data} />}
        </div>
      )}
    </div>
  )
}

function GeeklistItems({ snapshot }: { snapshot: GeeklistSnapshot }) {
  return (
    <div className="divide-y divide-gray-800/60">
      {snapshot.items.map(item => (
        <div key={item.bgg_id} className={clsx(
          'flex items-start gap-3 px-3 py-2 hover:bg-gray-900/40',
        )}>
          <div className="w-8 text-right text-violet-400 font-mono text-xs flex-shrink-0 pt-0.5">
            #{item.rank}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs text-gray-200">{item.name}</div>
            <div className="text-[10px] text-gray-500">
              bgg_id={item.bgg_id}
              {item.game_id && (
                <span className="ml-2 text-emerald-400">
                  ✓ в каталоге{item.game_title && `: ${item.game_title}`}
                </span>
              )}
            </div>
            {item.body && (
              <div className="text-[11px] text-gray-400 mt-1 line-clamp-3">
                {item.body}
              </div>
            )}
          </div>
          <a
            href={`https://boardgamegeek.com/boardgame/${item.bgg_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-500 hover:text-violet-300 flex-shrink-0 mt-0.5"
            title="Открыть на BGG"
          >
            <ExternalLink size={11} />
          </a>
        </div>
      ))}
    </div>
  )
}
