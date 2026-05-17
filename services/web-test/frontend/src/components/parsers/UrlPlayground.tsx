/**
 * UrlPlayground — пробный GET по URL через тот же HTTP-стек, что у парсеров.
 *
 * Это намеренно НЕ парсер-по-URL: для извлечения структурированного товара
 * нужны магазинные селекторы, которые реализованы внутри каждого парсера.
 * Здесь — только raw материал: status, encoding, body. Достаточно чтобы:
 *  - проверить, отдаёт ли магазин 200;
 *  - увидеть финальный URL после редиректов;
 *  - проверить cp1251-декодинг на конкретной странице (gaga.ru);
 *  - вытянуть HTML и попробовать на нём CSS-селекторы прежде чем
 *    встраивать в парсер.
 */
import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Play, Loader2, AlertTriangle, ExternalLink, Copy, Check } from 'lucide-react'
import clsx from 'clsx'
import { debugFetchUrl } from '../../lib/api'
import type { DebugFetchUrlResult } from '../../types/api'

const ENCODING_HINTS = ['', 'utf-8', 'cp1251', 'windows-1252', 'iso-8859-1']

export function UrlPlayground() {
  const [url, setUrl] = useState('')
  const [encodingHint, setEncodingHint] = useState('')
  const [copied, setCopied] = useState(false)

  const mutation = useMutation<DebugFetchUrlResult, Error>({
    mutationFn: () => debugFetchUrl({ url: url.trim(), encoding_hint: encodingHint || undefined }),
  })

  const submit = () => { if (url.trim()) mutation.mutate() }

  const copyBody = () => {
    if (!mutation.data) return
    navigator.clipboard.writeText(mutation.data.body_text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="space-y-4">
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submit() }}
            placeholder="https://gaga.ru/product/..."
            className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500 font-mono"
            disabled={mutation.isPending}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!url.trim() || mutation.isPending}
            className="px-4 py-2 rounded text-sm font-medium flex items-center gap-1.5 bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 disabled:cursor-not-allowed text-white"
          >
            {mutation.isPending
              ? <><Loader2 size={13} className="animate-spin" /> GET…</>
              : <><Play size={13} /> Probe</>}
          </button>
        </div>

        <div className="flex items-center gap-3 text-xs">
          <span className="text-gray-500">Encoding hint:</span>
          {ENCODING_HINTS.map(h => (
            <button
              key={h || 'auto'}
              type="button"
              onClick={() => setEncodingHint(h)}
              className={clsx(
                'px-2 py-0.5 rounded font-mono',
                encodingHint === h
                  ? 'bg-indigo-900/60 text-indigo-200'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
              )}
            >
              {h || 'auto'}
            </button>
          ))}
        </div>

        <div className="text-xs text-gray-500">
          User-Agent и прокси берутся как у боевых парсеров (env <code className="bg-black/30 px-1 rounded">PROXY</code>).
          Body ограничен 200KB декодированного — длинные страницы усекаются.
        </div>
      </div>

      {mutation.isError && (
        <div className="bg-red-950/50 border border-red-900/50 rounded p-3 text-sm text-red-400 flex items-start gap-2">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <div>
            <div className="font-medium">Не удалось выполнить GET</div>
            <div className="text-xs text-red-300/80 mt-0.5">{String(mutation.error)}</div>
          </div>
        </div>
      )}

      {mutation.data && <ProbeResult result={mutation.data} onCopyBody={copyBody} copied={copied} />}
    </div>
  )
}

