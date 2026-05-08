/**
 * Единый источник правды для имён и цветов магазинов.
 *
 * Раньше каждый компонент держал свой Record<string, string> — это привело
 * к расхождениям («HobbyGames» vs «HobbyGames.ru») и к тому, что новый
 * парсер `crowdgames` не имел цвета и появлялся серым плейсхолдером.
 *
 * Если меняется человеческое имя или появляется новый магазин — правится
 * только этот файл.
 */

export const STORE_LABELS: Record<string, string> = {
  hobbygames: 'HobbyGames',
  lavkaigr:   'Лавка игр',
  gaga:       'GaGa',
  crowdgames: 'Crowd Games',
  avito:      'Авито',
}

/** Полные домены — для второстепенных мест (ParserCard, tooltip). */
export const STORE_DOMAINS: Record<string, string> = {
  hobbygames: 'hobbygames.ru',
  lavkaigr:   'lavkaigr.ru',
  gaga:       'gaga.ru',
  crowdgames: 'crowdgames.ru',
  avito:      'avito.ru',
}

/** Для бейджа в таблице/Drawer — приглушённые насыщенные тона на тёмном фоне. */
export const STORE_BADGE_COLORS: Record<string, string> = {
  hobbygames: 'bg-blue-900/70 text-blue-300',
  lavkaigr:   'bg-green-900/70 text-green-300',
  gaga:       'bg-orange-900/70 text-orange-300',
  crowdgames: 'bg-purple-900/70 text-purple-300',
  avito:      'bg-teal-900/70 text-teal-300',
}

/** Для бордера карточек ParserCard — те же оттенки, но прозрачнее. */
export const STORE_BORDER_COLORS: Record<string, string> = {
  hobbygames: 'bg-blue-900/40 border-blue-800',
  lavkaigr:   'bg-green-900/40 border-green-800',
  gaga:       'bg-orange-900/40 border-orange-800',
  crowdgames: 'bg-purple-900/40 border-purple-800',
  avito:      'bg-teal-900/40 border-teal-800',
}

export function getStoreLabel(slug: string, fallback?: string): string {
  return STORE_LABELS[slug] ?? fallback ?? slug
}

export function getStoreBadgeColor(slug: string): string {
  return STORE_BADGE_COLORS[slug] ?? 'bg-gray-800 text-gray-300'
}

export function getStoreBorderColor(slug: string): string {
  return STORE_BORDER_COLORS[slug] ?? 'border-gray-800'
}

export function getStoreDomain(slug: string, fallback?: string): string {
  return STORE_DOMAINS[slug] ?? fallback ?? slug
}
