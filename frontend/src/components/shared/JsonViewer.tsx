import { useState } from 'react'
import { Copy, Check } from 'lucide-react'

interface Props {
  data: unknown
  maxHeight?: number
}

function highlight(json: string): string {
  return json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"(\w[\w\d_-]*)":/g, '<span class="json-key">"$1"</span>:')
    .replace(/: "([^"]*?)"/g, ': <span class="json-str">"$1"</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="json-num">$1</span>')
    .replace(/: (true|false|null)/g, ': <span class="json-bool">$1</span>')
}

export function JsonViewer({ data, maxHeight = 400 }: Props) {
  const [copied, setCopied] = useState(false)
  const json = JSON.stringify(data, null, 2)

  const copy = () => {
    navigator.clipboard.writeText(json).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="relative bg-gray-950 rounded border border-gray-800">
      <button
        onClick={copy}
        title="Copy JSON"
        className="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-300 hover:bg-gray-800 z-10"
      >
        {copied ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
      </button>
      <style>{`
        .json-key { color: #d1d5db; }
        .json-str { color: #4ade80; }
        .json-num { color: #facc15; }
        .json-bool { color: #60a5fa; }
      `}</style>
      <pre
        className="p-3 text-xs font-mono overflow-auto"
        style={{ maxHeight, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}
        dangerouslySetInnerHTML={{ __html: highlight(json) }}
      />
    </div>
  )
}
