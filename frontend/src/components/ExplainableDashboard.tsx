import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import type { MissingSkillImpactOut } from '../api/client'

interface ExplainableDashboardProps {
  currentScore: number
  missingSkillImpacts: MissingSkillImpactOut[]
}

export default function ExplainableDashboard({ currentScore, missingSkillImpacts }: ExplainableDashboardProps) {
  if (!missingSkillImpacts?.length) return null

  const chartData = missingSkillImpacts.map((m) => ({
    name: m.skill_name.length > 20 ? m.skill_name.slice(0, 18) + '…' : m.skill_name,
    fullName: m.skill_name,
    scoreIfAdded: m.score_if_added,
    scoreDrop: m.score_drop,
    demandPct: m.demand_percentage,
    demandImpact: m.demand_penalty_impact,
  }))

  const totalDemandImpact = missingSkillImpacts.reduce(
    (sum, m) => sum + (m.demand_penalty_impact ?? 0),
    0
  )

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/50 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-800/80">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
          Explainable AI — Decision support
        </h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          How each missing skill affects your score and the gain if you add it
        </p>
      </div>
      <div className="p-4 space-y-4">
        {totalDemandImpact > 0 && (
          <div className="flex items-center gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 px-3 py-2">
            <span className="text-amber-700 dark:text-amber-300 text-sm font-medium">Demand penalty impact:</span>
            <span className="text-amber-800 dark:text-amber-200 font-bold tabular-nums">
              {totalDemandImpact.toFixed(1)} pts
            </span>
            <span className="text-xs text-amber-600 dark:text-amber-400">(score drop weighted by job demand)</span>
          </div>
        )}

        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-left text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
                <th className="py-2 pr-2 font-medium">Missing skill</th>
                <th className="py-2 px-2 font-medium text-right">Score drop</th>
                <th className="py-2 px-2 font-medium text-right">Score if added</th>
                <th className="py-2 px-2 font-medium text-right">Demand %</th>
                <th className="py-2 pl-2 font-medium text-right">Demand impact</th>
              </tr>
            </thead>
            <tbody>
              {missingSkillImpacts.map((m) => (
                <tr
                  key={m.skill_name}
                  className="border-b border-slate-100 dark:border-slate-800 last:border-0"
                >
                  <td className="py-2 pr-2 text-slate-800 dark:text-slate-200 font-medium">
                    {m.skill_name}
                  </td>
                  <td className="py-2 px-2 text-right text-red-600 dark:text-red-400 tabular-nums">
                    −{m.score_drop.toFixed(1)}
                  </td>
                  <td className="py-2 px-2 text-right text-emerald-600 dark:text-emerald-400 tabular-nums font-medium">
                    {m.score_if_added.toFixed(1)}
                  </td>
                  <td className="py-2 px-2 text-right text-slate-600 dark:text-slate-300 tabular-nums">
                    {m.demand_percentage != null ? `${m.demand_percentage.toFixed(1)}%` : '—'}
                  </td>
                  <td className="py-2 pl-2 text-right text-amber-600 dark:text-amber-400 tabular-nums">
                    {m.demand_penalty_impact != null ? m.demand_penalty_impact.toFixed(1) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
            Score improvement if you add this skill (current: {currentScore.toFixed(1)})
          </p>
          <div className="h-40 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ left: 4, right: 24, top: 4, bottom: 4 }}
              >
                <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 10 }} />
                <Tooltip
                  content={({ active, payload }) =>
                    active && payload?.[0] ? (
                      <div className="bg-white dark:bg-gray-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg px-3 py-2 text-sm">
                        <p className="font-medium text-slate-900 dark:text-white">
                          {payload[0].payload.fullName}
                        </p>
                        <p className="text-emerald-600 dark:text-emerald-400">
                          Score if added: {payload[0].payload.scoreIfAdded.toFixed(1)}
                        </p>
                        <p className="text-slate-500 dark:text-slate-400">
                          Score drop: −{payload[0].payload.scoreDrop.toFixed(1)}
                        </p>
                        {payload[0].payload.demandPct != null && (
                          <p className="text-amber-600 dark:text-amber-400">
                            Demand: {payload[0].payload.demandPct.toFixed(1)}%
                          </p>
                        )}
                      </div>
                    ) : null
                  }
                />
                <Bar dataKey="scoreIfAdded" radius={[0, 4, 4, 0]} fill="#10b981" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  )
}
