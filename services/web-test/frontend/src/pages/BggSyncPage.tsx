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
import clsx from 'clsx'

import { SchedulerHealth } from '../components/bgg-sync/SchedulerHealth'
import { JobHistoryTable } from '../components/bgg-sync/JobHistoryTable'
import { HotnessPanel } from '../components/bgg-sync/HotnessPanel'
import { GeeklistPanel } from '../components/bgg-sync/GeeklistPanel'
import { NoBggList } from '../components/bgg-sync/NoBggList'

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
    <div className="space-y-4">
      <header className="flex items-baseline gap-3">
        <h1 className="text-lg font-bold text-gray-100">BGG Sync</h1>
        <span className="text-xs text-gray-500">
          Периодическая синхронизация с BoardGameGeek: ручные триггеры, история,
          расписание, snapshot'ы Hotness и GeekList.
        </span>
      </header>

      {/* Tab strip */}
      <nav className="flex items-center gap-1 border-b border-gray-800">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px transition-colors',
              tab === id
                ? 'border-violet-500 text-violet-300'
                : 'border-transparent text-gray-400 hover:text-gray-200',
            )}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </nav>

      {/* Tab content */}
      <div>
        {tab === 'schedule' && <SchedulerHealth />}
        {tab === 'history' && <JobHistoryTable />}
        {tab === 'hotness' && <HotnessPanel />}
        {tab === 'geeklist' && <GeeklistPanel />}
        {tab === 'no-bgg' && <NoBggList />}
      </div>
    </div>
  )
}
