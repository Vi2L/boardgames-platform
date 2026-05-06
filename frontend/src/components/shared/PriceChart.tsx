import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Dot } from 'recharts'
import type { PricePointOut } from '../../types/api'

interface Props {
  data: PricePointOut[]
}

export function PriceChart({ data }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
        Нет истории цен
      </div>
    )
  }

  const chartData = data.map(p => ({
    date: new Date(p.fetched_at).toLocaleDateString('ru-RU', { month: 'short', day: 'numeric' }),
    price: p.price_rub,
  }))

  // Форматируем как 1 234 ₽ (с неразрывными пробелами через ru-RU локаль)
  const formatRub = (v: number) => `${v.toLocaleString('ru-RU')} ₽`

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
        <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} />
        <YAxis
          tick={{ fill: '#9ca3af', fontSize: 11 }}
          tickFormatter={formatRub}
          width={72}
        />
        <Tooltip
          contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 12 }}
          labelStyle={{ color: '#9ca3af' }}
          formatter={(v: number) => [formatRub(v), 'Цена']}
        />
        <Line
          type="monotone"
          dataKey="price"
          stroke="#8b5cf6"
          strokeWidth={2}
          dot={<Dot r={3} fill="#8b5cf6" />}
          activeDot={{ r: 5, fill: '#a78bfa' }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
