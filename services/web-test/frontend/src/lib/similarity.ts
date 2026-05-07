/**
 * Простая токенизация и Jaccard-similarity для сопоставления названий товаров
 * между магазинами.
 *
 * Зачем не Левенштейн: расстояние редактирования плохо работает на длинных
 * названиях типа «Каркассон. Базовый набор. Новая редакция» — токенный
 * Jaccard устойчивее к перестановке слов и припискам.
 *
 * Минимальная длина токена 3 — чтобы «и», «в», «на», единичные цифры
 * не рисовали ложные совпадения.
 */

const STOPWORDS = new Set<string>([
  'и', 'в', 'во', 'на', 'из', 'для', 'при', 'с', 'со', 'к', 'у',
  'игра', 'настольная', 'настольной', 'настольный', 'набор',
])

/** Нормализация: lower-case, удаление диакритики и пунктуации, расщепление на токены ≥3. */
export function tokenize(input: string): Set<string> {
  const lower = input
    .toLowerCase()
    .normalize('NFKD')
    // удаление диакритики (для иностранных названий)
    .replace(/[̀-ͯ]/g, '')
    // ё → е (унификация для русских)
    .replace(/ё/g, 'е')
    // пунктуация → пробелы (включая дефисы между словами и тире)
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')

  const tokens = new Set<string>()
  for (const tok of lower.split(/\s+/)) {
    if (tok.length >= 3 && !STOPWORDS.has(tok)) {
      tokens.add(tok)
    }
  }
  return tokens
}

/** Jaccard = |A ∩ B| / |A ∪ B|, диапазон [0..1]. */
export function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0
  let intersect = 0
  for (const tok of a) if (b.has(tok)) intersect += 1
  const union = a.size + b.size - intersect
  return union === 0 ? 0 : intersect / union
}

/** Удобный helper: считает Jaccard сразу для строк. */
export function titleSimilarity(a: string, b: string): number {
  return jaccardSimilarity(tokenize(a), tokenize(b))
}
