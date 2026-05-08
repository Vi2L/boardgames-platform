/**
 * Левая колонка SourcesPage: список известных источников.
 *
 * Disabled-провайдеры (BGA, Dicebreaker) отображаются полупрозрачными — это
 * визуальный анонс «скоро появится». Клик по ним блокируется.
 */
import clsx from 'clsx'
import { SOURCE_PROVIDERS } from '../../lib/sourceProviders'

type Props = {
  current: string
  onSelect: (slug: string) => void
}

export function ProviderSidebar({ current, onSelect }: Props) {
  return (
    <aside className="w-56 flex-shrink-0 border-r border-gray-800 bg-gray-900/50 p-3 space-y-1 overflow-y-auto">
      <div className="text-xs uppercase tracking-wide text-gray-500 px-2 mb-2">
        Источники
      </div>
      {SOURCE_PROVIDERS.map(p => {
        const Icon = p.icon
        const isCurrent = p.slug === current
        return (
          <button
            key={p.slug}
            type="button"
            disabled={!p.enabled}
            onClick={() => p.enabled && onSelect(p.slug)}
            title={p.description}
            className={clsx(
              'w-full flex items-start gap-2.5 px-2.5 py-2 rounded-md text-left text-sm transition-colors',
              !p.enabled && 'opacity-40 cursor-not-allowed',
              p.enabled && !isCurrent && 'text-gray-300 hover:bg-gray-800/60',
              p.enabled && isCurrent && 'bg-violet-900/40 text-violet-200',
            )}
          >
            <Icon size={15} className="mt-0.5 flex-shrink-0" />
            <div className="min-w-0">
              <div className="font-medium truncate">{p.label}</div>
              <div className="text-[11px] text-gray-500 mt-0.5 leading-tight">
                {p.description}
              </div>
            </div>
          </button>
        )
      })}
    </aside>
  )
}
