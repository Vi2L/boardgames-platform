import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface Props {
  /** Массив цен в рублях. Меньше 2 — гистограмма не показывается. */
  prices: number[]
}

const formatRub = (v: number) => `${Math.round(v).toLocaleString('ru-RU')} ₽`

/**
 * Гистограмма распределения цен.
 *
 * Bin-size — формула Стёрджеса: `bins = ⌈log2(N) + 1⌉` (добавили +1 потому
 * что в выборке 8–20 товаров формула даёт 4–5 бинов, что норм для одной
 * страницы поиска). Для очень больших выборок (1000+) лучше Freedman-Diaconis,
 * но мы сюда столько не положим.
 */
export function PriceHistogram({ prices }: Props) {
  const data = useMemo(() => {
    if (prices.length < 2) return null

    const sorted = [...prices].sort((a, b) => a - b)
    const min = sorted[0]
    const max = sorted[sorted.length - 1]
    if (min === max) return null

    const bins = Math.ceil(Math.log2(prices.length)) + 1
    const step = (max - min) / bins
    const bucketCounts: Array<{ range: string; from: number; to: number; count: number }> = []
    for (let i = 0; i < bins; i++) {
      const from = min + step * i
      const to = i === bins - 1 ? max : from + step
      bucketCounts.push({
        range: `${formatRub(from)}–${formatRub(to)}`,
        from,
        to,
        count: 0,
      })
    }

    for (const p of prices) {
      // последний бин включает обе границы
      let idx = Math.floor((p - min) / step)
      if (idx >= bins) idx = bins - 1
      bucketCounts[idx].count += 1
    }

    return bucketCounts
  }, [prices])

  if (data === null) {
    return (
      <div className="text-sm text-gray-500 text-center py-8">
        Недостаточно данных для гистограммы
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
        <XAxis
          dataKey="range"
          tick={{ fill: '#9ca3af', fontSize: 9 }}
          interval={0}
          angle={-25}
          textAnchor="end"
          height={60}
        />
        <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} allowDecimals={false} />
        <Tooltip
          contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 12 }}
          labelStyle={{ color: '#9ca3af' }}
          formatter={(v: number) => [`${v} товаров`, 'Кол-во']}
        />
        <Bar dataKey="count">
          {data.map((_, i) => (
            <Cell key={i} fill="#8b5cf6" />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
