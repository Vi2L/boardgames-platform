import { Fragment, useState } from 'react'
import { Copy, Check } from 'lucide-react'

interface Props {
  data: unknown
  maxHeight?: number
}

/**
 * Рекурсивный рендер JSON-совместимого значения в React-узлы с подсветкой.
 *
 * Раньше использовался JSON.stringify + regex + dangerouslySetInnerHTML —
 * это работало, но любая правка регулярки рисковала прорвать XSS, плюс
 * некоторые форматы (числа с ведущей точкой, строки внутри массивов) не
 * подсвечивались. Новый подход — обходить значение, формируя текст из
 * безопасных React-нод; никакого innerHTML.
 *
 * Глубина нужна только для отступов (чтобы сохранить вид JSON.stringify(_, null, 2)).
 */
function renderValue(value: unknown, depth: number = 0): React.ReactNode {
  if (value === null) {
    return <span className="text-blue-400">null</span>
  }
  if (value === undefined) {
    // JSON.stringify не выводит undefined, но в data: unknown это возможно
    return <span className="text-gray-500">undefined</span>
  }
  if (typeof value === 'boolean') {
    return <span className="text-blue-400">{String(value)}</span>
  }
  if (typeof value === 'number') {
    return <span className="text-yellow-300">{Number.isFinite(value) ? value : String(value)}</span>
  }
  if (typeof value === 'string') {
    // JSON.stringify даёт корректное экранирование (\n, \", \uXXXX и т.д.)
    return <span className="text-green-400">{JSON.stringify(value)}</span>
  }

  const innerIndent = '  '.repeat(depth + 1)
  const closingIndent = '  '.repeat(depth)

  if (Array.isArray(value)) {
    if (value.length === 0) return <>[]</>
    return (
      <>
        {'['}
        {'\n'}
        {value.map((v, i) => (
          <Fragment key={i}>
            {innerIndent}
            {renderValue(v, depth + 1)}
            {i < value.length - 1 ? ',' : ''}
            {'\n'}
          </Fragment>
        ))}
        {closingIndent}
        {']'}
      </>
    )
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return <>{'{}'}</>
    return (
      <>
        {'{'}
        {'\n'}
        {entries.map(([k, v], i) => (
          <Fragment key={k}>
            {innerIndent}
            <span className="text-gray-300">{JSON.stringify(k)}</span>
            {': '}
            {renderValue(v, depth + 1)}
            {i < entries.length - 1 ? ',' : ''}
            {'\n'}
          </Fragment>
        ))}
        {closingIndent}
        {'}'}
      </>
    )
  }

  // Fallback для функций/символов — крайне маловероятно в данных API
  return <span className="text-red-400">{String(value)}</span>
}

export function JsonViewer({ data, maxHeight = 400 }: Props) {
  const [copied, setCopied] = useState(false)
  // Для буфера обмена — все ещё удобнее иметь JSON-текст под рукой
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
      <pre
        className="p-3 text-xs overflow-auto whitespace-pre"
        style={{ maxHeight, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}
      >
        {renderValue(data)}
      </pre>
    </div>
  )
}
