/**
 * SuggestInput — единый input с подсказками для строк поиска /search и /catalog.
 *
 * Поведение:
 *  - При фокусе на ПУСТОЕ поле → дропдаун с «Недавние» из localStorage
 *    (через useSearchHistory).
 *  - При вводе → debounced (200мс) fetch к /api/catalog/games?q=&limit=8.
 *    Catalog умеет fuzzy-search по title + game_aliases (RU/EN), поэтому
 *    «карк» → «Каркассон» работает из коробки.
 *  - Click / Enter на selected suggestion → подставить title в input,
 *    закрыть дропдаун. Submit (полноценный поиск) делается отдельным Enter
 *    или кнопкой родителя — это договорённый UX, чтобы юзер мог дописать
 *    запрос («Каркассон + допы») перед поиском.
 *  - Submit формы (Enter без выделенной подсказки) → push в history через
 *    onSubmit-колбек родителя.
 *
 * Не оборачивает <form> — родитель сам делает форму, мы лишь рендерим input
 * и absolute-positioned dropdown. Это позволяет родителю держать кнопку
 * «Поиск» и handleSubmit как было раньше.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Search, Clock, X } from 'lucide-react'
import clsx from 'clsx'
import { listCatalogGames, type CatalogGame } from '../../lib/catalog'
import { useSearchHistory } from '../../lib/searchHistory'

interface Props {
  value: string
  onChange: (v: string) => void
  /** Вызывается на Enter (без выбранного suggestion). Родитель пушит query
   *  в history и делает реальный поиск. */
  onSubmit?: () => void
  /** Уникальный ключ для localStorage — например 'search' или 'catalog'. */
  historyKey: string
  placeholder?: string
  disabled?: boolean
  autoFocus?: boolean
  className?: string
  /** id для форм-связки label-input. */
  inputId?: string
}

const DEBOUNCE_MS = 200
const SUGGEST_LIMIT = 8

