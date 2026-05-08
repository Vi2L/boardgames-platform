/**
 * Match params: список сохранённых профилей + редактор активного.
 * Полная имплементация на задаче #12 — пока показываем существующие профили
 * read-only, чтобы оператор видел, как backend хранит конфиг.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchMatchProfiles } from '../../lib/sources'

type Props = { provider: string }

export function MatchParamsTab({ provider }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['sources', provider, 'match-profiles'],
    queryFn: () => fetchMatchProfiles(provider),
  })

  return (
    <div className="space-y-4 max-w-4xl">
      <h2 className="text-base font-semibold text-gray-100">Профили матчинга</h2>
      <p className="text-sm text-gray-400">
        Сохранённые наборы параметров матчинга (threshold, веса по
        title_ru/title_en/alias, deterministic-матч по BGG/Tesera ID).
        Редактор появится в следующей итерации.
      </p>

      {isLoading && <div className="text-gray-500 text-sm">загрузка…</div>}
      {error && <div className="text-red-400 text-sm">ошибка: {String(error)}</div>}

      {data && data.length === 0 && (
        <div className="rounded-md border border-gray-800 p-6 text-center text-sm text-gray-500">
          Профилей пока нет. Backend поддерживает их в `match_profiles`,
          UI редактора — в задаче #12.
        </div>
      )}

      {data && data.length > 0 && (
        <ul className="space-y-2">
          {data.map(p => (
            <li
              key={p.id}
              className="rounded-md border border-gray-800 p-3 bg-gray-900/40"
            >
              <div className="flex items-center justify-between mb-1">
                <div className="font-medium text-gray-100">{p.name}</div>
                {p.is_default && (
                  <span className="text-[11px] px-1.5 py-0.5 rounded bg-violet-900/50 text-violet-300">
                    default
                  </span>
                )}
              </div>
              <pre className="text-[11px] text-gray-400 font-mono whitespace-pre-wrap">
                {JSON.stringify(p.params, null, 2)}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
