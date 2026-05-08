/**
 * Staging — провайдер-агностичная обёртка над PromotionPanel.
 *
 * Сейчас существующий PromotionPanel (services/web-test/frontend/src/components/catalog/)
 * хардкодит provider='dicefest'. На задаче #11 он переедет сюда и станет
 * принимать `provider` пропом. Пока — заглушка-ссылка на /catalog, чтобы
 * страница не была пустой.
 */
import { Link } from 'react-router-dom'

type Props = { provider: string }

export function StagingTab({ provider }: Props) {
  return (
    <div className="max-w-3xl space-y-4">
      <h2 className="text-base font-semibold text-gray-100">
        Promotion {provider} → canonical
      </h2>
      <p className="text-sm text-gray-400">
        В следующей итерации сюда переедет PromotionPanel из раздела «Каталог»
        (станет провайдер-агностичным). Пока работа с очередью раз/journal —
        на странице каталога.
      </p>
      <Link
        to="/catalog"
        className="inline-block px-3 py-1.5 text-sm rounded-md bg-violet-900/40 text-violet-200 hover:bg-violet-900/60"
      >
        Открыть в каталоге →
      </Link>
    </div>
  )
}
