/**
 * Реестр известных источников данных.
 *
 * Сейчас подключён один провайдер (Dicefest). Когда добавятся BGA / Dicebreaker /
 * Wikidata-bulk — расширим этот файл, и UI ProviderSidebar / SourcesPage
 * автоматически их подхватит. Backend-эндпоинты `/sources/{provider}/...` уже
 * провайдер-агностичны.
 */
import type { LucideIcon } from 'lucide-react'
import { Sparkles, Lock } from 'lucide-react'

export type SourceProviderConfig = {
  /** Ключ в БД и в URL: /sources/dicefest, params.provider = 'dicefest' */
  slug: string
  label: string
  /** Краткое описание для UI: что это за источник */
  description: string
  icon: LucideIcon
  /** disabled=true → показываем серым в сайдбаре, без интерактивов. Для будущих провайдеров. */
  enabled: boolean
  /** Подсказка к параметрам сухого прогона: что они значат. Опционально. */
  paramsHint?: string
}

export const SOURCE_PROVIDERS: SourceProviderConfig[] = [
  {
    slug: 'dicefest',
    label: 'Dicefest',
    description: 'РФ-локализации с dicefest.ru: издатель, цена предзаказа, ссылки на BGG/Tesera/Nastolio.',
    icon: Sparkles,
    enabled: true,
    paramsHint: 'max_items для пробного прогона (10–50), only_year (2024/2025/2026) — фильтр листинга по году.',
  },
  // Заглушки на будущее — disabled=true показывает «скоро» в UI.
  {
    slug: 'bga',
    label: 'BoardGameArena',
    description: '(скоро) Импорт игр и партий из BGA.',
    icon: Lock,
    enabled: false,
  },
  {
    slug: 'dicebreaker',
    label: 'Dicebreaker',
    description: '(скоро) Обзоры и рекомендации.',
    icon: Lock,
    enabled: false,
  },
]

export const getProvider = (slug: string): SourceProviderConfig | undefined =>
  SOURCE_PROVIDERS.find(p => p.slug === slug)

/** По умолчанию открываем первый включённый провайдер. */
export const DEFAULT_PROVIDER: string =
  SOURCE_PROVIDERS.find(p => p.enabled)?.slug ?? 'dicefest'
