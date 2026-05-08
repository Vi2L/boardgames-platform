/**
 * Редактор одного набора MatchParams (threshold, prefer_external_id, weights).
 *
 * Используется автономно (в табе MatchParamsTab) и встраиваемо (в AutoLinkModal /
 * candidates-фильтре в будущем). Контролируемый компонент: значения извне через
 * `value`, изменения наружу через `onChange`.
 */
import type { MatchParams } from '../../lib/sources'

type Props = {
  value: MatchParams
  onChange: (p: MatchParams) => void
  /** Скрыть подписи — режим компактного inline (для модалок). */
  compact?: boolean
}

export function MatchParamsForm({ value, onChange, compact = false }: Props) {
  const set = (patch: Partial<MatchParams>) =>
    onChange({ ...value, ...patch })
  const setWeight = (key: 'ru' | 'en' | 'alias', v: number) =>
    onChange({ ...value, weights: { ...value.weights, [key]: v } })

  return (
    <div className={compact ? 'space-y-2' : 'space-y-4'}>
      {/* Threshold */}
      <Slider
        label="Threshold"
        hint="Минимальный score кандидата (после применения весов)"
        min={0}
        max={1}
        step={0.05}
        value={value.threshold}
        onChange={v => set({ threshold: v })}
      />

      {/* Prefer external ID */}
      <label className="flex items-start gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          checked={value.prefer_external_id}
          onChange={e => set({ prefer_external_id: e.target.checked })}
          className="mt-0.5"
        />
        <div>
          <div className="text-gray-200">Сначала по внешним ID</div>
          {!compact && (
            <div className="text-xs text-gray-500 mt-0.5">
              Если у raw есть BGG/Tesera ID — добавить deterministic-кандидата
              со score=1.0 поверх trgm-результатов.
            </div>
          )}
        </div>
      </label>

      {/* Weights */}
      <div className="space-y-2">
        {!compact && (
          <div className="text-xs uppercase tracking-wide text-gray-500">
            Веса по источнику
          </div>
        )}
        <Slider
          label="title_ru"
          min={0}
          max={2}
          step={0.1}
          value={value.weights.ru}
          onChange={v => setWeight('ru', v)}
        />
        <Slider
          label="title_en"
          min={0}
          max={2}
          step={0.1}
          value={value.weights.en}
          onChange={v => setWeight('en', v)}
        />
        <Slider
          label="alias"
          hint="Множитель для совпадений через game_aliases (поверх языкового веса)"
          min={0}
          max={2}
          step={0.1}
          value={value.weights.alias}
          onChange={v => setWeight('alias', v)}
        />
      </div>
    </div>
  )
}

function Slider({
  label,
  hint,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string
  hint?: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
}) {
  return (
    <label className="block">
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-300">{label}</span>
        <span className="font-mono text-violet-300 tabular-nums">
          {value.toFixed(2)}
        </span>
      </div>
      {hint && <div className="text-xs text-gray-500 mt-0.5">{hint}</div>}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full mt-1 accent-violet-500"
      />
    </label>
  )
}
