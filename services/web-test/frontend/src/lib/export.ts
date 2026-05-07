/**
 * Экспорт данных в файл — JSON и CSV без серверной поддержки.
 *
 * Используется в SearchPage (текущие results) и DatabasePage (страница
 * товаров). Для больших списков (>10k строк) Blob+URL.createObjectURL
 * остаётся быстрым; в крайних случаях стоит подумать о streaming, но это
 * редкий сценарий для дебаг-портала.
 */

function downloadBlob(content: BlobPart, filename: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  // setTimeout даёт браузеру время инициировать загрузку до revoke.
  setTimeout(() => {
    URL.revokeObjectURL(url)
    a.remove()
  }, 100)
}

/** Сохраняет данные как pretty-printed JSON. */
export function downloadJson(data: unknown, filename: string): void {
  const text = JSON.stringify(data, null, 2)
  downloadBlob(text, filename, 'application/json;charset=utf-8')
}

/**
 * Экранирование для CSV согласно RFC 4180:
 * - значение оборачивается в кавычки, если содержит запятую/кавычку/перевод строки;
 * - двойная кавычка внутри значения удваивается.
 *
 * Excel под Windows плохо читает UTF-8 без BOM — добавляем `﻿` в начало.
 */
function escapeCsv(value: unknown): string {
  if (value === null || value === undefined) return ''
  const str = typeof value === 'object' ? JSON.stringify(value) : String(value)
  if (/[",\n\r]/.test(str)) {
    return '"' + str.replace(/"/g, '""') + '"'
  }
  return str
}

/**
 * Сохраняет массив объектов как CSV. Колонки задаются явно — порядок
 * и переименование под пользователя; неуказанные ключи объекта игнорируются.
 */
export function downloadCsv<T extends Record<string, unknown>>(
  rows: T[],
  columns: Array<{ key: keyof T; label: string }>,
  filename: string,
): void {
  const header = columns.map(c => escapeCsv(c.label)).join(',')
  const body = rows
    .map(row => columns.map(c => escapeCsv(row[c.key])).join(','))
    .join('\r\n')
  // BOM для Excel
  const csv = '﻿' + header + '\r\n' + body + '\r\n'
  downloadBlob(csv, filename, 'text/csv;charset=utf-8')
}
