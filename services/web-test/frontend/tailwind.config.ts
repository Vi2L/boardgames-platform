import type { Config } from 'tailwindcss'
import { tokens } from './src/lib/design-tokens'

/**
 * Tailwind v3 config. Extend через token-object из `src/lib/design-tokens.ts`.
 * Это даёт:
 *   - fontFamily.sans = Inter (replaces system stack)
 *   - fontFamily.mono = JetBrains Mono
 *   - fontSize шкала 10..18px (заменяет дефолтную 12..36+)
 *   - colors.surface.{DEFAULT, elevated} как короткие алиасы
 *
 * `theme.extend` НЕ перезатирает дефолтную палитру Tailwind — все `bg-zinc-*`,
 * `text-emerald-*` и пр. продолжают работать. Старые страницы с `bg-gray-*` /
 * `bg-violet-*` тоже не сломаны: эти классы из core Tailwind v3.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: tokens.tailwind,
  },
  plugins: [],
} satisfies Config
