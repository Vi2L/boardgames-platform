import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import clsx from 'clsx'
import type { HttpLog } from '../../types/api'

interface Props {
  log: HttpLog
}

function statusColor(status?: number): string {
  if (!status) return 'text-gray-400'
  if (status < 300) return 'text-green-400'
  if (status < 400) return 'text-yellow-400'
  return 'text-red-400'
}

function formatSize(bytes?: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes}B`
  return `${(bytes / 1024).toFixed(1)}KB`
}

export function HttpLogEntry({ log }: Props) {
  const [open, setOpen] = useState(false)

  const label = log.type === 'request'
    ? `↑ ${log.method}`
    : `↓ ${log.status}`

  const detail = log.type === 'request'
    ? log.url
    : log.body_preview?.slice(0, 80)

  return (
    <div className="border border-gray-800 rounded bg-gray-900 text-xs overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-800/60 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <span className="text-gray-600 flex-shrink-0">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
        <span className={clsx('font-mono font-bold w-16 flex-shrink-0', log.type === 'request' ? 'text-blue-400' : statusColor(log.status))}>
          {label}
        </span>
        <span className="text-violet-400 font-medium px-1.5 py-0.5 bg-gray-800 rounded text-xs flex-shrink-0">
          {log.slug}
        </span>
        <span className="text-gray-400 truncate flex-1 font-mono">{detail}</span>
        <span className="text-gray-600 ml-auto flex-shrink-0 flex items-center gap-2">
          {log.elapsed_ms != null && <span>{log.elapsed_ms}ms</span>}
          {log.size_bytes != null && <span>{formatSize(log.size_bytes)}</span>}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 space-y-2 border-t border-gray-800">
          {Object.keys(log.headers).length > 0 && (
            <div>
              <div className="text-gray-500 mb-1 text-xs">Заголовки</div>
              <pre
                className="text-xs font-mono text-gray-300 bg-gray-950 p-2 rounded overflow-x-auto max-h-32 border border-gray-800"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {Object.entries(log.headers).map(([k, v]) => `${k}: ${v}`).join('\n')}
              </pre>
            </div>
          )}
          {log.body_preview && (
            <div>
              <div className="text-gray-500 mb-1 text-xs">Тело ответа (превью)</div>
              <pre
                className="text-xs font-mono text-gray-300 bg-gray-950 p-2 rounded overflow-x-auto max-h-48 border border-gray-800"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {log.body_preview}
              </pre>
            </div>
          )}
          {log.url && log.type === 'request' && (
            <div>
              <div className="text-gray-500 mb-1 text-xs">URL</div>
              <div className="text-violet-300 font-mono break-all bg-gray-950 p-2 rounded text-xs border border-gray-800">
                {log.url}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
