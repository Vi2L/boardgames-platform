/**
 * SchemaForm (WT-F7) — рендерит динамическую форму по `FieldSpec[]`, полученному
 * с бэка. Заменяет JSON-textarea в CronEditor.
 *
 * Паттерн: controlled-форма с одним `values: Record<string, unknown>` стейтом —
 * вызов `onChange(next)` отдаёт родителю полный объект значений. Это упрощает
 * mutation в TanStack Query: `rescheduleJob(id, { params: values })`.
 *
 * UI-решение: используем нативные input'ы (а не ui/Input) для консистентности с
 * существующим CronEditor — миграция всей секции на ui/* — это WT-DESIGN-PR2 и
 * последующие. Здесь — точечная функциональная замена, без визуальной революции.
 */
import type { FieldSpec } from '../../lib/bgg-sync'
import clsx from 'clsx'

export type SchemaFormProps = {
  schema: FieldSpec[]
  values: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
}

/** Резолв значения с fallback на default из схемы — null/undefined → schema.default. */
function resolveValue(field: FieldSpec, value: unknown): unknown {
  if (value === null || value === undefined) return field.default
  return value
}

export function SchemaForm({ schema, values, onChange }: SchemaFormProps) {
  if (schema.length === 0) {
    return (
      <div className="text-[11px] text-gray-500 italic py-1">
        У этого job'а нет параметров — только cron и enabled.
      </div>
    )
  }

  const setValue = (name: string, v: unknown) =>
    onChange({ ...values, [name]: v })

  return (
    <div className="grid grid-cols-2 gap-3">
      {schema.map(field => {
        const current = resolveValue(field, values[field.name])
        return (
          <div key={field.name}>
            <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
              {field.label}
              {field.required && <span className="text-amber-400"> *</span>}
            </label>
            <FieldInput field={field} value={current} onChange={v => setValue(field.name, v)} />
            {field.description && (
              <div className="mt-1 text-[10px] text-gray-500 leading-snug">
                {field.description}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: FieldSpec
  value: unknown
  onChange: (v: unknown) => void
}) {
  const baseClass =
    'w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-indigo-500'

  if (field.type === 'bool') {
    return (
      <label className={clsx('flex items-center gap-2 text-xs text-gray-300 cursor-pointer', 'py-1.5')}>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={e => onChange(e.target.checked)}
        />
        {value ? 'включено' : 'выключено'}
      </label>
    )
  }

  if (field.type === 'enum') {
    return (
      <select
        value={String(value ?? '')}
        onChange={e => onChange(e.target.value)}
        className={baseClass}
      >
        {(field.enum ?? []).map(opt => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    )
  }

  if (field.type === 'int' || field.type === 'float') {
    return (
      <input
        type="number"
        value={value === '' || value === null || value === undefined ? '' : Number(value)}
        step={field.type === 'float' ? 0.1 : 1}
        min={field.min}
        max={field.max}
        onChange={e => {
          const raw = e.target.value
          if (raw === '') {
            onChange(null)
            return
          }
          const n = field.type === 'int' ? parseInt(raw, 10) : parseFloat(raw)
          onChange(Number.isFinite(n) ? n : raw)
        }}
        className={clsx(baseClass, 'font-mono')}
      />
    )
  }

  // string
  return (
    <input
      type="text"
      value={String(value ?? '')}
      onChange={e => onChange(e.target.value)}
      className={baseClass}
    />
  )
}
