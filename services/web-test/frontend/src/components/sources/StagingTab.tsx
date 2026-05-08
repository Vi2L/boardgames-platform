/**
 * Staging — провайдер-агностичная обёртка над PromotionPanel.
 *
 * PromotionPanel живёт в `components/catalog/` и принимает `provider` пропом
 * с дефолтом 'dicefest'. UI и поведение для Dicefest полностью идентичны
 * тому, что было раньше на `/catalog`.
 *
 * TODO (separate refactor): API-функции в `lib/catalog.ts` пока хардкодят
 * PROVIDER='dicefest' константой. Когда подключим BGA/Dicebreaker — нужно
 * параметризовать (или вынести в `lib/promotion.ts` с явным провайдером).
 * Сейчас disabled-провайдеры в ProviderSidebar отрезают неподдерживаемые
 * слаги до того, как сюда дойдёт рендер.
 */
import { PromotionPanel } from '../catalog/PromotionPanel'

type Props = { provider: string }

export function StagingTab({ provider }: Props) {
  return (
    <div className="space-y-4">
      <PromotionPanel provider={provider} />
    </div>
  )
}