function ProbeResult({
  result, onCopyBody, copied,
}: {
  result: DebugFetchUrlResult
  onCopyBody: () => void
  copied: boolean
}) {
  const ok = result.status_code >= 200 && result.status_code < 300
  return (
    <div className="space-y-3">
      {/* Meta */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 space-y-2">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className={clsx('px-2 py-0.5 rounded font-mono',
            ok ? 'bg-emerald-900/50 text-emerald-300' :
            result.status_code >= 300 && result.status_code < 400 ? 'bg-blue-900/50 text-blue-300' :
            'bg-red-900/50 text-red-300')}>
            HTTP {result.status_code}
          </span>
          <span className="text-gray-500">{result.duration_ms} ms</span>
          <span className="text-gray-500">{result.body_size.toLocaleString()} B</span>
          <span className="text-gray-500 font-mono">enc: {result.encoding}</span>
          {result.truncated && <span className="text-amber-400">⚠ body усечён до 200KB</span>}
        </div>

        {result.content_type && (
          <div className="text-xs text-gray-500">
            content-type: <span className="text-gray-300 font-mono">{result.content_type}</span>
          </div>
        )}

        <div className="text-xs text-gray-500">
          final-url:{' '}
          <a href={result.final_url} target="_blank" rel="noreferrer"
             className="text-indigo-300 hover:underline font-mono break-all">
            {result.final_url}
          </a>
        </div>

        {result.history.length > 0 && (
          <div className="text-xs space-y-0.5">
            <div className="text-gray-500">redirect history ({result.history.length}):</div>
            {result.history.map((h, i) => (
              <div key={i} className="font-mono text-gray-400 ml-2">
                <span className="text-blue-300">{h.status}</span> → <a href={h.url} target="_blank"
                                                                       rel="noreferrer"
                                                                       className="hover:underline">{h.url}</a>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Headers */}
      <details className="bg-gray-900 border border-gray-800 rounded-lg">
        <summary className="px-3 py-2 cursor-pointer text-xs text-gray-400 hover:text-gray-200">
          Response headers ({Object.keys(result.headers).length})
        </summary>
        <div className="p-3 border-t border-gray-800 space-y-0.5 text-xs">
          {Object.entries(result.headers).map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <span className="text-gray-500 font-mono">{k}:</span>
              <span className="text-gray-300 font-mono break-all">{v}</span>
            </div>
          ))}
        </div>
      </details>

      {/* Body */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
          <span className="text-xs text-gray-400">Body ({result.body_text.length} символов)</span>
          <div className="flex items-center gap-2">
            <a
              href={`data:${result.content_type || 'text/plain'};charset=${result.encoding},${encodeURIComponent(result.body_text)}`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded"
            >
              <ExternalLink size={11} /> Открыть
            </a>
            <button
              type="button"
              onClick={onCopyBody}
              className="flex items-center gap-1 px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded"
            >
              {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
              Copy
            </button>
          </div>
        </div>
        <pre className="p-3 text-xs text-gray-200 whitespace-pre-wrap break-all overflow-auto"
             style={{ maxHeight: 600, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
          {result.body_text}
        </pre>
      </div>

      <SelectorPlayground html={result.body_text} />
    </div>
  )
}

// ─── CSS Selector playground ─────────────────────────────────────────────────

function SelectorPlayground({ html }: { html: string }) {
  const [selector, setSelector] = useState('')

  type SelectorResult =
    | { kind: 'ok'; matches: { text: string; outerHTML: string }[] }
    | { kind: 'error'; message: string }

  // DOMParser — синхронный браузерный API, никаких сетевых запросов.
  // useMemo пересчитывается при каждом изменении селектора или html.
  const result = useMemo((): SelectorResult | null => {
    const q = selector.trim()
    if (!q) return null
    try {
      const doc = new DOMParser().parseFromString(html, 'text/html')
      const nodes = Array.from(doc.querySelectorAll(q))
      return { kind: 'ok', matches: nodes.map(el => ({ text: el.textContent?.trim() ?? '', outerHTML: el.outerHTML })) }
    } catch (e) {
      return { kind: 'error', message: String(e) }
    }
  }, [html, selector])

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 space-y-2">
      <div className="text-xs text-gray-500 font-medium uppercase tracking-wide">CSS Selector</div>
      <div className="flex items-center gap-2">
        <input
          value={selector}
          onChange={e => setSelector(e.target.value)}
          placeholder=".price, h1, [data-product-id]"
          className="flex-1 px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200 placeholder-gray-500 font-mono focus:outline-none focus:border-indigo-500"
        />
        {result?.kind === 'ok' && (
          <span className={clsx('text-xs whitespace-nowrap', result.matches.length ? 'text-emerald-400' : 'text-gray-500')}>
            {result.matches.length} совпадений
          </span>
        )}
      </div>
      {result?.kind === 'error' && (
        <div className="text-xs text-red-400 font-mono">{result.message}</div>
      )}
      {result?.kind === 'ok' && result.matches.length > 0 && (
        <div className="space-y-1 max-h-72 overflow-y-auto">
          {result.matches.map((m, i) => (
            <details key={i} className="text-xs group">
              <summary className="cursor-pointer list-none flex items-center gap-2 py-0.5 text-gray-400 hover:text-gray-200">
                <span className="text-gray-600 font-mono w-6 flex-shrink-0">[{i}]</span>
                <span className="truncate">{m.text || <span className="text-gray-600 italic">(нет текста)</span>}</span>
              </summary>
              <pre className="mt-1 p-2 bg-gray-950 border border-gray-800 rounded text-[11px] text-gray-300 whitespace-pre-wrap break-all font-mono">
                {m.outerHTML}
              </pre>
            </details>
          ))}
        </div>
      )}
      {result?.kind === 'ok' && result.matches.length === 0 && selector.trim() && (
        <div className="text-xs text-gray-500 italic">Нет совпадений.</div>
      )}
      <div className="text-[10px] text-gray-600">
        Применяется к полученному body через DOMParser — без сетевых запросов.
      </div>
    </div>
  )
}
