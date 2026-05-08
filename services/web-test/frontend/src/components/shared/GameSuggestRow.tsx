/**
 * Контент строки игры в дропдауне автоподсказок (без внешнего контейнера).
 * Используется внутри SuggestInput; может переиспользоваться в других
 * контекстах с собственным внешним div.
 *
 * Иерархия имён: RU первичное (белый), EN вторичное (серый мелкий).
 * Если title_ru = null — EN как первичное + бейдж «EN».
 */
import type { CatalogGame } from '../../lib/catalog'
import { getDisplayName } from '../../lib/catalog'

interface Props {
  game: CatalogGame
}

export function GameSuggestRow({ game }: Props) {
  const hasRu = game.title_ru !== null

  return (
    <>
      {game.cover_url
        ? <img src={game.cover_url} alt="" className="w-7 h-7 object-contain rounded bg-gray-950 flex-shrink-0" />
        : <div className="w-7 h-7 rounded bg-gray-950 flex-shrink-0" />
      }
      <div className="flex-1 min-w-0">
        {/* Строка 1: первичное название + вторичное */}
        <div className="flex items-baseline min-w-0">
          <span className="truncate">{getDisplayName(game)}</span>
          {hasRu
            ? <span className="text-[11px] text-gray-500 ml-1.5 shrink-0">{game.title}</span>
            : <span className="text-[10px] font-mono text-gray-600 border border-gray-700 rounded px-0.5 ml-1 shrink-0">EN</span>
          }
        </div>
        {/* Строка 2: технические метаданные */}
        <div className="text-[10px] text-gray-500 font-mono">
          #{game.id}{game.year ? ` · ${game.year}` : ''}
          {game.kind !== 'base' ? ` · ${game.kind}` : ''}
        </div>
      </div>
    </>
  )
}
