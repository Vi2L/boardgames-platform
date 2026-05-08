/**
 * useSearchHistory — простой localStorage-стейт для последних N запросов
 * в одном поле ввода.
 *
 * Каждое поле использует свой `key` (например 'search' для /search и
 * 'catalog' для CatalogPage), чтобы истории не смешивались между разными
 * семантиками поиска (товары vs канонические игры).
 *
 * Reasoning по дизайну:
 *  - localStorage, не Zustand: данные нужны только в одном компоненте,
 *    persist через store был бы over-engineering.
 *  - Дедупликация: если запрос повторяется — поднимаем его в начало
 *    (LRU-семантика). Без дедупа история бы захламлялась повторами.
 *  - Trim к max-N: 10 — комфортный лимит для дропдауна, без скролла.
 *  - При SSR / без localStorage (старые приватные режимы) — fallback на
 *    in-memory, чтобы не падать. Тут window-guard проверяет это.
 */
import { useCallback, useEffect, useState } from 'react'

const STORAGE_PREFIX = 'search-history:'
const DEFAULT_MAX = 10

function read(key: string): string[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + key)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

function write(key: string, items: string[]): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(items))
  } catch {
    // Quota exceeded / private mode — игнорируем, не критично.
  }
}

export function useSearchHistory(key: string, max = DEFAULT_MAX) {
  // Initial read из localStorage. useState с функцией — чтобы read() вызвался
  // только на mount, а не на каждый render.
  const [items, setItems] = useState<string[]>(() => read(key))

  // Если key меняется (редко, но возможно) — перечитываем.
  useEffect(() => { setItems(read(key)) }, [key])

  const push = useCallback((q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
    setItems(prev => {
      // LRU: убираем дубликат (case-insensitive), вставляем в начало.
      const filtered = prev.filter(x => x.toLowerCase() !== trimmed.toLowerCase())
      const next = [trimmed, ...filtered].slice(0, max)
      write(key, next)
      return next
    })
  }, [key, max])

  const remove = useCallback((q: string) => {
    setItems(prev => {
      const next = prev.filter(x => x !== q)
      write(key, next)
      return next
    })
  }, [key])

  const clear = useCallback(() => {
    write(key, [])
    setItems([])
  }, [key])

  return { items, push, remove, clear }
}
