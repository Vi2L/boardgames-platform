/**
 * Design tokens · web-test redesign (PR 1 Foundation, handoff 2026-05-16)
 *
 * Источник правды для UI-системы: цвета, типографика, плотность, статусы.
 * См. сопроводительный handoff в `.scratch/admin-panel-design/`:
 *   - tokens/design-tokens.ts — этот файл
 *   - tokens/status-system.md — таблица применений statusKey → tone
 *
 * Tailwind extend подключается через `tokens.tailwind` в `tailwind.config.ts`.
 * Runtime-объект `tokens` экспортируется для мест, где Tailwind утилит мало
 * (например, inline SVG-цвета в sparkline).
 *
 * Магазины (`stores`) — здесь только для UI-маппинга бейджей. Источник правды
 * слагов — `src/lib/stores.ts`. Не переделывать тот, использовать как есть.
 */

// ─── Colors ──────────────────────────────────────────────────────────────

export const colors = {
  // Тёмный каркас. Меньше зелени, чем у gray. Не плодим оттенки.
  bg: {
    base: '#09090b',                    // zinc-950
    elevated: '#18181b',                // zinc-900
    hover: 'rgba(39, 39, 42, 0.6)',     // zinc-800/60
  },
  border: {
    DEFAULT: '#27272a',                  // zinc-800
    hard: '#3f3f46',                     // zinc-700
    soft: 'rgba(39, 39, 42, 0.6)',
  },
  text: {
    primary: '#f4f4f5',                  // zinc-100
    secondary: '#a1a1aa',                // zinc-400
    muted: '#71717a',                    // zinc-500
    faint: '#52525b',                    // zinc-600
  },
  // Акцент — один цвет. ТЗ §5: indigo-400.
  accent: {
    fg: '#818cf8',                       // indigo-400  · focus ring, active nav, links
    bg: '#6366f1',                       // indigo-500  · primary CTA bg
    soft: 'rgba(99, 102, 241, 0.15)',
    bdr: 'rgba(99, 102, 241, 0.4)',
  },
  // Semantic — для бейджей, состояний.
  semantic: {
    ok:      { fg: '#34d399', bg: 'rgba(16, 185, 129, 0.15)', bdr: 'rgba(16, 185, 129, 0.3)' },
    warn:    { fg: '#fbbf24', bg: 'rgba(245, 158, 11, 0.15)', bdr: 'rgba(245, 158, 11, 0.3)' },
    danger:  { fg: '#fb7185', bg: 'rgba(244, 63, 94, 0.15)',  bdr: 'rgba(244, 63, 94, 0.3)'  },
    info:    { fg: '#818cf8', bg: 'rgba(99, 102, 241, 0.15)', bdr: 'rgba(99, 102, 241, 0.3)' },
    neutral: { fg: '#a1a1aa', bg: 'rgba(39, 39, 42, 0.8)',    bdr: '#3f3f46' },
  },
} as const

// ─── Typography ──────────────────────────────────────────────────────────

export const typography = {
  fontFamily: {
    sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
    mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
  },
  // Узкая шкала: ТЗ §5 — без hero-размеров (никаких 24/32/48).
  // Tailwind перезаписывает свои размеры этим набором — за счёт `theme.extend.fontSize`.
  fontSize: {
    'xxs':  ['10px', { lineHeight: '14px' }],
    'xs':   ['11px', { lineHeight: '16px' }],
    'sm':   ['12px', { lineHeight: '16px' }],
    'base': ['13px', { lineHeight: '18px' }],   // дефолт body
    'md':   ['14px', { lineHeight: '20px' }],
    'lg':   ['16px', { lineHeight: '22px' }],
    'xl':   ['18px', { lineHeight: '24px' }],   // потолок (заголовки страниц)
  },
} as const

// ─── Density ─────────────────────────────────────────────────────────────

export const density = {
  compact:     32,
  cozy:        40,
  comfortable: 48,
} as const

export type DensityKey = keyof typeof density

// Управляющие элементы: Button/Input/IconButton.
export const controlHeights = {
  xs: 24,
  sm: 28,
  md: 32,
  lg: 36,
} as const

// ─── Магазины (для UI-бейджей; источник правды слагов — lib/stores.ts) ───

