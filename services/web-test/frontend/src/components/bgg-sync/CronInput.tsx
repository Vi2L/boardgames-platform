/**
 * CronInput (WT-F7) — input для cron-выражения с пресетами + human-readable preview.
 *
 * Дизайнерское решение: пресеты — это просто <select>, который при выборе подставляет
 * unix-cron строку в текстовый input. Пользователь видит и пресет, и raw cron — это
 * образовательно (учит читать cron) и оставляет escape hatch в любой момент написать
 * собственное выражение.
 *
 * Preview через `cronstrue` с RU-локалью. Если cron невалиден — показываем красным
 * сообщение об ошибке, но не блокируем ввод (валидация на бэке при PATCH).
 */
import { useMemo, useState } from 'react'
import { Clock } from 'lucide-react'
import cronstrue from 'cronstrue/i18n'
import clsx from 'clsx'

// Преднабор: имя в UI + cron строка. UTC подразумевается во всех (как и весь scheduler).
// Подобрано под существующие job'ы — этого хватает на 90% сценариев в нашем стеке.
const PRESETS: Array<{ label: string; expr: string }> = [
  { label: 'Каждый час (00 минут)',          expr: '0 * * * *' },
  { label: 'Каждые 30 минут',                expr: '*/30 * * * *' },
  { label: 'Ежедневно в 02:00 UTC',          expr: '0 2 * * *' },
  { label: 'Ежедневно в 03:00 UTC',          expr: '0 3 * * *' },
  { label: 'Ежедневно в 04:00 UTC',          expr: '0 4 * * *' },
  { label: 'Ежедневно в 06:00 UTC',          expr: '0 6 * * *' },
  { label: 'Понедельник 03:00 UTC',          expr: '0 3 * * 1' },
  { label: 'Воскресенье 05:00 UTC',          expr: '0 5 * * 0' },
  { label: '1-е число месяца, 02:00 UTC',    expr: '0 2 1 * *' },
]

export type CronInputProps = {
  value: string
  onChange: (next: string) => void
  /** Подсветка: добавить розовую обводку, например когда родитель знает что cron битый. */
  invalid?: boolean
  className?: string
}

export function CronInput({ value, onChange, invalid, className }: CronInputProps) {
  // Local state для пресета — если поле value совпало с пресетом, подсветим его.
  // Если нет — оставим dropdown в "Custom".
  const matchedPreset = useMemo(
    () => PRESETS.find(p => p.expr === value.trim())?.expr ?? '',
    [value],
  )
  const [presetVal, setPresetVal] = useState(matchedPreset)

  // Preview через cronstrue. Если cron невалиден — cronstrue бросает; ловим.
  const preview = useMemo(() => {
    if (!value.trim()) return { ok: true, text: '' }
    try {
      return {
        ok: true,
        text: cronstrue.toString(value.trim(), { locale: 'ru', use24HourTimeFormat: true }),
      }
    } catch (e) {
      return { ok: false, text: (e as Error).message }
    }
  }, [value])

  return (
    <div className={clsx('space-y-2', className)}>
      <div className="grid grid-cols-2 gap-2">
        <input
          type="text"
          value={value}
          onChange={e => {
            onChange(e.target.value)
            setPresetVal('')  // user редактирует — сбрасываем preset, не путаем
          }}
          className={clsx(
            'w-full px-2 py-1.5 bg-gray-900 border rounded text-xs font-mono text-gray-200',
            'focus:outline-none focus:border-indigo-500',
            invalid || !preview.ok ? 'border-red-700' : 'border-gray-700',
          )}
          placeholder="0 3 * * 1"
        />
        <select
          value={presetVal}
          onChange={e => {
            const expr = e.target.value
            setPresetVal(expr)
            if (expr) onChange(expr)
          }}
          className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-indigo-500"
        >
          <option value="">Пресет…</option>
          {PRESETS.map(p => (
            <option key={p.expr} value={p.expr}>{p.label}</option>
          ))}
        </select>
      </div>
      <div className={clsx(
        'flex items-start gap-1.5 text-[10px]',
        preview.ok ? 'text-gray-500' : 'text-red-400',
      )}>
        <Clock size={10} className="mt-0.5 shrink-0" />
        <span>{preview.text || 'формат: «мин час день_мес мес день_нед» (UTC)'}</span>
      </div>
    </div>
  )
}
