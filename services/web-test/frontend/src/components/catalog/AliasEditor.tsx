/**
 * AliasEditor — CRUD алиасов внутри карточки игры.
 *
 * Заменяет AliasList в edit-режиме. Структура:
 *  - inline-форма «добавить» вверху;
 *  - список существующих с inline-edit (toggle verified / language /
 *    edit alias text) и delete.
 *
 * Все мутации через TanStack Query — после успеха инвалидируем
 * ['catalog', 'game-detail', gameId], чтобы drawer переподтянул карточку.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Plus, X, Save, Pencil, Trash2, CheckCircle2, Globe, Loader2,
} from 'lucide-react'
import clsx from 'clsx'
import {
  addAlias, deleteAlias, patchAlias,
  type AliasInput, type CatalogGameAlias,
} from '../../lib/catalog'

interface Props {
  gameId: number
  aliases: CatalogGameAlias[]
}

const COMMON_LANGS = ['ru', 'en', 'de', 'fr', 'es', 'it', 'pl', 'uk']

export function AliasEditor({ gameId, aliases }: Props) {
  const queryClient = useQueryClient()
  const invalidateDetail = () =>
    queryClient.invalidateQueries({ queryKey: ['catalog', 'game-detail', gameId] })

  const create = useMutation({
    mutationFn: (payload: AliasInput) => addAlias(gameId, payload),
    onSuccess: () => { invalidateDetail(); toast.success('Алиас добавлен') },
    onError: (e) => toast.error(`Не добавлен: ${e}`),
  })

  // Сортировка — verified manual первыми, затем wikidata, bgg/tesera, auto-match.
  const order = (a: CatalogGameAlias) => {
    if (a.verified && a.source === 'manual') return 0
    if (a.source === 'manual') return 1
    if (a.source === 'wikidata') return 2
    if (a.source === 'bgg' || a.source === 'tesera') return 3
    return 4
  }
  const sorted = [...aliases].sort((a, b) => order(a) - order(b))

  return (
    <div className="space-y-2">
      <AddAliasForm
        onAdd={(payload) => create.mutate(payload)}
        isPending={create.isPending}
      />

      {sorted.length === 0 ? (
        <div className="text-xs text-gray-500 italic">Алиасов нет.</div>
      ) : (
        <div className="space-y-1">
          {sorted.map(a => (
            <AliasRow key={a.id} gameId={gameId} alias={a} onChanged={invalidateDetail} />
          ))}
        </div>
      )}
    </div>
  )
}

function AddAliasForm({
  onAdd, isPending,
}: {
  onAdd: (payload: AliasInput) => void
  isPending: boolean
}) {
  const [alias, setAlias] = useState('')
  const [language, setLanguage] = useState('ru')
  const [verified, setVerified] = useState(true)

  const submit = () => {
    if (!alias.trim()) return
    onAdd({
      alias: alias.trim(),
      source: 'manual',
      language: language || null,
      verified,
    })
    setAlias('')
  }

  return (
    <div className="bg-gray-950 border border-gray-800 rounded p-2 space-y-2">
      <div className="flex gap-2">
        <input
          type="text"
          value={alias}
          onChange={e => setAlias(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }}
          placeholder="Альтернативное название…"
          className="flex-1 px-2 py-1 text-sm bg-gray-900 border border-gray-700 rounded text-gray-100 placeholder-gray-500"
          disabled={isPending}
        />
        <button
          type="button"
          onClick={submit}
          disabled={!alias.trim() || isPending}
          className="px-3 py-1 text-xs flex items-center gap-1 bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 text-white rounded"
        >
          {isPending ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
          Добавить
        </button>
      </div>
      <div className="flex items-center gap-3 text-xs">
        <span className="text-gray-500">язык:</span>
        <div className="flex gap-1">
          {COMMON_LANGS.map(l => (
            <button
              key={l}
              type="button"
              onClick={() => setLanguage(l === language ? '' : l)}
              className={clsx('px-1.5 py-0.5 rounded font-mono uppercase',
                language === l
                  ? 'bg-indigo-900/60 text-indigo-200'
                  : 'text-gray-500 hover:text-gray-200 hover:bg-gray-800')}
            >
              {l}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1 cursor-pointer ml-auto">
          <input
            type="checkbox"
            checked={verified}
            onChange={e => setVerified(e.target.checked)}
            className="accent-emerald-500"
          />
          <span className="text-gray-400">verified</span>
        </label>
      </div>
    </div>
  )
}

function AliasRow({
  gameId, alias, onChanged,
}: {
  gameId: number
  alias: CatalogGameAlias
  onChanged: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [aliasText, setAliasText] = useState(alias.alias)
  const [language, setLanguage] = useState(alias.language ?? '')

  const update = useMutation({
    mutationFn: (payload: Partial<AliasInput>) => patchAlias(gameId, alias.id, payload),
    onSuccess: () => { onChanged(); toast.success('Алиас обновлён'); setEditing(false) },
    onError: (e) => toast.error(`Не обновлён: ${e}`),
  })
  const remove = useMutation({
    mutationFn: () => deleteAlias(gameId, alias.id),
    onSuccess: () => { onChanged(); toast.success('Алиас удалён') },
    onError: (e) => toast.error(`Не удалён: ${e}`),
  })

  const toggleVerified = () =>
    update.mutate({ verified: !alias.verified })

  if (editing) {
    return (
      <div className="bg-gray-950 border border-indigo-800 rounded p-2 space-y-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={aliasText}
            onChange={e => setAliasText(e.target.value)}
            className="flex-1 px-2 py-1 text-sm bg-gray-900 border border-gray-700 rounded text-gray-100"
            autoFocus
          />
          <input
            type="text"
            value={language}
            onChange={e => setLanguage(e.target.value)}
            placeholder="lang"
            className="w-16 px-2 py-1 text-xs font-mono bg-gray-900 border border-gray-700 rounded text-gray-100"
          />
          <button
            type="button"
            onClick={() => update.mutate({ alias: aliasText, language: language || null })}
            disabled={!aliasText.trim() || update.isPending}
            className="px-2 py-1 text-xs flex items-center gap-1 bg-emerald-700 hover:bg-emerald-600 text-white rounded"
          >
            <Save size={11} /> Save
          </button>
          <button
            type="button"
            onClick={() => { setEditing(false); setAliasText(alias.alias); setLanguage(alias.language ?? '') }}
            className="px-2 py-1 text-xs flex items-center gap-1 bg-gray-700 hover:bg-gray-600 text-white rounded"
          >
            <X size={11} />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={clsx(
      'flex items-center gap-2 px-2 py-1.5 rounded border',
      alias.verified ? 'bg-emerald-950/20 border-emerald-900/50'
                     : 'bg-gray-950 border-gray-800',
    )}>
      <span className="text-sm text-gray-100 flex-1 truncate" title={alias.alias}>
        {alias.alias}
      </span>
      {alias.language && (
        <span className="flex items-center gap-0.5 text-[10px] text-gray-500 font-mono uppercase">
          <Globe size={9} /> {alias.language}
        </span>
      )}
      <span className="text-[10px] text-gray-500 font-mono uppercase">{alias.source}</span>
      <button
        type="button"
        onClick={toggleVerified}
        disabled={update.isPending}
        title={alias.verified ? 'снять verified' : 'отметить verified'}
        className={clsx('p-1 rounded',
          alias.verified ? 'text-emerald-400 hover:bg-emerald-950/40'
                         : 'text-gray-600 hover:text-emerald-400 hover:bg-gray-800')}
      >
        <CheckCircle2 size={12} />
      </button>
      <button
        type="button"
        onClick={() => setEditing(true)}
        title="Редактировать"
        className="p-1 text-gray-500 hover:text-indigo-300 hover:bg-indigo-950/40 rounded"
      >
        <Pencil size={12} />
      </button>
      <button
        type="button"
        onClick={() => {
          if (window.confirm(`Удалить алиас «${alias.alias}»?`)) remove.mutate()
        }}
        disabled={remove.isPending}
        title="Удалить"
        className="p-1 text-gray-500 hover:text-red-400 hover:bg-red-950/40 rounded"
      >
        {remove.isPending ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
      </button>
    </div>
  )
}
