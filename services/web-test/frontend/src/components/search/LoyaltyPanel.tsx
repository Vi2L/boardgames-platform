import { Sparkles, ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { useLoyaltyStore } from '../../store/loyalty'

/**
 * Раскрываемый блок настроек личных программ лояльности магазинов.
 *
 * Применяется поверх результатов поиска чисто на фронте — пересчитывает
 * отображаемую цену, не трогая parsers/БД. Дисклеймер про корзину важен:
 * мы считаем максимально возможную скидку для КАЖДОЙ строки независимо.
 */
export function LoyaltyPanel() {
  const { enabled, hobbygames, lavkaigr, setEnabled, setHobby, setLavka } = useLoyaltyStore()
  const [open, setOpen] = useState(enabled)

  const Caret = open ? ChevronDown : ChevronRight
  return (
    <div className="border border-gray-800 rounded-lg bg-gray-950/40">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-300 hover:bg-gray-900/40 rounded-t-lg"
      >
        <Caret size={13} className="text-gray-500" />
        <Sparkles size={12} className="text-indigo-400" />
        <label className="flex items-center cursor-pointer select-none" onClick={e => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={e => setEnabled(e.target.checked)}
            className="accent-indigo-500 w-5 h-5"
          />
        </label>
        <span className="font-medium">Учитывать личные скидки</span>
      </button>

      {open && (
        <div className="px-3 pb-3 pt-1 space-y-2.5 border-t border-gray-800/60">
          {/* HobbyGames */}
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 cursor-pointer select-none min-w-[150px]">
              <input
                type="checkbox"
                checked={hobbygames.enabled}
                disabled={!enabled}
                onChange={e => setHobby({ enabled: e.target.checked })}
                className="accent-indigo-500 w-3.5 h-3.5"
              />
              <span className="text-xs text-gray-300">HobbyGames бонусы</span>
            </label>
            <label className="flex items-center gap-1.5">
              <span className="text-xs text-gray-500">Ваши бонусы:</span>
              <input
                type="text"
                value={hobbygames.bonuses === 'unlim' ? 'unlim' : String(hobbygames.bonuses)}
                disabled={!enabled || !hobbygames.enabled}
                onChange={e => {
                  const v = e.target.value.trim()
                  if (v === '' || v.toLowerCase() === 'unlim') {
                    setHobby({ bonuses: 'unlim' })
                    return
                  }
                  const n = Number(v)
                  if (Number.isFinite(n) && n >= 0) setHobby({ bonuses: n })
                }}
                placeholder="unlim"
                className="w-24 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200 disabled:opacity-50"
              />
              <span className="text-[10px] text-gray-500">₽</span>
            </label>
            <span className="text-[10px] text-gray-600">до 15 % от цены товара без акции</span>
          </div>

          {/* Лавка игр */}
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 cursor-pointer select-none min-w-[150px]">
              <input
                type="checkbox"
                checked={lavkaigr.enabled}
                disabled={!enabled}
                onChange={e => setLavka({ enabled: e.target.checked })}
                className="accent-indigo-500 w-3.5 h-3.5"
              />
              <span className="text-xs text-gray-300">Лавка игр</span>
            </label>
            <label className="flex items-center gap-1.5">
              <span className="text-xs text-gray-500">Скидка:</span>
              <input
                type="number"
                min={0}
                max={10}
                value={lavkaigr.percent}
                disabled={!enabled || !lavkaigr.enabled}
                onChange={e => setLavka({ percent: Math.max(0, Math.min(10, Number(e.target.value))) })}
                className="w-14 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200 disabled:opacity-50"
              />
              <span className="text-[10px] text-gray-500">%</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={lavkaigr.vkDon}
                disabled={!enabled || !lavkaigr.enabled}
                onChange={e => setLavka({ vkDon: e.target.checked })}
                className="accent-indigo-500 w-3.5 h-3.5"
              />
              <span className="text-xs text-gray-300">+5 % для донов VK</span>
            </label>
          </div>

          <p className="text-[10px] text-gray-600 leading-tight">
            Личные скидки рассчитаны независимо для каждого товара (бонусы трактуются как доступные именно для этой строки).
            При покупке нескольких товаров одной корзиной суммарная скидка может быть меньше.
          </p>
        </div>
      )}
    </div>
  )
}