export function SuggestInput({
  value, onChange, onSubmit, historyKey,
  placeholder, disabled, autoFocus, className, inputId,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [debounced, setDebounced] = useState(value)
  const [suggestions, setSuggestions] = useState<CatalogGame[]>([])
  const [loading, setLoading] = useState(false)
  const history = useSearchHistory(historyKey)

  // Debounce ввода: дёргаем catalog-поиск только когда пользователь
  // остановился на 200мс. Без дебаунса каждый keystroke = HTTP-запрос.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [value])

  // Live-fetch при изменении debounced. Игнорируем «устаревшие» ответы
  // через cancelled-флажок — если пользователь успел напечатать ещё, не
  // показываем результат предыдущего запроса.
  useEffect(() => {
    const q = debounced.trim()
    if (!q) {
      setSuggestions([])
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    listCatalogGames(q, SUGGEST_LIMIT, 0)
      .then(r => { if (!cancelled) setSuggestions(r.items) })
      .catch(() => { if (!cancelled) setSuggestions([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [debounced])

  // Click outside — закрыть dropdown. mousedown (а не click) — чтобы
  // mousedown на самом suggestion'е успел отрендериться без потери фокуса.
  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [])

  // Объединённый список того, что показываем в дропдауне.
  // history-секция — только при пустом инпуте; suggestions — иначе.
  type Row =
    | { kind: 'history'; q: string }
    | { kind: 'game'; game: CatalogGame }
  const rows: Row[] = useMemo(() => {
    if (value.trim()) return suggestions.map(g => ({ kind: 'game', game: g } as Row))
    return history.items.map(q => ({ kind: 'history', q } as Row))
  }, [value, suggestions, history.items])

  // Когда меняется набор rows — сбрасываем selection, чтобы стрелочки
  // начинали с первой строки.
  useEffect(() => { setActive(-1) }, [rows.length])

  function pickRow(r: Row) {
    if (r.kind === 'history') onChange(r.q)
    else onChange(r.game.title)
    setOpen(false)
    setActive(-1)
    inputRef.current?.focus()
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      if (!open) { setOpen(true); return }
      e.preventDefault()
      setActive(a => Math.min(a + 1, rows.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive(a => Math.max(a - 1, -1))
    } else if (e.key === 'Enter') {
      // Если выделена подсказка — подставляем её, НЕ сабмитим. Это
      // сознательный UX: дать пользователю шанс дописать запрос
      // («Каркассон» + « + допы»). Submit — отдельный Enter без selection.
      if (active >= 0 && rows[active]) {
        e.preventDefault()
        pickRow(rows[active])
      } else if (onSubmit) {
        // Native form submit обработает родитель; здесь мы дополнительно
        // зовём onSubmit для push-в-history (родитель push'нет в свой
        // history). Не preventDefault — пусть форма всё равно отправится.
        onSubmit()
        setOpen(false)
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
      setActive(-1)
    }
  }

  const showDropdown = open && rows.length > 0

  return (
    <div ref={wrapperRef} className={clsx('relative', className)}>
      <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
      <input
        ref={inputRef}
        id={inputId}
        type="text"
        value={value}
        onChange={e => { onChange(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        autoFocus={autoFocus}
        autoComplete="off"
        className="w-full pl-9 pr-4 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 disabled:opacity-50"
      />
      {showDropdown && (
        <div className="absolute z-30 left-0 right-0 mt-1 bg-gray-900 border border-gray-700 rounded-lg shadow-xl max-h-80 overflow-y-auto">
          {value.trim() === '' && history.items.length > 0 && (
            <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-gray-500
                            flex items-center justify-between">
              <span className="flex items-center gap-1"><Clock size={10} /> Недавние</span>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); history.clear() }}
                className="text-gray-500 hover:text-gray-300"
              >очистить</button>
            </div>
          )}
          {value.trim() !== '' && (
            <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-gray-500 flex items-center gap-1">
              <span>Каталог</span>
              {loading && <span className="text-violet-400">·  загрузка</span>}
              {!loading && suggestions.length === 0 && <span>·  ничего не найдено</span>}
            </div>
          )}
          {rows.map((r, idx) => (
            <SuggestRow
              key={r.kind === 'history' ? `h:${r.q}` : `g:${r.game.id}`}
              row={r}
              active={idx === active}
              onPick={() => pickRow(r)}
              onRemove={r.kind === 'history' ? () => history.remove(r.q) : undefined}
              onMouseEnter={() => setActive(idx)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SuggestRow({
  row, active, onPick, onRemove, onMouseEnter,
}: {
  row: { kind: 'history'; q: string } | { kind: 'game'; game: CatalogGame }
  active: boolean
  onPick: () => void
  onRemove?: () => void
  onMouseEnter: () => void
}) {
  return (
    <div
      // mousedown, не click — чтобы успеть среагировать до blur инпута.
      onMouseDown={(e) => { e.preventDefault(); onPick() }}
      onMouseEnter={onMouseEnter}
      className={clsx(
        'flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer',
        active ? 'bg-violet-900/40 text-gray-100' : 'text-gray-200 hover:bg-gray-800',
      )}
    >
      {row.kind === 'history' ? (
        <>
          <Clock size={12} className="text-gray-500 flex-shrink-0" />
          <span className="flex-1 truncate">{row.q}</span>
          {onRemove && (
            <button
              type="button"
              onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); onRemove() }}
              title="Удалить"
              className="text-gray-500 hover:text-red-300"
            >
              <X size={12} />
            </button>
          )}
        </>
      ) : (
        <>
          {row.game.cover_url ? (
            <img src={row.game.cover_url} alt="" className="w-7 h-7 object-contain rounded bg-gray-950 flex-shrink-0" />
          ) : (
            <div className="w-7 h-7 rounded bg-gray-950 flex-shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <div className="truncate">
              {row.game.title}
              {row.game.title_ru && row.game.title_ru !== row.game.title && (
                <span className="text-gray-500"> · {row.game.title_ru}</span>
              )}
            </div>
            <div className="text-[10px] text-gray-500 font-mono">
              #{row.game.id}{row.game.year ? ` · ${row.game.year}` : ''}
              {row.game.kind && row.game.kind !== 'base' ? ` · ${row.game.kind}` : ''}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
