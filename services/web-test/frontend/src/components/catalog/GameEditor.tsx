/**
 * GameEditor — единая форма создания и редактирования каноничной Game.
 *
 * Режим определяется prop'ом: `mode='create'` или `{mode:'edit', game}`.
 * В режиме edit slug нельзя менять (он primary identifier; редактирование
 * требует merge или ручную работу с БД).
 *
 * Минимальная клиентская валидация: slug по паттерну [a-z0-9][a-z0-9-]*,
 * title непустой. Серверные ошибки (409 на duplicate) — через toast.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { X, Save, Loader2, Plus, Pencil } from 'lucide-react'
import {
  createGame, patchGame,
  type CatalogGame, type CatalogGameDetail,
  type GameCreatePayload, type GamePatchPayload,
} from '../../lib/catalog'

type Props =
  | { mode: 'create'; onClose: () => void; onCreated?: (g: CatalogGame) => void }
  | { mode: 'edit'; game: CatalogGameDetail; onClose: () => void }

const SLUG_RE = /^[a-z0-9][a-z0-9\-]*$/

const STATUSES = ['published', 'draft', 'merged', 'rejected']

export function GameEditor(props: Props) {
  const queryClient = useQueryClient()

  // Common fields
  const [slug, setSlug]         = useState(props.mode === 'edit' ? props.game.slug : '')
  const [title, setTitle]       = useState(props.mode === 'edit' ? props.game.title : '')
  const [year, setYear]         = useState<string>(propValue('year', props))
  const [designers, setDesigners] = useState<string>(joinList('designers', props))
  const [publishers, setPublishers] = useState<string>(joinList('publishers', props))
  const [playersMin, setPlayersMin] = useState<string>(propValue('players_min', props))
  const [playersMax, setPlayersMax] = useState<string>(propValue('players_max', props))
  const [ageMin, setAgeMin]         = useState<string>(propValue('age_min', props))
  const [playMin, setPlayMin]       = useState<string>(propValue('playtime_min', props))
  const [playMax, setPlayMax]       = useState<string>(propValue('playtime_max', props))
  const [coverUrl, setCoverUrl]     = useState<string>(propValue('cover_url', props))
  const [description, setDescription] = useState<string>(propValue('description', props))
  const [bggId, setBggId]           = useState<string>(propValue('bgg_id', props))
  const [teseraId, setTeseraId]     = useState<string>(propValue('tesera_id', props))
  const [statusVal, setStatusVal]   = useState<string>(props.mode === 'edit' ? props.game.status : 'published')

  const slugInvalid = props.mode === 'create' && !!slug && !SLUG_RE.test(slug)

  const create = useMutation({
    mutationFn: (payload: GameCreatePayload) => createGame(payload),
    onSuccess: (g) => {
      toast.success(`Игра #${g.id} создана: ${g.title}`)
      queryClient.invalidateQueries({ queryKey: ['catalog', 'games'] })
      if (props.mode === 'create') props.onCreated?.(g)
      props.onClose()
    },
    onError: (e) => toast.error(`Не удалось создать: ${e}`),
  })
  const update = useMutation({
    mutationFn: (payload: GamePatchPayload) =>
      patchGame((props as { game: CatalogGameDetail }).game.id, payload),
    onSuccess: () => {
      toast.success('Игра обновлена')
      queryClient.invalidateQueries({ queryKey: ['catalog', 'games'] })
      if (props.mode === 'edit') {
        queryClient.invalidateQueries({ queryKey: ['catalog', 'game-detail', props.game.id] })
      }
      props.onClose()
    },
    onError: (e) => toast.error(`Не удалось обновить: ${e}`),
  })

  const submit = () => {
    if (!title.trim()) { toast.error('title обязателен'); return }
    const common = {
      title: title.trim(),
      year: numOrNull(year),
      designers: csvOrNull(designers),
      publishers: csvOrNull(publishers),
      players_min: numOrNull(playersMin),
      players_max: numOrNull(playersMax),
      age_min: numOrNull(ageMin),
      playtime_min: numOrNull(playMin),
      playtime_max: numOrNull(playMax),
      cover_url: strOrNull(coverUrl),
      description: strOrNull(description),
      bgg_id: numOrNull(bggId),
      tesera_id: numOrNull(teseraId),
    }

    if (props.mode === 'create') {
      if (!slug.trim()) { toast.error('slug обязателен'); return }
      if (!SLUG_RE.test(slug)) { toast.error('slug: только a-z0-9 и тире'); return }
      create.mutate({ slug: slug.trim(), ...common, source: 'manual' })
    } else {
      update.mutate({ ...common, status: statusVal })
    }
  }

  const isPending = create.isPending || update.isPending

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={props.onClose} />
      <div className="relative bg-gray-900 border border-gray-800 rounded-lg shadow-2xl w-[min(720px,100%)] max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <h2 className="text-sm font-semibold text-gray-100 flex items-center gap-2">
            {props.mode === 'create' ? <><Plus size={14} /> Новая игра</> : <><Pencil size={14} /> Редактирование</>}
          </h2>
          <button onClick={props.onClose} className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="slug" required={props.mode === 'create'}
                   invalid={slugInvalid} hint="a-z0-9 и тире">
              <input
                type="text"
                value={slug}
                onChange={e => setSlug(e.target.value)}
                disabled={props.mode === 'edit'}
                placeholder="carcassonne"
                className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100 font-mono disabled:opacity-50"
              />
            </Field>
            <Field label="title" required>
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100"
              />
            </Field>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Field label="year"><NumberInput value={year} onChange={setYear} /></Field>
            <Field label="players_min"><NumberInput value={playersMin} onChange={setPlayersMin} /></Field>
            <Field label="players_max"><NumberInput value={playersMax} onChange={setPlayersMax} /></Field>
            <Field label="age_min"><NumberInput value={ageMin} onChange={setAgeMin} /></Field>
            <Field label="playtime_min"><NumberInput value={playMin} onChange={setPlayMin} /></Field>
            <Field label="playtime_max"><NumberInput value={playMax} onChange={setPlayMax} /></Field>
          </div>

          <Field label="designers" hint="через запятую">
            <input type="text" value={designers} onChange={e => setDesigners(e.target.value)}
                   className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100" />
          </Field>
          <Field label="publishers" hint="через запятую">
            <input type="text" value={publishers} onChange={e => setPublishers(e.target.value)}
                   className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100" />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="bgg_id"><NumberInput value={bggId} onChange={setBggId} /></Field>
            <Field label="tesera_id"><NumberInput value={teseraId} onChange={setTeseraId} /></Field>
          </div>

          <Field label="cover_url">
            <input type="url" value={coverUrl} onChange={e => setCoverUrl(e.target.value)}
                   className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100 font-mono" />
          </Field>

          <Field label="description">
            <textarea value={description} onChange={e => setDescription(e.target.value)} rows={4}
                      className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100" />
          </Field>

          {props.mode === 'edit' && (
            <Field label="status">
              <select value={statusVal} onChange={e => setStatusVal(e.target.value)}
                      className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100 font-mono">
                {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
          )}
        </div>

        <div className="flex justify-end gap-2 p-3 border-t border-gray-800">
          <button type="button" onClick={props.onClose}
                  className="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 rounded">
            Отмена
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={isPending || !title.trim() || (props.mode === 'create' && (!slug.trim() || slugInvalid))}
            className="px-4 py-1.5 text-xs flex items-center gap-1.5 bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 text-white rounded"
          >
            {isPending
              ? <><Loader2 size={11} className="animate-spin" /> Сохраняем…</>
              : <><Save size={11} /> {props.mode === 'create' ? 'Создать' : 'Сохранить'}</>}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({
  label, required, invalid, hint, children,
}: {
  label: string
  required?: boolean
  invalid?: boolean
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <div className="flex items-baseline gap-2 mb-0.5">
        <span className="text-xs text-gray-400 font-mono">{label}</span>
        {required && <span className="text-[10px] text-red-400">required</span>}
        {hint && <span className="text-[10px] text-gray-500">{hint}</span>}
        {invalid && <span className="text-[10px] text-red-400">invalid</span>}
      </div>
      {children}
    </label>
  )
}

function NumberInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input type="number" value={value} onChange={e => onChange(e.target.value)}
           className="w-full px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-gray-100 font-mono" />
  )
}

// Helpers — извлечение текущих значений из props.game для edit-mode.
type EditOnlyKey = keyof Omit<CatalogGameDetail, 'id'|'slug'|'title'|'status'|'aliases'|'bgg'|'wikidata'|'created_at'|'updated_at'|'meta'>
function propValue(key: EditOnlyKey, props: Props): string {
  if (props.mode !== 'edit') return ''
  const v = (props.game as unknown as Record<string, unknown>)[key]
  return v == null ? '' : String(v)
}
function joinList(key: 'designers'|'publishers', props: Props): string {
  if (props.mode !== 'edit') return ''
  const v = props.game[key]
  return v ? v.join(', ') : ''
}
function numOrNull(s: string): number | null {
  if (!s.trim()) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}
function strOrNull(s: string): string | null {
  return s.trim() ? s.trim() : null
}
function csvOrNull(s: string): string[] | null {
  const items = s.split(',').map(x => x.trim()).filter(Boolean)
  return items.length > 0 ? items : null
}
