/**
 * RunStartDialog — модалка запуска сухого прогона.
 *
 * Параметры:
 *   max_items   — пробный прогон (галочка → 10).
 *   only_year   — год листинга (для Dicefest: 2024/2025/2026; пусто → все).
 *
 * Параметры провайдер-специфичны; для других источников будут другие поля.
 * Сейчас один провайдер (Dicefest), и эти параметры подходят.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { startSourceRun } from '../../lib/sources'

type Props = {
  provider: string
  open: boolean
  onClose: () => void
}

export function RunStartDialog({ provider, open, onClose }: Props) {
  const [trial, setTrial] = useState(true)
  const [onlyYear, setOnlyYear] = useState<string>('')
  const qc = useQueryClient()

  // Сброс на каждое открытие — состояние не должно «прилипать».
  useEffect(() => {
    if (open) {
      setTrial(true)
      setOnlyYear('')
    }
  }, [open])

  const m = useMutation({
    mutationFn: () => startSourceRun(provider, {
      max_items: trial ? 10 : undefined,
      only_year: onlyYear ? parseInt(onlyYear, 10) : undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources', provider, 'runs'] })
      onClose()
    },
  })

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 border border-gray-800 rounded-lg w-full max-w-md p-5"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold text-gray-100 mb-3">
          Запуск сухого прогона
        </h3>
        <p className="text-sm text-gray-400 mb-4">
          Парсер скачает свежее состояние сайта и положит результаты в новый
          run. Staging при этом не меняется — до явного «применить».
        </p>

        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-gray-200">
            <input
              type="checkbox"
              checked={trial}
              onChange={e => setTrial(e.target.checked)}
            />
            Пробный прогон (только первые 10 slug'ов)
          </label>

          <label className="block text-sm">
            <span className="text-gray-400">Фильтр года</span>
            <select
              className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-100 text-sm"
              value={onlyYear}
              onChange={e => setOnlyYear(e.target.value)}
            >
              <option value="">все годы</option>
              <option value="2024">2024</option>
              <option value="2025">2025</option>
              <option value="2026">2026</option>
            </select>
          </label>

          {m.error && (
            <div className="text-sm text-red-400">
              ошибка: {String(m.error)}
            </div>
          )}
        </div>

        <div className="flex gap-2 justify-end mt-5">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md text-gray-300 hover:bg-gray-800"
          >
            Отмена
          </button>
          <button
            type="button"
            disabled={m.isPending}
            onClick={() => m.mutate()}
            className="px-3 py-1.5 text-sm rounded-md bg-indigo-700 text-white hover:bg-indigo-600 disabled:opacity-50"
          >
            {m.isPending ? 'Запускаем…' : 'Запустить'}
          </button>
        </div>
      </div>
    </div>
  )
}
