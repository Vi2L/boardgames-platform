/**
 * GameDetailDrawer — полная карточка игры с алиасами и satellite-данными.
 *
 * F2.1: UI-only показ. Edit-функции (CRUD алиасов) — F2.2.
 *
 * Drawer открывается справа поверх CatalogPage, не меняет URL — это
 * быстрый peek; для глубокой работы есть отдельная страница (TODO).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, Loader2, ExternalLink, Users, Clock, Calendar, Cake, Pencil, GitMerge } from 'lucide-react'
import { fetchCatalogGame } from '../../lib/catalog'
import { AliasEditor } from './AliasEditor'
import { BggCard } from './BggCard'
import { WikidataCard } from './WikidataCard'
import { GameEditor } from './GameEditor'
import { MergeDialog } from './MergeDialog'

interface Props {
  gameId: number
  onClose: () => void
}

export function GameDetailDrawer({ gameId, onClose }: Props) {
  const [editing, setEditing] = useState(false)
  const [merging, setMerging] = useState(false)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['catalog', 'game-detail', gameId],
    queryFn: () => fetchCatalogGame(gameId),
  })

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="ml-auto w-[min(900px,100vw)] h-full bg-gray-900 border-l border-gray-800 flex flex-col relative shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 flex-shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold text-gray-100 truncate">
              {data ? data.title : 'Карточка игры'}
            </span>
            <span className="text-xs font-mono text-gray-500">#{gameId}</span>
          </div>
          <div className="flex items-center gap-1">
            {data && (
              <>
                <button onClick={() => setMerging(true)} title="Объединить с другой игрой"
                        className="p-1 text-gray-400 hover:text-red-300 hover:bg-red-950/40 rounded">
                  <GitMerge size={14} />
                </button>
                <button onClick={() => setEditing(true)} title="Редактировать"
                        className="p-1 text-gray-400 hover:text-violet-300 hover:bg-violet-950/40 rounded">
                  <Pencil size={14} />
                </button>
              </>
            )}
            <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded">
              <X size={16} />
            </button>
          </div>
        </div>

        {editing && data && (
          <GameEditor mode="edit" game={data} onClose={() => setEditing(false)} />
        )}
        {merging && data && (
          <MergeDialog source={data} onClose={() => setMerging(false)} />
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-gray-500">
              <Loader2 size={18} className="animate-spin" />
            </div>
          )}
          {isError && (
            <div className="bg-red-950/50 border border-red-900/50 rounded p-3 text-sm text-red-400">
              {String(error)}
            </div>
          )}
          {data && (
            <>
              {/* Cover + meta */}
              <div className="flex gap-4">
                {data.cover_url && (
                  <img
                    src={data.cover_url}
                    alt=""
                    className="w-40 h-40 object-contain rounded bg-gray-950 border border-gray-800 flex-shrink-0"
                  />
                )}
                <div className="flex-1 min-w-0 space-y-2 text-xs">
                  <Field label="slug" value={data.slug} mono />
                  <Field label="source" value={data.source} mono />
                  <Field label="status" value={data.status} mono />
                  {data.year && <Field label="год" value={String(data.year)}
                                      icon={<Calendar size={11} />} />}
                  {(data.players_min || data.players_max) && (
                    <Field label="игроков"
                          value={`${data.players_min ?? '?'}–${data.players_max ?? '?'}`}
                          icon={<Users size={11} />} />
                  )}
                  {data.age_min && (
                    <Field label="возраст" value={`${data.age_min}+`}
                          icon={<Cake size={11} />} />
                  )}
                  {(data.playtime_min || data.playtime_max) && (
                    <Field label="время"
                          value={`${data.playtime_min ?? '?'}–${data.playtime_max ?? '?'} мин`}
                          icon={<Clock size={11} />} />
                  )}
                  {data.designers && data.designers.length > 0 && (
                    <Field label="дизайнеры" value={data.designers.join(', ')} />
                  )}
                  {data.publishers && data.publishers.length > 0 && (
                    <Field label="издатели" value={data.publishers.join(', ')} />
                  )}
                  {/* Тип игры — показываем только не-base, чтобы не шуметь */}
                  {data.kind && data.kind !== 'base' && (
                    <Field label="тип" value={data.kind} mono />
                  )}
                  {data.parent_game_id && (
                    <Field label="parent_game_id" value={`#${data.parent_game_id}`} mono />
                  )}
                  {/* Локализация в РФ */}
                  {data.ru_publisher && (
                    <Field label="издатель РФ" value={data.ru_publisher} />
                  )}
                  {data.ru_release_year && (
                    <Field label="год РФ" value={String(data.ru_release_year)} />
                  )}
                  {data.preorder_price != null && (
                    <Field
                      label="предзаказ"
                      value={`${(data.preorder_price / 100).toLocaleString('ru-RU')} ₽`}
                    />
                  )}
                </div>
              </div>

              {/* Description */}
              {data.description && (
                <Section title="Описание">
                  <div className="text-sm text-gray-300 leading-relaxed bg-gray-950 p-3 rounded
                                  max-h-48 overflow-y-auto">
                    {data.description}
                  </div>
                </Section>
              )}

              {/* Aliases (с CRUD) */}
              <Section title={`Алиасы (${data.aliases.length})`}>
                <AliasEditor gameId={data.id} aliases={data.aliases} />
              </Section>

              {/* External links */}
              <Section title="Внешние ссылки">
                <div className="flex flex-wrap gap-2 text-xs">
                  {data.bgg_id && (
                    <Link href={`https://boardgamegeek.com/boardgame/${data.bgg_id}`}
                          label={`BGG #${data.bgg_id}`} color="bg-orange-900/40 text-orange-200" />
                  )}
                  {data.tesera_id && (
                    <Link href={`https://tesera.ru/game/${data.tesera_id}/`}
                          label={`Tesera #${data.tesera_id}`} color="bg-cyan-900/40 text-cyan-200" />
                  )}
                  {/* dicefest_id — без публичного URL, у dicefest нет /id/N (только slug). */}
                  {data.dicefest_id && (
                    <span className="px-2 py-1 rounded text-xs bg-purple-900/40 text-purple-200">
                      Dicefest #{data.dicefest_id}
                    </span>
                  )}
                  {/* nastolio_id — это slug или URL (см. catalog миграция 0006) */}
                  {data.nastolio_id && (
                    <Link
                      href={
                        data.nastolio_id.startsWith('http')
                          ? data.nastolio_id
                          : `https://nastolio.ru/games/${data.nastolio_id}/`
                      }
                      label="Nastolio"
                      color="bg-emerald-900/40 text-emerald-200"
                    />
                  )}
                  {data.wikidata?.entity_id && (
                    <Link href={`https://www.wikidata.org/wiki/${data.wikidata.entity_id}`}
                          label={`Wikidata ${data.wikidata.entity_id}`} color="bg-blue-900/40 text-blue-200" />
                  )}
                  {!data.bgg_id && !data.tesera_id && !data.dicefest_id
                    && !data.nastolio_id && !data.wikidata?.entity_id && (
                    <span className="text-xs text-gray-500 italic">Нет привязок к внешним каталогам.</span>
                  )}
                </div>
              </Section>

              {/* BGG satellite */}
              {data.bgg && <BggCard bgg={data.bgg} />}

              {/* Wikidata satellite */}
              {data.wikidata && <WikidataCard wikidata={data.wikidata} />}

              {/* Meta footer */}
              <div className="text-[10px] text-gray-500 font-mono pt-2 border-t border-gray-800">
                created: {data.created_at.slice(0, 10)} · updated: {data.updated_at.slice(0, 10)}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{title}</div>
      {children}
    </div>
  )
}

function Field({
  label, value, mono = false, icon,
}: {
  label: string
  value: string
  mono?: boolean
  icon?: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-2">
      {icon && <span className="text-gray-500 flex-shrink-0">{icon}</span>}
      <span className="text-gray-500 w-20 flex-shrink-0">{label}</span>
      <span className={mono ? 'text-gray-300 font-mono' : 'text-gray-200'}>{value}</span>
    </div>
  )
}

function Link({ href, label, color }: { href: string; label: string; color: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer"
       className={`flex items-center gap-1 px-2 py-1 rounded ${color} hover:brightness-125`}>
      <ExternalLink size={11} /> {label}
    </a>
  )
}
