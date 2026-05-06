import { useState } from 'react'
import { Play, Square, CheckCircle2, XCircle } from 'lucide-react'
import clsx from 'clsx'
import type { HttpLog, ParserStatsOut } from '../../types/api'
import { HttpLogEntry } from './HttpLogEntry'
import { useSSE } from '../../lib/sse'

interface Props {
  parser: ParserStatsOut
}

let localLogId = 0

const STORE_LABELS: Record<string, string> = {
  hobbygames: 'HobbyGames.ru',
  lavkaigr:   'lavkaigr.ru',
  gaga:       'gaga.ru',
}

const STORE_COLORS: Record<string, string> = {
  hobbygames: 'bg-blue-900/40 border-blue-800',
  lavkaigr:   'bg-green-900/40 border-green-800',
  gaga:       'bg-orange-900/40 border-orange-800',
}

export function ParserCard({ parser }: Props) {
  const [runQuery, setRunQuery] = useState('')
  const [sseUrl, setSseUrl] = useState<string | null>(null)
  const [logs, setLogs] = useState<HttpLog[]>([])
  const [resultInfo, setResultInfo] = useState<{ count: number; ms: number; error?: string } | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const handleEvent = (event: string, data: unknown) => {
    // Для ParserCard мы используем api-request/api-response события (не http-request/response)
    // т.к. parsers_web_test делает один HTTP-запрос к parsers API
    const d = data as Record<string, unknown>

    if (event === 'api-request') {
      setLogs(prev => [...prev, {
        id: ++localLogId,
        slug: parser.slug,
        type: 'request',
        method: 'GET',
        url: `${d.url as string}?q=${d.q}&stores=${parser.slug}&refresh=true`,
        headers: {},
        timestamp: Date.now(),
      }])
    }

    if (event === 'api-response') {
      setLogs(prev => [...prev, {
        id: ++localLogId,
        slug: parser.slug,
        type: 'response',
        status: d.status as number,
        elapsed_ms: d.elapsed_ms as number,
        headers: { source: d.source as string },
        body_preview: `${d.products_count} products, source: ${d.source}`,
        timestamp: Date.now(),
      }])
    }

    if (event === 'store-done') {
      setResultInfo({
        count: d.count as number,
        ms: d.elapsed_ms as number,
        error: d.error as string | undefined,
      })
      setSseUrl(null)
      setIsRunning(false)
    }

    if (event === 'api-error') {
      setResultInfo({ count: 0, ms: d.elapsed_ms as number, error: d.error as string })
      setSseUrl(null)
      setIsRunning(false)
    }
  }

  useSSE(sseUrl, handleEvent)

  const run = () => {
    if (!runQuery.trim()) return
    setLogs([])
    setResultInfo(null)
    setIsRunning(true)
    setSseUrl(`/api/parsers/${parser.slug}/run?q=${encodeURIComponent(runQuery.trim())}&limit=10`)
  }

  const stop = () => {
    setSseUrl(null)
    setIsRunning(false)
  }

  return (
    <div className={clsx(
      'bg-gray-900 border rounded-lg p-4 space-y-3',
      STORE_COLORS[parser.slug] ?? 'border-gray-800',
    )}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            {parser.available === true
              ? <CheckCircle2 size={14} className="text-green-400" />
              : <XCircle size={14} className="text-red-400" />
            }
            <span className="font-semibold text-gray-100">{parser.name}</span>
          </div>
          <div className="text-xs text-gray-500 mt-0.5">{STORE_LABELS[parser.slug] ?? parser.base_url}</div>
        </div>
        <span className="text-xs font-mono text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">
          {parser.slug}
        </span>
      </div>

      {/* Run form */}
      <div className="flex gap-2">
        <input
          type="text"
          value={runQuery}
          onChange={e => setRunQuery(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { isRunning ? stop() : run() } }}
          placeholder="Запрос для теста…"
          className="flex-1 px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-violet-500"
          disabled={isRunning}
        />
        <button
          onClick={isRunning ? stop : run}
          className={clsx(
            'px-3 py-1.5 rounded text-xs font-medium flex items-center gap-1 transition-colors',
            isRunning
              ? 'bg-red-900 hover:bg-red-800 text-red-300'
              : 'bg-violet-700 hover:bg-violet-600 text-white',
          )}
        >
          {isRunning ? <><Square size={11} /> Стоп</> : <><Play size={11} /> Запуск</>}
        </button>
      </div>

      {/* Result */}
      {resultInfo && (
        <div className={clsx(
          'text-xs px-2.5 py-1.5 rounded border',
          resultInfo.error
            ? 'bg-red-950/50 text-red-400 border-red-900/50'
            : 'bg-green-950/50 text-green-400 border-green-900/50',
        )}>
          {resultInfo.error
            ? `Ошибка: ${resultInfo.error}`
            : `✓ ${resultInfo.count} результатов за ${resultInfo.ms}ms`}
        </div>
      )}

      {/* API Logs */}
      {logs.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-xs text-gray-500">API Log</div>
          <div className="max-h-48 overflow-y-auto space-y-1.5">
            {logs.map(l => <HttpLogEntry key={l.id} log={l} />)}
          </div>
        </div>
      )}
    </div>
  )
}
