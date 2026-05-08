/**
 * Match params: список сохранённых профилей + редактор (создать / обновить / удалить).
 *
 * Поток:
 *  - Слева — список профилей. Клик выбирает активный.
 *  - Справа — форма редактирования. Save (POST /match-profiles upsert по name).
 *  - is_default — partial UNIQUE на backend'е гарантирует ровно один дефолт.
 *  - Delete + confirm.
 *  - Кнопка «новый» сбрасывает форму.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Plus, Trash2 } from 'lucide-react'
import {
  DEFAULT_MATCH_PARAMS,
  deleteMatchProfile,
  fetchMatchProfiles,
  upsertMatchProfile,
  type MatchParams,
  type MatchProfile,
} from '../../lib/sources'
import { MatchParamsForm } from './MatchParamsForm'

type Props = { provider: string }

type Draft = {
  id: number | null
  name: string
  params: MatchParams
  is_default: boolean
}

const EMPTY_DRAFT: Draft = {
  id: null,
  name: '',
  params: DEFAULT_MATCH_PARAMS,
  is_default: false,
}

export function MatchParamsTab({ provider }: Props) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)

  const { data: profiles, isLoading, error } = useQuery({
    queryKey: ['sources', provider, 'match-profiles'],
    queryFn: () => fetchMatchProfiles(provider),
  })

  // При первой загрузке выбираем default-профиль, чтобы оператор видел не
  // пустую форму. Если default'а нет — оставляем «новый профиль».
  useEffect(() => {
    if (!profiles) return
    if (draft.id != null) return  // оператор уже выбрал
    const def = profiles.find(p => p.is_default) ?? profiles[0]
    if (def) loadIntoDraft(def)
  }, [profiles, draft.id])

  function loadIntoDraft(p: MatchProfile) {
    setDraft({
      id: p.id,
      name: p.name,
      params: p.params,
      is_default: p.is_default,
    })
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      upsertMatchProfile(provider, {
        name: draft.name.trim(),
        params: draft.params,
        is_default: draft.is_default,
      }),
    onSuccess: saved => {
      qc.invalidateQueries({ queryKey: ['sources', provider, 'match-profiles'] })
      // Привязываемся к id сохранённого, чтобы повторное Save апдейтило, а не создавало.
      setDraft(d => ({ ...d, id: saved.id }))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteMatchProfile(provider, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources', provider, 'match-profiles'] })
      setDraft(EMPTY_DRAFT)
    },
  })

  const canSave = draft.name.trim().length > 0 && !saveMutation.isPending

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[16rem_1fr] gap-6 max-w-5xl">
      {/* Список профилей */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-200">Профили</h3>
          <button
            type="button"
            onClick={() => setDraft(EMPTY_DRAFT)}
            title="Новый профиль"
            className="p-1 text-gray-400 hover:text-violet-300"
          >
            <Plus size={16} />
          </button>
        </div>

        {isLoading && <div className="text-gray-500 text-sm">загрузка…</div>}
        {error && (
          <div className="text-red-400 text-sm">ошибка: {String(error)}</div>
        )}

        <ul className="space-y-1">
          {(profiles ?? []).map(p => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => loadIntoDraft(p)}
                className={clsx(
                  'w-full text-left px-2.5 py-1.5 rounded-md text-sm flex items-center justify-between',
                  draft.id === p.id
                    ? 'bg-violet-900/40 text-violet-200'
                    : 'text-gray-300 hover:bg-gray-800/60',
                )}
              >
                <span className="truncate">{p.name}</span>
                {p.is_default && (
                  <span className="text-[10px] uppercase tracking-wide text-violet-400 ml-2 flex-shrink-0">
                    default
                  </span>
                )}
              </button>
            </li>
          ))}
          {profiles && profiles.length === 0 && (
            <li className="text-xs text-gray-500 px-2.5 py-2">
              нет сохранённых профилей
            </li>
          )}
        </ul>
      </div>

      {/* Редактор */}
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <input
            type="text"
            placeholder="имя профиля (например, «BGG-приоритет»)"
            value={draft.name}
            onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-100"
          />
          {draft.id != null && (
            <button
              type="button"
              onClick={() => {
                if (confirm(`Удалить профиль «${draft.name}»?`)) {
                  deleteMutation.mutate(draft.id!)
                }
              }}
              className="p-1.5 text-red-400 hover:bg-red-900/30 rounded"
              title="Удалить профиль"
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.is_default}
            onChange={e => setDraft(d => ({ ...d, is_default: e.target.checked }))}
          />
          <span className="text-gray-300">Дефолтный профиль провайдера</span>
        </label>

        <div className="rounded-md border border-gray-800 p-4 bg-gray-900/40">
          <MatchParamsForm
            value={draft.params}
            onChange={params => setDraft(d => ({ ...d, params }))}
          />
        </div>

        {saveMutation.error && (
          <div className="text-sm text-red-400">
            ошибка сохранения: {String(saveMutation.error)}
          </div>
        )}

        <div className="flex gap-2">
          <button
            type="button"
            disabled={!canSave}
            onClick={() => saveMutation.mutate()}
            className="px-3 py-1.5 text-sm rounded-md bg-violet-700 text-white hover:bg-violet-600 disabled:opacity-50"
          >
            {saveMutation.isPending
              ? 'Сохраняем…'
              : draft.id != null
                ? 'Обновить'
                : 'Создать'}
          </button>
          {saveMutation.isSuccess && (
            <span className="self-center text-xs text-emerald-400">сохранено</span>
          )}
        </div>
      </div>
    </div>
  )
}
