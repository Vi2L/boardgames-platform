/**
 * DebugPage — единая точка входа в диагностические инструменты парсеров.
 *
 * Сейчас единственная вкладка — Live Test (запуск парсеров мимо кеша).
 * Дальше сюда же добавятся: Compare cache vs live (F1.2), URL playground (F1.4),
 * Contract validator (F1.5).
 */
import { LiveTestPanel } from '../components/parsers/LiveTestPanel'

export function DebugPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-gray-100">Debug парсеров</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Live Test: запуск парсеров мимо кеша, без записи в products / request_log.
          Полезно при правке селекторов и отладке нового магазина.
        </p>
      </div>

      <LiveTestPanel />
    </div>
  )
}
