import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

/**
 * Настройки личных программ лояльности магазинов.
 *
 * Применяются на фронте поверх результатов поиска: пересчитывают
 * отображаемую цену, не меняя сырые данные парсеров.
 *
 * Стратегия HG-бонусов: для каждого товара считаем цену так, как если
 * бы весь доступный пул бонусов лёг именно на него (выбрано пользователем).
 * При покупке нескольких товаров одной корзиной суммарная скидка может
 * быть меньше — выводим дисклеймер в UI.
 */
export interface HobbyLoyalty {
  enabled: boolean
  /** 'unlim' = неограничено; число = пул бонусов в рублях. */
  bonuses: 'unlim' | number
}

export interface LavkaLoyalty {
  enabled: boolean
  /** Базовая скидка от 0 до 10. */
  percent: number
  /** Дополнительные +5 % для донов VK. */
  vkDon: boolean
}

export interface LoyaltyStore {
  /** Глобальный мастер-переключатель. */
  enabled: boolean
  hobbygames: HobbyLoyalty
  lavkaigr: LavkaLoyalty

  setEnabled: (v: boolean) => void
  setHobby: (patch: Partial<HobbyLoyalty>) => void
  setLavka: (patch: Partial<LavkaLoyalty>) => void
}

export const useLoyaltyStore = create<LoyaltyStore>()(persist((set) => ({
  enabled: true,
  hobbygames: { enabled: true, bonuses: 'unlim' },
  lavkaigr: { enabled: true, percent: 10, vkDon: true },

  setEnabled: (v) => set({ enabled: v }),
  setHobby: (patch) => set(s => ({ hobbygames: { ...s.hobbygames, ...patch } })),
  setLavka: (patch) => set(s => ({ lavkaigr: { ...s.lavkaigr, ...patch } })),
}), {
  name: 'search:loyalty',
  storage: createJSONStorage(() => localStorage),
}))
