import { useEffect, useRef, useState } from 'react'

/**
 * Имена SSE-событий, на которые подписан фронт.
 *
 * Должны совпадать с тем, что эмитит backend (app/api/search.py, app/api/suites.py).
 * Если backend начнёт эмитить новое событие — добавить сюда, иначе оно будет
 * проигнорировано (EventSource доставляет только события, на которые есть listener).
 *
 * Резерв `suite-*` нужен для фазы 4 (test suites SSE-progress).
 */
const SSE_EVENTS = [
  'store-start',
  'api-request',
  'api-response',
  'api-error',
  'store-done',
  'store-error',
  'results',
  'suite-item-start',
  'suite-item-done',
  'suite-summary',
] as const

/** Состояние соединения, доступно через возвращаемое значение useSSE. */
export type SseConnectionState = 'idle' | 'open' | 'reconnecting' | 'closed' | 'error'

/**
 * Терминальные события — после них реконнектиться не нужно (поток уже
 * дослал результат). Иначе при штатном `EventSource.onerror` после `results`
 * мы бы зря открывали ещё одно соединение.
 */
const TERMINAL_EVENTS = new Set<string>(['results', 'api-error', 'suite-summary'])

const MAX_RETRIES = 3
const BASE_DELAY_MS = 250

/**
 * Хук-обёртка над EventSource с реконнектами и indicator'ом состояния.
 *
 * Зачем нужны реконнекты: сетевой разрыв в середине SSE — частая ситуация
 * (Wi-Fi переключение, прокси, sleep). Без них пользователь видит замершую
 * шапку прогресса и думает, что портал завис.
 *
 * Стратегия: до MAX_RETRIES попыток с экспоненциальным backoff и jitter
 * (`base * 2^n * (0.5 + random)`), иначе сдаёмся и переходим в 'error'.
 */
export function useSSE(
  url: string | null,
  onEvent: (event: string, data: unknown) => void,
  onError?: (err: Event) => void,
  onOpen?: () => void,
): { connectionState: SseConnectionState } {
  const [connectionState, setConnectionState] = useState<SseConnectionState>('idle')

  // refs нужны, чтобы handler EventSource всегда видел актуальные колбэки,
  // даже если родитель пере-рендерится с новой ссылкой на onEvent (React quirk).
  const onEventRef = useRef(onEvent)
  const onErrorRef = useRef(onError)
  const onOpenRef = useRef(onOpen)

  useEffect(() => { onEventRef.current = onEvent }, [onEvent])
  useEffect(() => { onErrorRef.current = onError }, [onError])
  useEffect(() => { onOpenRef.current = onOpen }, [onOpen])

  useEffect(() => {
    if (!url) {
      setConnectionState('idle')
      return
    }

    // ── Локальное состояние одного «жизненного цикла» url ────────────────
    let retries = 0
    let receivedTerminal = false
    let isClosed = false
    let es: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (isClosed) return

      es = new EventSource(url)

      es.onopen = () => {
        retries = 0  // сброс счётчика после успешного открытия
        setConnectionState('open')
        onOpenRef.current?.()
      }

      es.onerror = (e) => {
        // EventSource в большинстве браузеров делает свой реконнект, но без
        // backoff и без потолка. Чтобы не молотить сервер при серьёзных
        // проблемах, мы сами управляем циклом: закрываем и решаем — заново или сдаваться.
        es?.close()
        es = null

        if (isClosed || receivedTerminal) {
          setConnectionState('closed')
          return
        }

        if (retries >= MAX_RETRIES) {
          setConnectionState('error')
          onErrorRef.current?.(e)
          return
        }

        const delay = BASE_DELAY_MS * Math.pow(2, retries) * (0.5 + Math.random())
        retries += 1
        setConnectionState('reconnecting')
        reconnectTimer = setTimeout(connect, delay)
      }

      // Подписка на все известные события — попытка обработать неизвестные
      // через `onmessage` бесполезна, EventSource доставляет только зарегистрированные.
      for (const name of SSE_EVENTS) {
        es.addEventListener(name, (e) => {
          try {
            const data = JSON.parse((e as MessageEvent).data)
            if (TERMINAL_EVENTS.has(name)) {
              receivedTerminal = true
            }
            onEventRef.current(name, data)
          } catch {
            // Битый JSON — пропускаем; слушатель не падает.
          }
        })
      }
    }

    connect()

    return () => {
      isClosed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      es?.close()
      setConnectionState('closed')
    }
  }, [url])

  return { connectionState }
}
