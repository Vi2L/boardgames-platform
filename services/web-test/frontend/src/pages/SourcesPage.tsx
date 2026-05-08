/**
 * Страница «Источники» — управление актуализацией данных из внешних источников.
 *
 * Архитектура (provider-agnostic):
 *  - Слева: ProviderSidebar — список провайдеров (Dicefest сейчас, BGA/Dicebreaker позже).
 *  - Справа: 4 таба:
 *      Detection      — сухой прогон скрапа + diff + apply/discard
 *      Staging        — PromotionPanel (раньше жил на /catalog)
 *      Match params   — настройка threshold/weights/external-id + сохранённые профили
 *      Logs           — журнал промоушенов и scrape runs
 *
 * Провайдер выбирается через URL: /sources/:provider — это даёт
 * deep-link'и и чистый back/forward.
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import clsx from 'clsx'
import { ProviderSidebar } from '../components/sources/ProviderSidebar'
import { DetectionTab } from '../components/sources/DetectionTab'
import { MatchParamsTab } from '../components/sources/MatchParamsTab'
import { SourcesLogsTab } from '../components/sources/SourcesLogsTab'
import { StagingTab } from '../components/sources/StagingTab'
import { DEFAULT_PROVIDER, getProvider } from '../lib/sourceProviders'

type TabKey = 'detection' | 'staging' | 'match' | 'logs'

const TABS: { key: TabKey; label: string; description: string }[] = [
  { key: 'detection', label: 'Detection', description: 'Сухой прогон + diff' },
  { key: 'staging', label: 'Staging', description: 'Promotion → canonical' },
  { key: 'match', label: 'Match params', description: 'Профили матчинга' },
  { key: 'logs', label: 'Logs', description: 'Журнал действий' },
]

export function SourcesPage() {
  const { provider: providerParam } = useParams<{ provider?: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabKey>('detection')

  // Если провайдер не задан в URL — редирект на дефолтный, чтобы deep-link
  // и сама страница работали одинаково.
  useEffect(() => {
    if (!providerParam) {
      navigate(`/sources/${DEFAULT_PROVIDER}`, { replace: true })
    }
  }, [providerParam, navigate])

  const providerSlug = providerParam ?? DEFAULT_PROVIDER
  const provider = getProvider(providerSlug)

  const handleSelectProvider = (slug: string) => {
    navigate(`/sources/${slug}`)
    // tab сохраняем — оператор переключает провайдеров на одной задаче.
  }

  return (
    <div className="flex h-[calc(100vh-3rem)] -m-4 md:-m-6">
      <ProviderSidebar current={providerSlug} onSelect={handleSelectProvider} />

      <div className="flex-1 flex flex-col min-w-0">
        {/* Header: имя провайдера + табы */}
        <header className="border-b border-gray-800 px-6 py-3 bg-gray-900/30">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold text-gray-100">
                {provider?.label ?? providerSlug}
              </h1>
              {provider?.description && (
                <p className="text-xs text-gray-500 mt-0.5 max-w-2xl">
                  {provider.description}
                </p>
              )}
            </div>
          </div>
          <nav className="flex gap-1 mt-3">
            {TABS.map(t => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                title={t.description}
                className={clsx(
                  'px-3 py-1.5 text-sm rounded-md transition-colors',
                  tab === t.key
                    ? 'bg-violet-900/50 text-violet-200'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/60',
                )}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </header>

        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'detection' && <DetectionTab provider={providerSlug} />}
          {tab === 'staging' && <StagingTab provider={providerSlug} />}
          {tab === 'match' && <MatchParamsTab provider={providerSlug} />}
          {tab === 'logs' && <SourcesLogsTab provider={providerSlug} />}
        </div>
      </div>
    </div>
  )
}
