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
import { Beaker, Scale, FileCode2, Link2, ScrollText, type LucideIcon } from 'lucide-react'
import { LiveTestPanel } from '../components/parsers/LiveTestPanel'
import { CompareTab } from '../components/parsers/CompareTab'
import { SnapshotsTab } from '../components/parsers/SnapshotsTab'
import { UrlPlayground } from '../components/parsers/UrlPlayground'
import { ContractPanel } from '../components/parsers/ContractPanel'
import { Tabs } from '../components/ui'

type Tab = 'live' | 'compare' | 'url' | 'contract' | 'snapshots'

const TABS: Array<{ id: Tab; label: string; icon: LucideIcon; hint: string }> = [
  { id: 'live',     label: 'Live Test',  icon: Beaker,     hint: 'мимо кеша, raw ParsedProduct' },
  { id: 'compare',  label: 'Сравнить',   icon: Scale,      hint: 'diff cache vs live по url' },
  { id: 'url',      label: 'По URL',     icon: Link2,      hint: 'пробный GET по URL магазина' },
  { id: 'contract', label: 'Контракт',   icon: ScrollText, hint: 'схема ParsedProduct + coverage' },
  { id: 'snapshots',label: 'Raw HTTP',   icon: FileCode2,  hint: 'тело сохранённых ответов' },
]

export function DebugPage() {
  const [tab, setTab] = useState<Tab>('live')

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Debug парсеров</h1>
        <p className="text-xs text-zinc-500 mt-0.5">
          Диагностические инструменты: запуск мимо кеша, сравнение с live, просмотр raw HTTP.
        </p>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <Tabs.List>
          {TABS.map(t => {
            const Icon = t.icon
            return (
              <Tabs.Trigger key={t.id} value={t.id}>
                <Icon size={12} />
                <span title={t.hint}>{t.label}</span>
              </Tabs.Trigger>
            )
          })}
        </Tabs.List>

        <Tabs.Content value="live"><LiveTestPanel /></Tabs.Content>
        <Tabs.Content value="compare"><CompareTab /></Tabs.Content>
        <Tabs.Content value="url"><UrlPlayground /></Tabs.Content>
        <Tabs.Content value="contract"><ContractPanel /></Tabs.Content>
        <Tabs.Content value="snapshots"><SnapshotsTab /></Tabs.Content>
      </Tabs>
    </div>
  )
}
