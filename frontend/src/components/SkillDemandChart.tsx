import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import type { SkillDemandOut } from '../api/client'

interface SkillDemandChartProps {
  data: SkillDemandOut[]
  maxBars?: number
}

export default function SkillDemandChart({ data, maxBars = 15 }: SkillDemandChartProps) {
  const chartData = data.slice(0, maxBars).map((d) => ({
    name: d.skill_name.length > 18 ? d.skill_name.slice(0, 18) + '…' : d.skill_name,
    fullName: d.skill_name,
    count: d.job_count,
    pct: d.demand_percentage,
  }))

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 24, top: 8, bottom: 8 }}>
          <XAxis type="number" tick={{ fontSize: 12 }} className="text-gray-500" />
          <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
          <Tooltip
            content={({ active, payload }) =>
              active && payload?.[0] ? (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg px-3 py-2 text-sm">
                  <p className="font-medium text-gray-900 dark:text-white">{payload[0].payload.fullName}</p>
                  <p className="text-gray-600 dark:text-gray-300">Jobs: {payload[0].payload.count} · {payload[0].payload.pct.toFixed(1)}%</p>
                </div>
              ) : null
            }
          />
          <Bar dataKey="count" fill="rgb(99, 102, 241)" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
