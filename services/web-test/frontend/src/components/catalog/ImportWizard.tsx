/**
 * ImportWizard — модал импорта из BGG / Tesera / Dicefest с polling job-status.
 *
 * Поток:
 *  1) Пользователь выбирает источник + параметры (ID для BGG/Tesera; для Dicefest —
 *     пробный прогон / фильтр года; запускается обходом сайта целиком).
 *  2) POST /api/catalog/import/{bgg,tesera,dicefest} → возвращает ImportJob (pending).
 *  3) Polling GET /api/catalog/import/jobs/{id} каждые 1.5s до status=done|failed.
 *  4) При done/failed показываем результат: imported[] и errors[].
 *  5) Для long-running (dicefest, ~15 мин на 900 игр) показываем progress-bar
 *     по progress.current/total + tail последних log_lines.
 *
 * batch-режим — multi-line input (по строке на ID) для BGG/Tesera.
 * Dicefest — single-action: парсер сам собирает все slug'и из листингов.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  X, Loader2, CheckCircle2, AlertTriangle, Download, Plus,
} from 'lucide-react'
import clsx from 'clsx'
import {
  importBgg, importTesera, importDicefest, fetchImportJob,
  type ImportJob, type ImportJobStatus,
} from '../../lib/catalog'

interface Props {
  onClose: () => void
}

type Source = 'bgg' | 'tesera' | 'dicefest'

export function ImportWizard({ onClose }: Props) {
  const [source, setSource] = useState<Source>('bgg')
  const [input, setInput] = useState('')
  // Dicefest-специфичные настройки. Не выносим в отдельный компонент пока,
  // чтобы не плодить файлов — пара полей.
  const [dicefestTrial, setDicefestTrial] = useState(true)         // [✓] пробный прогон
  const [dicefestOnlyYear, setDicefestOnlyYear] = useState<string>('') // '' | '2024' | ...
  const [jobId, setJobId] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const start = useMutation({
    mutationFn: async () => {
      if (source === 'bgg') {
        const tokens = input.split(/[\s,;\n]+/).filter(Boolean)
        if (tokens.length === 0) throw new Error('Пустой ввод')
        const ids = tokens.map(t => parseInt(t, 10))
        if (ids.some(n => Number.isNaN(n))) throw new Error('BGG требует числовые ID')
        return importBgg({ ids })
      } else if (source === 'tesera') {
        const tokens = input.split(/[\s,;\n]+/).filter(Boolean)
        if (tokens.length === 0) throw new Error('Пустой ввод')
        const items: (string | number)[] = tokens.map(t => {
          const n = Number(t)
          return Number.isFinite(n) && /^\d+$/.test(t) ? n : t
        })
        return importTesera({ items })
      } else {
        // Dicefest: input игнорируется, парсер сам собирает все slug'и.
        const payload: { max_items?: number; only_year?: number } = {}
        if (dicefestTrial) payload.max_items = 10
        if (dicefestOnlyYear) payload.only_year = parseInt(dicefestOnlyYear, 10)
        return importDicefest(payload)
      }
    },
    onSuccess: (job) => { setJobId(job.id); toast.success(`Job #${job.id} запущен`) },
    onError: (e) => toast.error(`Не удалось запустить: ${e}`),
  })

  // Polling: refetchInterval, но останавливаем когда status final.
  const job = useQuery({
    queryKey: ['catalog', 'import-job', jobId],
    queryFn: () => fetchImportJob(jobId!),
    enabled: jobId !== null,
    refetchInterval: (q) => {
      const data = q.state.data as ImportJob | undefined
      if (!data) return 1500
      return data.status === 'done' || data.status === 'failed' ? false : 1500
    },
  })

  // Когда импорт успешен — инвалидируем listing игр.
  const isFinal = job.data?.status === 'done' || job.data?.status === 'failed'
  if (isFinal && job.data?.status === 'done') {
    queryClient.invalidateQueries({ queryKey: ['catalog', 'games'] })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-gray-900 border border-gray-800 rounded-lg shadow-2xl w-[min(640px,100%)] max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <h2 className="text-sm font-semibold text-gray-100">Импорт из внешнего каталога</h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Source picker */}
          <div className="flex gap-1 border-b border-gray-800">
            {(['bgg', 'tesera', 'dicefest'] as Source[]).map(s => (
              <button
                key={s}
                type="button"
                onClick={() => { setSource(s); setJobId(null); setInput('') }}
                className={clsx(
                  'px-3 py-2 text-sm transition-colors border-b-2 -mb-px',
                  source === s
                    ? 'text-violet-300 border-violet-500'
                    : 'text-gray-400 border-transparent hover:text-gray-200',
                )}
              >
                {s === 'bgg' ? 'BoardGameGeek' : s === 'tesera' ? 'Tesera' : 'Dicefest'}
              </button>
            ))}
          </div>

          {/* Input */}
          {!jobId && source !== 'dicefest' && (
            <>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">
                  {source === 'bgg'
                    ? 'BGG ID (одно число или несколько через пробел/запятую/перенос)'
                    : 'Tesera alias или ID (можно несколько; alias — slug страницы)'}
                </label>
                <textarea
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  placeholder={source === 'bgg' ? '174430\n167791, 192291' : 'pandemic\nktulhu_pochti\n12345'}
                  rows={4}
                  className="w-full px-3 py-2 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100 placeholder-gray-500 font-mono focus:outline-none focus:border-violet-500"
                />
              </div>
              <button
                type="button"
                onClick={() => start.mutate()}
                disabled={!input.trim() || start.isPending}
                className="w-full px-4 py-2 rounded text-sm font-medium flex items-center justify-center gap-2 bg-violet-700 hover:bg-violet-600 disabled:opacity-40 disabled:cursor-not-allowed text-white"
              >
                {start.isPending
                  ? <><Loader2 size={13} className="animate-spin" /> Создаю задачу…</>
                  : <><Download size={13} /> Запустить импорт</>}
              </button>
            </>
          )}

          {!jobId && source === 'dicefest' && (
            <>
              <div className="text-xs text-gray-400 leading-relaxed">
                Парсер обходит каталог dicefest.ru (~900 игр на 3 года), пишет
                в staging-таблицу <code className="text-violet-300">dicefest_raw_games</code>.
                Основная БД <b>не</b> трогается — перенос в canonical games будет отдельным
                управляемым процессом (промоушен с матчингом).
                <br/>
                Полный прогон ~15 минут (rate-limit 1 req/sec).
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={dicefestTrial}
                  onChange={e => setDicefestTrial(e.target.checked)}
                  className="accent-violet-500"
                />
                Пробный прогон (только первые 10 slug'ов)
              </label>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">
                  Фильтр года (опционально)
                </label>
                <select
                  value={dicefestOnlyYear}
                  onChange={e => setDicefestOnlyYear(e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100 focus:outline-none focus:border-violet-500"
                >
                  <option value="">Все годы (2024 + 2025 + 2026)</option>
                  <option value="2024">только 2024</option>
                  <option value="2025">только 2025</option>
                  <option value="2026">только 2026</option>
                </select>
              </div>
              <button
                type="button"
                onClick={() => start.mutate()}
                disabled={start.isPending}
                className="w-full px-4 py-2 rounded text-sm font-medium flex items-center justify-center gap-2 bg-violet-700 hover:bg-violet-600 disabled:opacity-40 disabled:cursor-not-allowed text-white"
              >
                {start.isPending
                  ? <><Loader2 size={13} className="animate-spin" /> Создаю задачу…</>
                  : <><Download size={13} /> Запустить парсер dicefest</>}
              </button>
            </>
          )}

          {/* Progress */}
          {jobId && job.data && (
            <JobProgress
              job={job.data}
              onReset={() => { setJobId(null); setInput('') }}
              onClose={onClose}
            />
          )}

          {!jobId && (
            <div className="text-xs text-gray-500 leading-relaxed border-t border-gray-800 pt-3">
              <div className="font-medium text-gray-400 mb-1">Подсказки</div>
              <ul className="space-y-1 list-disc list-inside">
                <li>BGG ID — число из URL: boardgamegeek.com/boardgame/<b>174430</b>/gloomhaven.</li>
                <li>Tesera alias — slug из URL: tesera.ru/game/<b>pandemic</b>/.</li>
                <li>Импорт идемпотентен: повторный запуск перезапишет/обновит запись.</li>
                <li>BGG-импорт также добавит alternate names как алиасы (source=bgg).</li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function JobProgress({
  job, onReset, onClose,
}: {
  job: ImportJob
  onReset: () => void
  onClose: () => void
}) {
  const isFinal = job.status === 'done' || job.status === 'failed'
  const imported = job.result?.imported ?? []
  const errors = job.result?.errors ?? []
  const progress = job.progress
  const logLines = job.log_lines ?? []
  const pct = progress && progress.total > 0
    ? Math.min(100, Math.round((progress.current / progress.total) * 100))
    : 0

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <StatusBadge status={job.status} />
        <span className="text-xs font-mono text-gray-500">
          {job.type} · job #{job.id}
        </span>
        {!isFinal && <Loader2 size={12} className="animate-spin text-violet-400" />}
      </div>

      {/* Progress bar (показываем для job'ов с progress — пока только dicefest,
          но контракт universal). */}
      {progress && progress.total > 0 && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span className="font-mono">
              {progress.phase} · {progress.current}/{progress.total} ({pct}%)
            </span>
            {progress.current_title && (
              <span className="text-gray-500 truncate ml-2 max-w-[60%]" title={progress.current_title}>
                {progress.current_title}
              </span>
            )}
          </div>
          <div className="h-1.5 bg-gray-800 rounded overflow-hidden">
            <div
              className="h-full bg-violet-500 transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      {/* Live tail последних строк лога. Auto-scroll вниз. */}
      {logLines.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 mb-1">Лог (последние {logLines.length})</div>
          <pre
            ref={el => { if (el) el.scrollTop = el.scrollHeight }}
            className="bg-gray-950 rounded p-2 max-h-48 overflow-y-auto text-[11px] font-mono text-gray-400 whitespace-pre-wrap break-all"
          >
            {logLines.join('\n')}
          </pre>
        </div>
      )}

      {job.error && (
        <div className="bg-red-950/40 border border-red-900/50 rounded p-2 text-xs text-red-300">
          <div className="font-medium text-red-200">Job error</div>
          <div className="font-mono mt-0.5">{job.error}</div>
        </div>
      )}

      {imported.length > 0 && (
        <div>
          <div className="text-xs text-emerald-400 mb-1">
            Импортировано — {imported.length}
            {job.result?.skipped_fresh ? ` · пропущено как свежие — ${job.result.skipped_fresh}` : ''}
          </div>
          <div className="bg-gray-950 rounded p-2 space-y-1 max-h-40 overflow-y-auto">
            {imported.slice(0, 100).map((it, i) => (
              <div key={i} className="text-xs text-gray-300 flex items-center gap-2">
                <CheckCircle2 size={11} className="text-emerald-400 flex-shrink-0" />
                {it.game_id && (
                  <span className="font-mono text-gray-500 flex-shrink-0">#{it.game_id}</span>
                )}
                {it.slug && (
                  <span className="font-mono text-gray-600 flex-shrink-0 text-[10px]">{it.slug}</span>
                )}
                <span className="truncate">{it.title || it.title_ru}</span>
                {it.bgg_id && <span className="text-[10px] text-gray-500 font-mono">bgg#{it.bgg_id}</span>}
                {it.tesera_id && <span className="text-[10px] text-gray-500 font-mono">t#{it.tesera_id}</span>}
              </div>
            ))}
            {imported.length > 100 && (
              <div className="text-[10px] text-gray-500 italic">…и ещё {imported.length - 100} (см. в БД)</div>
            )}
          </div>
        </div>
      )}

      {errors.length > 0 && (
        <div>
          <div className="text-xs text-red-400 mb-1">Ошибки — {errors.length}</div>
          <div className="bg-red-950/30 rounded p-2 space-y-1 max-h-40 overflow-y-auto">
            {errors.map((e, i) => (
              <div key={i} className="text-xs text-red-300 flex items-start gap-2">
                <AlertTriangle size={11} className="text-red-400 flex-shrink-0 mt-0.5" />
                <span className="font-mono text-gray-500 flex-shrink-0">
                  {e.bgg_id ?? e.item ?? e.slug}
                </span>
                <span className="font-mono">{e.error}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {isFinal && (
        <div className="flex gap-2 pt-2 border-t border-gray-800">
          <button
            type="button"
            onClick={onReset}
            className="flex-1 px-3 py-1.5 text-xs flex items-center justify-center gap-1 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded"
          >
            <Plus size={11} /> Импортировать ещё
          </button>
          <button
            type="button"
            onClick={onClose}
            className="flex-1 px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 text-white rounded"
          >
            Закрыть
          </button>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: ImportJobStatus }) {
  const map: Record<ImportJobStatus, { label: string; cls: string }> = {
    pending: { label: 'pending',  cls: 'bg-gray-800 text-gray-400' },
    running: { label: 'running',  cls: 'bg-violet-900/50 text-violet-300' },
    done:    { label: 'done',     cls: 'bg-emerald-900/50 text-emerald-300' },
    failed:  { label: 'failed',   cls: 'bg-red-900/50 text-red-300' },
  }
  const m = map[status]
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-mono uppercase ${m.cls}`}>
      {m.label}
    </span>
  )
}
