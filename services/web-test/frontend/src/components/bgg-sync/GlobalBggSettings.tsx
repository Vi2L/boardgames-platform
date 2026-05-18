/**
 * GlobalBggSettings (WT-F7) — сводная карточка над списком scheduler-job'ов на
 * странице /bgg-sync. Показывает три значения:
 *  1. Bearer token BGG (read-only, set/not set).
 *  2. Family cascade enabled (см. CAT-8 — в коммите 1 read-only, в коммите 3
 *     становится editable через PATCH /admin/runtime-flags/bgg_family_cascade_enabled).
 *  3. Cascade rate-limit (read-only, ENV-only — это не оперативная ручка).
 *
 * Зачем сводная карточка: эти значения сейчас живут в ENV (.env), и без UI'я
 * проверить состояние можно только через `docker exec bg-catalog env`. На случай
 * «что-то странное с обогащением» — взгляд на эту секцию даёт мгновенный ответ.
 */
import { useQuery } from '@tanstack/react-query'
import { ShieldCheck, ShieldAlert, KeyRound, Network, Timer } from 'lucide-react'
import clsx from 'clsx'
import { fetchBggSettings } from '../../lib/bgg-sync'

export function GlobalBggSettings() {
  const q = useQuery({
    queryKey: ['bgg-sync', 'settings', 'bgg'],
    queryFn: fetchBggSettings,
    // Дольше staleTime — значения не меняются часто, а карточка статична.
    staleTime: 30_000,
  })

  if (q.isLoading) {
    return (
      <div className="border border-gray-800 bg-gray-900/40 rounded-lg p-3 text-[11px] text-gray-500">
        Загружаю BGG settings…
      </div>
    )
  }
  if (q.isError || !q.data) {
    return (
      <div className="border border-red-900 bg-red-950/30 rounded-lg p-3 text-[11px] text-red-300">
        Ошибка загрузки BGG settings: {(q.error as Error | null)?.message ?? '—'}
      </div>
    )
  }

  const s = q.data
  return (
    <div className="border border-gray-800 bg-gray-900/40 rounded-lg p-3 mb-3">
      <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-2">
        Global BGG settings
      </div>
      <div className="grid grid-cols-3 gap-3 text-[11px]">
        <Stat
          icon={<KeyRound size={11} />}
          label="Bearer token"
          value={s.bgg_api_token_set ? 'задан' : 'не задан'}
          tone={s.bgg_api_token_set ? 'ok' : 'warn'}
          hint={s.bgg_api_token_set
            ? 'BGG_API_TOKEN присутствует в окружении catalog.'
            : 'BGG XML API без токена → 401. Задайте BGG_API_TOKEN в .env.'}
        />
        <Stat
          icon={<Network size={11} />}
          label="Family cascade"
          value={s.family_cascade_enabled ? 'включён' : 'выключен'}
          tone={s.family_cascade_enabled ? 'ok' : 'mute'}
          hint={s.family_cascade_enabled_editable
            ? 'CAT-8: подтягивать членов BGG-семьи после enrich_one.'
            : 'CAT-8: editable toggle появится после миграции 0018 (см. CAT-8).'}
        />
        <Stat
          icon={<Timer size={11} />}
          label="Cascade rate-limit"
          value={`${s.family_cascade_rate_limit_sec.toFixed(1)} с`}
          tone="mute"
          hint="Пауза между cascade-вызовами enrich_one. Меняется через ENV (BGG_FAMILY_CASCADE_RATE_LIMIT_SEC)."
        />
      </div>
    </div>
  )
}

function Stat({
  icon, label, value, tone, hint,
}: {
  icon: React.ReactNode
  label: string
  value: string
  tone: 'ok' | 'warn' | 'mute'
  hint: string
}) {
  const valueColor = tone === 'ok'
    ? 'text-emerald-300'
    : tone === 'warn'
    ? 'text-amber-300'
    : 'text-gray-300'
  const Icon = tone === 'ok' ? ShieldCheck : tone === 'warn' ? ShieldAlert : null
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">
        {icon}
        <span>{label}</span>
      </div>
      <div className={clsx('font-mono text-[12px] flex items-center gap-1', valueColor)}>
        {Icon && <Icon size={11} />}
        {value}
      </div>
      <div className="text-[10px] text-gray-500 leading-snug mt-0.5">{hint}</div>
    </div>
  )
}
