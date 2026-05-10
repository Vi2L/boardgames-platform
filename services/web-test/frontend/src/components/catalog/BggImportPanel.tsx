/**
 * BggImportPanel — UI для подсистемы `catalog/parsers/bgg/`.
 *
 * Две независимые секции:
 *
 *  1. **Search** — POST /catalog/parsers/bgg/search → список кандидатов из
 *     BGG XML API. Оператор кликает «Импорт» на конкретной игре —
 *     запускается одиночный /catalog/import/bgg (как в ImportWizard).
 *     Это удобнее чем ImportWizard, когда `bgg_id` неизвестен и нужен
 *     fuzzy-поиск по названию.
 *
 *  2. **Batch enrich** — POST /catalog/import/bgg/batch → массовое
 *     XML-обогащение топ-N или всех ranked-игр. Выводим прогресс из
 *     ImportJob.progress + последние строки log_lines с polling каждые
 *     1.5 сек, авто-стоп когда status='done'/'failed'.
 *
 * Принципы:
 *  - dry_run по умолчанию ВКЛ — UX «preview сначала», как в Promotion.
 *  - Все мутации через TanStack Query; invalidate ['catalog','games']
 *    после успешного enrich, чтобы таблица каталога подтянула обновления.
 *  - Search использует SuggestInput-стиль (debounced) — иначе на каждый
 *    keystroke шлём запрос к BGG.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CheckCircle2, ChevronRight, Loader2, Search, Download, Play, Upload, XCircle } from 'lucide-react'

import {
  searchBgg,
  importBgg,
  importBggBatch,
  importBggRanks,
  fetchImportJob,
  type BggSearchHit,
  type ImportJob,
} from '../../lib/catalog'

// ────────────────────────────────────────────────────────────────────────────

export function BggImportPanel() {
  return (
    <div className="space-y-6">
      <BggRanksImportSection />
      <div className="border-t border-gray-800" />
      <BggSearchSection />
      <div className="border-t border-gray-800" />
      <BggBatchSection />
    </div>
  )
}

// ─── Ranks CSV Seed (шаг 1: загрузка CSV → seed minimal game records) ────────

/**
 * BggRanksImportSection — UI-wizard вокруг import_bgg_ranks.py.
 *
 * Шаги:
 *  1. Пользователь скачивает BGG ranks CSV с boardgamegeek.com/data_dumps/bg_ranks
 *  2. Загружает файл через drag-and-drop / file picker
 *  3. Задаёт top-N фильтр и dry-run флаг
 *  4. Запускает job → прогресс-бар + лог с polling каждые 1.5 сек
 *  5. Получает результат: N игр проиндексировано, предлагаем обогатить через XML
 */
