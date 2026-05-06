import { useEffect, useRef } from 'react'

const SSE_EVENTS = ['store-start', 'store-cache', 'http-request', 'http-response', 'store-done', 'results']

export function useSSE(
  url: string | null,
  onEvent: (event: string, data: unknown) => void,
  onError?: (err: Event) => void,
  onOpen?: () => void,
) {
  const onEventRef = useRef(onEvent)
  const onErrorRef = useRef(onError)
  const onOpenRef = useRef(onOpen)

  useEffect(() => { onEventRef.current = onEvent }, [onEvent])
  useEffect(() => { onErrorRef.current = onError }, [onError])
  useEffect(() => { onOpenRef.current = onOpen }, [onOpen])

  useEffect(() => {
    if (!url) return

    const es = new EventSource(url)

    es.onopen = () => onOpenRef.current?.()
    es.onerror = (e) => {
      onErrorRef.current?.(e)
      es.close()
    }

    const handlers: Array<[string, EventListener]> = SSE_EVENTS.map(name => {
      const handler = (e: Event) => {
        try {
          const data = JSON.parse((e as MessageEvent).data)
          onEventRef.current(name, data)
        } catch {
          // ignore parse errors
        }
      }
      es.addEventListener(name, handler)
      return [name, handler]
    })

    return () => {
      handlers.forEach(([name, handler]) => es.removeEventListener(name, handler))
      es.close()
    }
  }, [url])
}
