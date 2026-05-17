/**
 * BGG Sync — единый cockpit для периодической синхронизации с BoardGameGeek.
 *
 * Структура — 5 вкладок (паттерн `Tab` из CatalogPage):
 *   1. Расписание   — health-блок 3 scheduled-job'ов + cron editor.
 *   2. История      — таблица ImportJob'ов с фильтрами (manual/scheduled).
 *   3. Hotness      — текущий снимок BGG /hot + история + diff (новые/выбывшие).
 *   4. GeekList     — импорт кураторских списков (Top 50 Most Played etc.).
 *   5. Без BGG ID   — игры из catalog без bgg_id, ссылка на поиск в BGG.
 *
 * Каждая вкладка — отдельный компонент в `components/bgg-sync/`. Этот файл —
 * только router-shell + навигация по табам.
 */
import { useState } from 'react'
import { Calendar, ListChecks, Flame, BookOpen, AlertCircle } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { SchedulerHealth } from '../components/bgg-sync/SchedulerHealth'
import { JobHistoryTable } from '../components/bgg-sync/JobHistoryTable'
import { HotnessPanel } from '../components/bgg-sync/HotnessPanel'
import { GeeklistPanel } from '../components/bgg-sync/GeeklistPanel'
import { NoBggList } from '../components/bgg-sync/NoBggList'
import { Tabs } from '../components/ui'

type Tab = 'schedule' | 'history' | 'hotness' | 'geeklist' | 'no-bgg'

const TABS: Array<{ id: Tab; label: string; icon: LucideIcon }> = [
  { id: 'schedule', label: 'Расписание',  icon: Calendar },
  { id: 'history',  label: 'История',     icon: ListChecks },
  { id: 'hotness',  label: 'Hotness',     icon: Flame },
  { id: 'geeklist', label: 'GeekList',    icon: BookOpen },
  { id: 'no-bgg',   label: 'Без BGG ID',  icon: AlertCircle },
]

export function BggSyncPage() {
  const [tab, setTab] = useState<Tab>('schedule')

  return (
    <div className="p-4 space-y-4">
      <header className="flex items-baseline gap-3">
        <h1 className="text-lg font-semibold text-zinc-100">BGG Sync</h1>
        <span className="text-xs text-zinc-500">
          Периодическая синхронизация с BoardGameGeek: ручные триггеры, история,
          расписание, snapshot'ы Hotness и GeekList.
        </span>
      </header>

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <Tabs.List>
          {TABS.map(({ id, label, icon: Icon }) => (
            <Tabs.Trigger key={id} value={id}>
              <Icon size={12} />
              {label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <Tabs.Content value="schedule" className="pt-4"><SchedulerHealth /></Tabs.Content>
        <Tabs.Content value="history" className="pt-4"><JobHistoryTable /></Tabs.Content>
        <Tabs.Content value="hotness" className="pt-4"><HotnessPanel /></Tabs.Content>
        <Tabs.Content value="geeklist" className="pt-4"><GeeklistPanel /></Tabs.Content>
        <Tabs.Content value="no-bgg" className="pt-4"><NoBggList /></Tabs.Content>
      </Tabs>
    </div>
  )
}