function BggRanksImportSection() {
  const qc = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [file, setFile] = useState<File | null>(null)
  const [topN, setTopN] = useState<number | ''>(500)
  const [dryRun, setDryRun] = useState(true)
  const [dragging, setDragging] = useState(false)
  const [activeJobId, setActiveJobId] = useState<number | null>(null)

  const startImport = useMutation({
    mutationFn: () => importBggRanks(file!, topN === '' ? null : topN, dryRun),
    onSuccess: (job) => {
      setActiveJobId(job.id)
      toast.success(`Job #${job.id} запущен (${dryRun ? 'dry-run' : 'real'})`)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const job = useQuery({
    queryKey: ['catalog', 'import-job', activeJobId],
    queryFn: () => fetchImportJob(activeJobId!),
    enabled: activeJobId !== null,
    refetchInterval: (q) => {
      const data = q.state.data as ImportJob | undefined
      if (!data) return 1500
      return data.status === 'done' || data.status === 'failed' ? false : 1500
    },
  })

  // Инвалидируем игры после реального (не dry-run) завершения.
  useEffect(() => {
    if (job.data?.status === 'done' && !dryRun) {
      qc.invalidateQueries({ queryKey: ['catalog', 'games'] })
    }
  }, [job.data?.status, dryRun, qc])

  const isRunning = job.data?.status === 'running' || job.data?.status === 'pending'
  const isDone = job.data?.status === 'done'
  const isFailed = job.data?.status === 'failed'
  const progress = job.data?.progress
  const enrichedCount = (job.data?.result as Record<string, number> | null)?.enriched ?? 0

  function handleFileDrop(files: FileList | null) {
    if (!files || files.length === 0) return
    const f = files[0]
    if (!f.name.endsWith('.csv') && f.type !== 'text/csv') {
      toast.error('Ожидается CSV-файл (.csv)')
      return
    }
    setFile(f)
    setActiveJobId(null)
  }

  const canRun = file !== null && !startImport.isPending && !isRunning

  return (
    <section>
      <div className="flex items-center gap-2 mb-1">
        <h2 className="text-sm font-semibold text-gray-200">Seed каталога из BGG ranks CSV</h2>
        {/* Wizard step pills */}
        <div className="flex items-center gap-1 ml-auto text-[10px] text-gray-500">
          <span className={file ? 'text-violet-400' : ''}>① CSV</span>
          <ChevronRight size={10} />
          <span className={activeJobId ? 'text-violet-400' : ''}>② Import</span>
          <ChevronRight size={10} />
          <span className={isDone && !dryRun ? 'text-green-400' : ''}>③ Enrich ↓</span>
        </div>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Создаёт minimal game records (title, year, rank) без XML-данных.
        После seed — запустите «Batch-обогащение» ниже для полного заполнения.{' '}
        <a
          href="https://boardgamegeek.com/data_dumps/bg_ranks"
          target="_blank"
          rel="noopener noreferrer"
          className="text-violet-400 hover:underline"
        >
          Скачать CSV ↗
        </a>
      </p>

      {/* Drop zone */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={e => e.key === 'Enter' && fileInputRef.current?.click()}
        onDragEnter={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={e => { e.preventDefault(); setDragging(false) }}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); setDragging(false); handleFileDrop(e.dataTransfer.files) }}
        className={[
          'border-2 border-dashed rounded-lg px-4 py-5 text-center cursor-pointer transition-colors',
          dragging ? 'border-violet-500 bg-violet-950/20' : 'border-gray-700 hover:border-gray-600',
          file ? 'border-violet-700 bg-violet-950/10' : '',
        ].join(' ')}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={e => handleFileDrop(e.target.files)}
        />
        {file ? (
          <div className="flex items-center justify-center gap-2 text-sm text-violet-300">
            <CheckCircle2 size={16} className="text-violet-400 flex-shrink-0" />
            <span className="truncate max-w-xs">{file.name}</span>
            <span className="text-gray-500 text-xs flex-shrink-0">
              ({(file.size / 1024 / 1024).toFixed(1)} MB)
            </span>
            <button
              type="button"
              onClick={e => { e.stopPropagation(); setFile(null); setActiveJobId(null) }}
              className="ml-1 text-gray-500 hover:text-gray-300"
            >
              <XCircle size={14} />
            </button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1 text-gray-500">
            <Upload size={20} />
            <span className="text-xs">Перетащите boardgames_ranks.csv или кликните</span>
          </div>
        )}
      </div>

      {/* Options */}
      <div className="grid grid-cols-2 gap-3 mt-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Top-N по rank{' '}
            <span className="text-gray-600">(пусто = все ~160K)</span>
          </label>
          <input
            type="number"
            min={1}
            max={200000}
            value={topN}
            onChange={e => setTopN(e.target.value === '' ? '' : Math.max(1, parseInt(e.target.value) || 1))}
            placeholder="например, 500"
            className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-500"
          />
        </div>
        <div className="flex items-end">
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={e => setDryRun(e.target.checked)}
            />
            Dry-run (подсчёт без записи)
          </label>
        </div>
      </div>

      {/* Run button */}
      <div className="flex items-center gap-3 mt-3">
        <button
          type="button"
          onClick={() => startImport.mutate()}
          disabled={!canRun}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white rounded"
        >
          {startImport.isPending || isRunning
            ? <Loader2 size={12} className="animate-spin" />
            : <Play size={12} />}
          {dryRun ? 'Dry-run' : 'Импортировать'}
        </button>
        {activeJobId && (
          <span className="text-xs text-gray-500">
            Job #{activeJobId} · {job.data?.status ?? '...'}
          </span>
        )}
      </div>

      {/* Progress */}
      {progress && (
        <div className="mt-4 space-y-1.5">
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>
              <span className="text-violet-300">{progress.phase}</span>
              {progress.total > 0 && (
                <> · {progress.current} / {progress.total}</>
              )}
            </span>
          </div>
          {progress.total > 0 && (
            <div className="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
              <div
                className="bg-violet-500 h-full transition-all"
                style={{ width: `${Math.min(100, (progress.current / progress.total) * 100)}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Result */}
      {job.data && (isDone || isFailed) && (
        <div className={[
          'mt-3 p-3 rounded text-xs border',
          isDone ? 'bg-gray-900 border-gray-800 text-gray-300' : 'bg-red-950/20 border-red-900/50 text-red-300',
        ].join(' ')}>
          <div className="font-medium mb-1">
            {isDone ? (dryRun ? '✓ Dry-run завершён' : '✓ Импорт завершён') : '✗ Ошибка'}
          </div>
          {isDone && (
            <div className="flex gap-6 mt-1">
              <Stat label={dryRun ? 'Будет импортировано' : 'Импортировано'} value={enrichedCount} />
            </div>
          )}
          {isFailed && job.data.error && (
            <div className="mt-1 font-mono text-[11px] text-red-400 break-all">{job.data.error}</div>
          )}
          {isDone && !dryRun && enrichedCount > 0 && (
            <div className="mt-2 text-gray-500 text-[11px]">
              Игры проиндексированы. Перейдите к «Batch-обогащению» ниже чтобы заполнить описания через BGG XML API.
            </div>
          )}
        </div>
      )}

      {/* Log */}
      {job.data?.log_lines && job.data.log_lines.length > 0 && (
        <details className="mt-3 group">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-200">
            Лог ({job.data.log_lines.length} строк)
          </summary>
          <pre className="mt-2 max-h-48 overflow-y-auto text-[11px] font-mono text-gray-400 bg-gray-950 p-2 rounded border border-gray-800 whitespace-pre-wrap">
            {job.data.log_lines.slice(-50).join('\n')}
          </pre>
        </details>
      )}
    </section>
  )
}

// ─── Search ─────────────────────────────────────────────────────────────────

const SEARCH_DEBOUNCE_MS = 350

function BggSearchSection() {
  const qc = useQueryClient()
  const [query, setQuery] = useState('')
  const [exact, setExact] = useState(false)
  const [debouncedQuery, setDebouncedQuery] = useState('')

  // Debounce — иначе каждый keystroke = HTTP к BGG.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [query])

  const search = useQuery({
    queryKey: ['catalog', 'bgg-search', debouncedQuery, exact],
    queryFn: () => searchBgg(debouncedQuery, { exact, limit: 50 }),
    enabled: debouncedQuery.length >= 2, // 1 буква — слишком много шума.
    retry: 0,
    staleTime: 60_000,
  })

  const importOne = useMutation({
    mutationFn: (bggId: number) => importBgg({ bgg_id: bggId }),
    onSuccess: (job, bggId) => {
      toast.success(`Импорт bgg_id=${bggId} запущен (job #${job.id})`)
      qc.invalidateQueries({ queryKey: ['catalog', 'games'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <section>
      <h2 className="text-sm font-semibold text-gray-200 mb-2">
        Поиск в BGG XML API
      </h2>
      <p className="text-xs text-gray-500 mb-3">
        Без побочных эффектов в БД. Кликните «Импорт» — запустится фоновый
        <code className="mx-1 text-gray-400">/import/bgg</code>, заполнит
        canonical-Game и satellite через XML API.
      </p>

      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="например, Carcassonne или Каркассон"
            className="w-full pl-9 pr-3 py-2 bg-gray-900 border border-gray-700 rounded text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-violet-500"
          />
        </div>
        <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={exact}
            onChange={e => setExact(e.target.checked)}
          />
          точное совпадение
        </label>
      </div>

      <div className="border border-gray-800 rounded overflow-hidden">
        {!debouncedQuery && (
          <div className="px-4 py-6 text-center text-xs text-gray-500">
            Введите хотя бы 2 символа.
          </div>
        )}
        {debouncedQuery && search.isLoading && (
          <div className="px-4 py-6 text-center text-xs text-gray-500 flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Поиск…
          </div>
        )}
        {search.isError && (
          <div className="px-4 py-3 text-xs text-red-400">
            Ошибка: {(search.error as Error).message}
          </div>
        )}
        {search.data && search.data.count === 0 && (
          <div className="px-4 py-6 text-center text-xs text-gray-500">
            Ничего не найдено в BGG.
          </div>
        )}
        {search.data && search.data.count > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-900 border-b border-gray-800 text-xs text-gray-400">
              <tr>
                <th className="text-left px-3 py-2 font-normal">bgg_id</th>
                <th className="text-left px-3 py-2 font-normal">Title</th>
                <th className="text-left px-3 py-2 font-normal">Year</th>
                <th className="text-right px-3 py-2 font-normal">Действия</th>
              </tr>
            </thead>
            <tbody>
              {search.data.items.map((hit: BggSearchHit) => (
                <tr key={hit.bgg_id} className="border-b border-gray-800 last:border-b-0 hover:bg-gray-900/40">
                  <td className="px-3 py-2 font-mono text-xs text-gray-400">
                    <a
                      href={`https://boardgamegeek.com/boardgame/${hit.bgg_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:text-violet-300"
                    >
                      {hit.bgg_id}
                    </a>
                  </td>
                  <td className="px-3 py-2 text-gray-200">{hit.title}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs">{hit.year ?? '—'}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => importOne.mutate(hit.bgg_id)}
                      disabled={importOne.isPending && importOne.variables === hit.bgg_id}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white rounded"
                    >
                      {importOne.isPending && importOne.variables === hit.bgg_id
                        ? <Loader2 size={11} className="animate-spin" />
                        : <Download size={11} />}
                      Импорт
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {search.data && (
        <div className="text-xs text-gray-500 mt-2">
          Найдено: {search.data.count} {search.data.count > search.data.items.length && '(показаны первые 50)'}
        </div>
      )}
    </section>
  )
}

// ─── Batch enrich ───────────────────────────────────────────────────────────

function BggBatchSection() {
  const qc = useQueryClient()
  const [scope, setScope] = useState<'rank_le' | 'all_ranked'>('rank_le')
  const [rankLe, setRankLe] = useState(100)
  const [batchSize, setBatchSize] = useState(20)
  const [skipRecentDays, setSkipRecentDays] = useState(30)
  const [dryRun, setDryRun] = useState(true)
  const [activeJobId, setActiveJobId] = useState<number | null>(null)

  const startBatch = useMutation({
    mutationFn: () =>
      importBggBatch({
        ...(scope === 'rank_le' ? { rank_le: rankLe } : { all_ranked: true }),
        batch_size: batchSize,
        skip_recent_days: skipRecentDays,
        dry_run: dryRun,
      }),
    onSuccess: (job) => {
      setActiveJobId(job.id)
      toast.success(`Job #${job.id} запущен (${dryRun ? 'dry-run' : 'real'})`)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  // Polling job'а: 1.5 сек когда running/pending; авто-стоп при done/failed.
  // Cache invalidation на done — таблица каталога подтянет обогащённые описания.
  const job = useQuery({
    queryKey: ['catalog', 'import-job', activeJobId],
    queryFn: () => fetchImportJob(activeJobId!),
    enabled: activeJobId !== null,
    refetchInterval: (q) => {
      const data = q.state.data as ImportJob | undefined
      if (!data) return 1500
      return data.status === 'done' || data.status === 'failed' ? false : 1500
    },
  })

  // На завершение job'а инвалидируем игры — UI каталога подхватит описания.
  useEffect(() => {
    if (job.data?.status === 'done' && !dryRun) {
      qc.invalidateQueries({ queryKey: ['catalog', 'games'] })
    }
  }, [job.data?.status, dryRun, qc])

  const isRunning = job.data?.status === 'running' || job.data?.status === 'pending'
  const progress = job.data?.progress

  return (
    <section>
      <h2 className="text-sm font-semibold text-gray-200 mb-2">
        Batch-обогащение через BGG XML
      </h2>
      <p className="text-xs text-gray-500 mb-3">
        Заполняет описания, дизайнеров, механики, обложки для уже-проиндексированных
        игр (`game_bgg.rank IS NOT NULL`). Resume через `fetched_at` — повторный
        прогон со <code className="text-gray-400">skip_recent_days&gt;0</code>
        пропускает недавно обогащённые. На полный seed (~30K игр) — ~25 минут.
      </p>

      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Охват</label>
          <div className="flex items-center gap-2">
            <select
              value={scope}
              onChange={e => setScope(e.target.value as 'rank_le' | 'all_ranked')}
              className="flex-shrink-0 px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-violet-500"
            >
              <option value="rank_le">Топ-N по rank</option>
              <option value="all_ranked">Все ranked игры</option>
            </select>
            {scope === 'rank_le' && (
              <input
                type="number"
                min={1}
                max={100000}
                value={rankLe}
                onChange={e => setRankLe(Math.max(1, parseInt(e.target.value) || 1))}
                className="flex-1 px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-violet-500"
              />
            )}
          </div>
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Skip recent days
            <span className="text-gray-600 ml-1">(0 = форсировать)</span>
          </label>
          <input
            type="number"
            min={0}
            value={skipRecentDays}
            onChange={e => setSkipRecentDays(Math.max(0, parseInt(e.target.value) || 0))}
            className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-violet-500"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Batch size <span className="text-gray-600 ml-1">(1..20)</span>
          </label>
          <input
            type="number"
            min={1}
            max={20}
            value={batchSize}
            onChange={e => setBatchSize(Math.min(20, Math.max(1, parseInt(e.target.value) || 1)))}
            className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-violet-500"
          />
        </div>

        <div className="flex items-end">
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={e => setDryRun(e.target.checked)}
            />
            Dry-run (без записи в БД)
          </label>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => startBatch.mutate()}
          disabled={startBatch.isPending || isRunning}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white rounded"
        >
          {startBatch.isPending || isRunning
            ? <Loader2 size={12} className="animate-spin" />
            : <Play size={12} />}
          {dryRun ? 'Dry-run' : 'Запустить enrich'}
        </button>
        {activeJobId && (
          <span className="text-xs text-gray-500">
            Job #{activeJobId} · {job.data?.status ?? '...'}
          </span>
        )}
      </div>

      {/* Прогресс */}
      {progress && (
        <div className="mt-4 space-y-1.5">
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>
              <span className="text-violet-300">{progress.phase}</span>
              {progress.total > 0 && (
                <> · {progress.current} / {progress.total}</>
              )}
            </span>
            {progress.current_title && (
              <span className="text-gray-500 truncate ml-3">{progress.current_title}</span>
            )}
          </div>
          {progress.total > 0 && (
            <div className="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
              <div
                className="bg-violet-500 h-full transition-all"
                style={{ width: `${Math.min(100, (progress.current / progress.total) * 100)}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Финальный результат */}
      {job.data?.result && (
        <div className="mt-3 p-3 bg-gray-900 border border-gray-800 rounded text-xs text-gray-300">
          <div className="font-medium mb-1">
            {job.data.status === 'done' ? '✓ Завершено' : '✗ Ошибка'}
          </div>
          <div className="grid grid-cols-3 gap-3 mt-2">
            <Stat label="Обогащено" value={(job.data.result as Record<string, number>).enriched ?? 0} />
            <Stat label="Пропущено" value={(job.data.result as Record<string, number>).skipped ?? 0} />
            <Stat label="Ошибки" value={(job.data.result as Record<string, number>).failed ?? 0} className={
              ((job.data.result as Record<string, number>).failed ?? 0) > 0 ? 'text-red-300' : ''
            } />
          </div>
        </div>
      )}

      {/* Ring-buffer last 200 строк лога */}
      {job.data?.log_lines && job.data.log_lines.length > 0 && (
        <details className="mt-3 group">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-200">
            Лог ({job.data.log_lines.length} строк)
          </summary>
          <pre className="mt-2 max-h-60 overflow-y-auto text-[11px] font-mono text-gray-400 bg-gray-950 p-2 rounded border border-gray-800 whitespace-pre-wrap">
            {job.data.log_lines.slice(-50).join('\n')}
          </pre>
        </details>
      )}
    </section>
  )
}

function Stat({ label, value, className = '' }: { label: string; value: number; className?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`text-lg font-mono ${className || 'text-gray-100'}`}>{value}</div>
    </div>
  )
}
