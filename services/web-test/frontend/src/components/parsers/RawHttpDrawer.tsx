/**
 * Drawer для просмотра одного raw HTTP-snapshot'а.
 *
 * Backend (parsers) уже декодирует body по encoding (включая cp1251 у GaGa).
 * Здесь рендерим как plain text в pre с горизонтальным скроллом — html viewer
 * не обязателен, потому что часто магазины отдают JSON-LD или JSON, а HTML
 * всё равно проще читать с whitespace preservation.
 */
import { useQuery } from '@tanstack/react-query'
import { X, ExternalLink, Download, Loader2 } from 'lucide-react'
import { fetchRawSnapshot, rawSnapshotTextUrl } from '../../lib/api'
import { getStoreLabel, getStoreBadgeColor } from '../../lib/stores'

interface Props {
  snapshotId: number
  onClose: () => void
}

export function RawHttpDrawer({ snapshotId, onClose }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['raw-snapshot', snapshotId],
    queryFn: () => fetchRawSnapshot(snapshotId),
  })

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="ml-auto w-[min(900px,100vw)] h-full bg-gray-900 border-l border-gray-800 flex flex-col relative shadow-2xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-100">Raw HTTP snapshot</span>
            <span className="text-xs font-mono text-gray-500">#{snapshotId}</span>
          </div>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded">
            <X size={16} />
          </button>
        </div>

        {isLoading && (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            <Loader2 size={18} className="animate-spin" />
          </div>
        )}
        {isError && (
          <div className="p-4 text-sm text-red-400">{String(error)}</div>
        )}
        {data && (
          <div className="flex-1 overflow-hidden flex flex-col">
            {/* Meta */}
            <div className="p-4 space-y-2 border-b border-gray-800 flex-shrink-0">
              <div className="flex items-center gap-2">
                <span className={`px-1.5 py-0.5 rounded text-xs ${getStoreBadgeColor(data.store_slug)}`}>
                  {getStoreLabel(data.store_slug)}
                </span>
                <span className="text-xs font-mono text-gray-400">{data.method}</span>
                <StatusBadge status={data.status_code} />
                <span className="text-xs text-gray-500">{data.duration_ms} ms</span>
                <span className="text-xs text-gray-500">{(data.body_size ?? 0).toLocaleString()} B</span>
                {data.encoding && <span className="text-xs text-gray-500 font-mono">{data.encoding}</span>}
                {data.kind && <span className="text-xs text-gray-600 italic">kind: {data.kind}</span>}
              </div>
              {data.url && (
                <a href={data.url} target="_blank" rel="noreferrer"
                   className="flex items-center gap-1 text-xs text-indigo-300 hover:underline truncate"
                   title={data.url}>
                  <ExternalLink size={10} /> {data.url}
                </a>
              )}
              {data.query && (
                <div className="text-xs text-gray-500">query: <span className="text-gray-300 font-mono">{data.query}</span></div>
              )}
              {data.content_type && (
                <div className="text-xs text-gray-500">content-type: <span className="text-gray-300 font-mono">{data.content_type}</span></div>
              )}
              <div className="flex items-center gap-2 text-xs">
                <a
                  href={rawSnapshotTextUrl(snapshotId)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded"
                >
                  <Download size={11} /> Открыть raw
                </a>
                {data.truncated ? (
                  <span className="text-amber-400 italic">⚠ body усечён в БД</span>
                ) : null}
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-auto p-3 bg-gray-950">
              <pre className="text-xs text-gray-200 whitespace-pre-wrap break-all"
                   style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
                {data.body_text}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: number | null }) {
  if (status == null) return <span className="text-xs text-gray-500">—</span>
  const ok = status >= 200 && status < 300
  const cls = ok
    ? 'bg-emerald-900/50 text-emerald-300'
    : status >= 300 && status < 400
      ? 'bg-blue-900/50 text-blue-300'
      : 'bg-red-900/50 text-red-300'
  return <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${cls}`}>{status}</span>
}
