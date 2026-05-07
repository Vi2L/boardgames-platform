import { useCallback, useEffect, useState } from 'react'
import { X, ChevronLeft, ChevronRight } from 'lucide-react'

interface Props {
  /** Список URL изображений. */
  images: string[]
  /** Стартовый индекс — обычно тот, по которому пользователь кликнул в галерее. */
  initialIndex?: number
  onClose: () => void
}

/**
 * Полноэкранный просмотрщик галереи.
 *
 * Замена `gallery.slice(0, 12)` в Drawer: галерея у HobbyGames бывает
 * 30+ фото, обрезка по 12 теряла данные. Lightbox держит все, навигация —
 * клавиатурой (← / → / Esc) и кнопками.
 *
 * Замечания:
 * - z-50: выше Drawer (40), чтобы lightbox перекрывал;
 * - preventDefault на клик по картинке, чтобы не закрывать lightbox при
 *   попадании в overlay через bubbling.
 */
export function Lightbox({ images, initialIndex = 0, onClose }: Props) {
  const [index, setIndex] = useState(() =>
    Math.max(0, Math.min(initialIndex, images.length - 1)),
  )

  const next = useCallback(() => {
    setIndex(i => (i + 1) % images.length)
  }, [images.length])

  const prev = useCallback(() => {
    setIndex(i => (i - 1 + images.length) % images.length)
  }, [images.length])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') next()
      else if (e.key === 'ArrowLeft') prev()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [next, prev, onClose])

  if (images.length === 0) return null

  return (
    <div
      className="fixed inset-0 bg-black/90 z-[60] flex items-center justify-center"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Просмотр галереи"
    >
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onClose() }}
        title="Закрыть (Esc)"
        className="absolute top-4 right-4 p-2 rounded-full bg-gray-900/70 text-gray-300 hover:bg-gray-800 hover:text-gray-100"
      >
        <X size={20} />
      </button>

      {images.length > 1 && (
        <>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); prev() }}
            title="Назад (←)"
            className="absolute left-4 p-2 rounded-full bg-gray-900/70 text-gray-300 hover:bg-gray-800 hover:text-gray-100"
          >
            <ChevronLeft size={24} />
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); next() }}
            title="Вперёд (→)"
            className="absolute right-4 p-2 rounded-full bg-gray-900/70 text-gray-300 hover:bg-gray-800 hover:text-gray-100"
          >
            <ChevronRight size={24} />
          </button>
        </>
      )}

      <img
        src={images[index]}
        alt={`Изображение ${index + 1} из ${images.length}`}
        className="max-h-[90vh] max-w-[90vw] object-contain rounded shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />

      {images.length > 1 && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-gray-900/70 text-gray-300 text-sm font-mono">
          {index + 1} / {images.length}
        </div>
      )}
    </div>
  )
}
