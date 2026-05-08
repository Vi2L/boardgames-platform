import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

/**
 * Видимость и ширины колонок таблицы каталога. id — стабильный ключ
 * ColumnDef (см. CatalogPage.tsx). Дефолт повторяет 6 исторически
 * захардкоженных колонок плюс title_ru (RU-название из лучшего alias-ru).
 *
 * columnSizes хранит ширину в пикселях per id. Заполняется при resize
 * через TanStack Table; при сбросе ширина возвращается к дефолту колонки.
 */
export const DEFAULT_CATALOG_COLUMNS = [
  'id', 'slug', 'title', 'title_ru', 'year', 'source', 'bgg_tesera',
] as const

interface CatalogTableStore {
  visibleColumns: string[]
  columnSizes: Record<string, number>
  setVisibleColumns: (cols: string[]) => void
  toggleColumn: (id: string) => void
  resetColumns: () => void
  showAllColumns: (allIds: string[]) => void
  setColumnSize: (id: string, size: number) => void
  resetColumnSizes: () => void
}

export const useCatalogTableStore = create<CatalogTableStore>()(persist((set) => ({
  visibleColumns: [...DEFAULT_CATALOG_COLUMNS],
  columnSizes: {},

  setVisibleColumns: (cols) => set({ visibleColumns: cols }),

  toggleColumn: (id) => set(s => ({
    visibleColumns: s.visibleColumns.includes(id)
      ? s.visibleColumns.filter(c => c !== id)
      : [...s.visibleColumns, id],
  })),

  resetColumns: () => set({ visibleColumns: [...DEFAULT_CATALOG_COLUMNS] }),

  showAllColumns: (allIds) => set({ visibleColumns: allIds }),

  setColumnSize: (id, size) => set(s => ({
    columnSizes: { ...s.columnSizes, [id]: Math.max(40, Math.round(size)) },
  })),

  resetColumnSizes: () => set({ columnSizes: {} }),
}), {
  name: 'catalog:columns',
  storage: createJSONStorage(() => localStorage),
  // v2 (2026-05): добавили title_ru в дефолтный набор и columnSizes для
  // персистентности ширин. Старые сохранения без columnSizes — берём пустой
  // объект через partialize-default, миграция не нужна.
  version: 2,
}))
