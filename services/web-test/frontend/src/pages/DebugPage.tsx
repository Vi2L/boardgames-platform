/**
 * DebugPage — единая точка входа в диагностические инструменты парсеров.
 *
 * Tabs:
 *  - Live Test (F1.1) — парсеры мимо кеша + сырой ParsedProduct.
 *  - Сравнить    (F1.2) — diff cache vs live по url.
 *  - Raw HTTP    (F1.2) — таблица сохранённых HTTP-снепшотов.
 *
 * Дальше сюда же добавятся: URL playground (F1.4), Contract validator (F1.5).
 */
import { useState } from 'react'
import { Beaker, Scale, FileCode2, Link2, type LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import { LiveTestPanel } from '../components/parsers/LiveTestPanel'
import { CompareTab } from '../components/parsers/CompareTab'
import { SnapshotsTab } from '../components/parsers/SnapshotsTab'
import { UrlPlayground } from '../components/parsers/UrlPlayground'

type Tab = 'live' | 'compare' | 'url' | 'snapshots'

const TABS: Array<{ id: Tab; label: string; icon: LucideIcon; hint: string }> = [
  { id: 'live',     label: 'Live Test',  icon: Beaker,    hint: 'мимо кеша, raw ParsedProduct' },
  { id: 'compare',  label: 'Сравнить',   icon: Scale,     hint: 'diff cache vs live по url' },
  { id: 'url',      label: 'По URL',     icon: Link2,     hint: 'пробный GET по URL магазина' },
  { id: 'snapshots',label: 'Raw HTTP',   icon: FileCode2, hint: 'тело сохранённых ответов' },
]

export function DebugPage() {
  const [tab, setTab] = useState<Tab>('live')

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-gray-100">Debug парсеров</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Диагностические инструменты: запуск мимо кеша, сравнение с live, просмотр raw HTTP.
        </p>
      </div>

      <div className="flex gap-1 border-b border-gray-800">
        {TABS.map(t => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={clsx(
                'flex items-center gap-2 px-3 py-2 text-sm transition-colors border-b-2 -mb-px',
                active
                  ? 'text-violet-300 border-violet-500'
                  : 'text-gray-400 border-transparent hover:text-gray-200',
              )}
              title={t.hint}
            >
              <Icon size={14} />
              {t.label}
            </button>
          )
        })}
      </div>

      {tab === 'live' && <LiveTestPanel />}
      {tab === 'compare' && <CompareTab />}
      {tab === 'url' && <UrlPlayground />}
      {tab === 'snapshots' && <SnapshotsTab />}
    </div>
  )
}