export const stores = [
  { slug: 'hobbygames',  label: 'HobbyGames',  dotClass: 'bg-blue-400',    tagClass: 'bg-blue-500/15 text-blue-300 border-blue-500/30'       },
  { slug: 'lavkaigr',    label: 'Лавка игр',   dotClass: 'bg-emerald-400', tagClass: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  { slug: 'gaga',        label: 'GaGa',        dotClass: 'bg-orange-400',  tagClass: 'bg-orange-500/15 text-orange-300 border-orange-500/30'    },
  { slug: 'crowdgames',  label: 'Crowd Games', dotClass: 'bg-purple-400',  tagClass: 'bg-purple-500/15 text-purple-300 border-purple-500/30'    },
  { slug: 'avito',       label: 'Авито',       dotClass: 'bg-teal-400',    tagClass: 'bg-teal-500/15 text-teal-300 border-teal-500/30'          },
  { slug: 'wildberries', label: 'Wildberries', dotClass: 'bg-rose-400',    tagClass: 'bg-rose-500/15 text-rose-300 border-rose-500/30'          },
  { slug: 'ozon',        label: 'Ozon',        dotClass: 'bg-sky-400',     tagClass: 'bg-sky-500/15 text-sky-300 border-sky-500/30'             },
] as const

// ─── Status system ───────────────────────────────────────────────────────
// См. tokens/status-system.md — таблица применений.

export type StatusTone = 'ok' | 'warn' | 'danger' | 'info' | 'neutral'

export type StatusKey =
  | 'pending' | 'processing' | 'done' | 'failed' | 'skipped'         // pipeline / jobs
  | 'auto' | 'manual' | 'unmatched' | 'rejected'                     // matching
  | 'closed' | 'half_open' | 'open' | 'unknown'                      // circuit breaker

export const statusSystem: Record<StatusKey, { tone: StatusTone; label: string }> = {
  pending:    { tone: 'neutral', label: 'pending'    },
  processing: { tone: 'info',    label: 'processing' },
  done:       { tone: 'ok',      label: 'done'       },
  failed:     { tone: 'danger',  label: 'failed'     },
  skipped:    { tone: 'neutral', label: 'skipped'    },
  auto:       { tone: 'ok',      label: 'auto'       },
  manual:     { tone: 'info',    label: 'manual'     },
  unmatched:  { tone: 'warn',    label: 'unmatched'  },
  rejected:   { tone: 'danger',  label: 'rejected'   },
  closed:     { tone: 'ok',      label: 'CLOSED'     },
  half_open:  { tone: 'warn',    label: 'HALF-OPEN'  },
  open:       { tone: 'danger',  label: 'OPEN'       },
  unknown:    { tone: 'neutral', label: 'unknown'    },
}

// Tailwind class-bundle для tone — используется в Badge / Tag / StatusDot.
export const toneClasses: Record<StatusTone, {
  bg: string; text: string; border: string; dot: string
}> = {
  ok:      { bg: 'bg-emerald-500/15', text: 'text-emerald-300', border: 'border-emerald-500/30', dot: 'bg-emerald-500' },
  warn:    { bg: 'bg-amber-500/15',   text: 'text-amber-300',   border: 'border-amber-500/30',   dot: 'bg-amber-500'   },
  danger:  { bg: 'bg-rose-500/15',    text: 'text-rose-300',    border: 'border-rose-500/30',    dot: 'bg-rose-500'    },
  info:    { bg: 'bg-indigo-500/15',  text: 'text-indigo-300',  border: 'border-indigo-500/30',  dot: 'bg-indigo-400'  },
  neutral: { bg: 'bg-zinc-800/80',    text: 'text-zinc-300',    border: 'border-zinc-700',       dot: 'bg-zinc-500'    },
}

// Score colors — отдельная шкала (не state). Tabular-nums + mono обязательны
// на месте использования (см. status-system.md).
export function scoreToneClass(score: number | null | undefined): string {
  if (score == null) return 'text-zinc-600'
  if (score >= 0.6) return 'text-emerald-400'
  if (score >= 0.3) return 'text-amber-400'
  return 'text-zinc-500'
}

// ─── Tailwind extend (готов для `theme.extend = tokens.tailwind`) ────────

export const tailwind = {
  fontFamily: typography.fontFamily,
  fontSize:   typography.fontSize,
  // Дополнительные семантические алиасы для удобства, если кому захочется.
  // `bg-surface`, `bg-surface-elevated` — короче чем `bg-zinc-950`/`bg-zinc-900`.
  colors: {
    surface: {
      DEFAULT:  colors.bg.base,
      elevated: colors.bg.elevated,
    },
  },
} as const

export const tokens = {
  colors,
  typography,
  density,
  controlHeights,
  stores,
  statusSystem,
  toneClasses,
  tailwind,
}
