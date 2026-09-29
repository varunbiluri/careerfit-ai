import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface ScorePart {
  name: string
  score: number
  weight: number
  color: string
}

interface MatchScoreBreakdownProps {
  totalScore: number
  semanticScore: number
  skillOverlapScore: number
  keywordCoverageScore: number
  weights?: { semantic: number; skill_overlap: number; keyword_coverage: number; demand_penalty?: number }
  demandPenaltyRaw?: number
  demandPenaltyPoints?: number
  uncertaintyScore?: number  // 0 = high confidence, 30 = sparse data
}

const COLORS = ['#6366f1', '#22c55e', '#eab308', '#f43f5e'] // semantic, skill, keyword, demand penalty

export default function MatchScoreBreakdown({
  totalScore,
  semanticScore,
  skillOverlapScore,
  keywordCoverageScore,
  weights = { semantic: 0.5, skill_overlap: 0.3, keyword_coverage: 0.2, demand_penalty: 0.2 },
  demandPenaltyRaw,
  demandPenaltyPoints,
  uncertaintyScore,
}: MatchScoreBreakdownProps) {
  const hasDemandPenalty = demandPenaltyPoints != null && demandPenaltyPoints !== 0
  const data: ScorePart[] = [
    { name: `Semantic (${(weights.semantic! * 100).toFixed(0)}%)`, score: semanticScore, weight: weights.semantic ?? 0.5, color: COLORS[0] },
    { name: `Skill overlap (${((weights.skill_overlap ?? 0.3) * 100).toFixed(0)}%)`, score: skillOverlapScore, weight: weights.skill_overlap ?? 0.3, color: COLORS[1] },
    { name: `Keyword (${((weights.keyword_coverage ?? 0.2) * 100).toFixed(0)}%)`, score: keywordCoverageScore, weight: weights.keyword_coverage ?? 0.2, color: COLORS[2] },
  ]
  if (hasDemandPenalty && demandPenaltyRaw != null) {
    data.push({
      name: `Demand penalty (${((weights.demand_penalty ?? 0.2) * 100).toFixed(0)}% × D)`,
      score: Math.abs(demandPenaltyPoints),
      weight: weights.demand_penalty ?? 0.2,
      color: COLORS[3],
    })
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
        Score = 0.5S + 0.3O + 0.2K − 0.2D = <span className="text-lg font-bold text-gray-900 dark:text-white">{totalScore.toFixed(1)}</span>
      </p>
      {uncertaintyScore != null && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Confidence:{' '}
          <span className={uncertaintyScore <= 10 ? 'text-emerald-600 dark:text-emerald-400' : uncertaintyScore <= 20 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'}>
            {uncertaintyScore <= 10 ? 'High' : uncertaintyScore <= 20 ? 'Medium' : 'Low'}
          </span>
          {' '}(uncertainty {uncertaintyScore.toFixed(1)}/30)
        </p>
      )}
      <div className="h-32 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
            <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 11 }} />
            <Tooltip
              content={({ active, payload }) =>
                active && payload?.[0] ? (
                  <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg px-3 py-2 text-sm">
                    <p className="font-medium text-gray-900 dark:text-white">{payload[0].payload.name}</p>
                    <p className="text-gray-600 dark:text-gray-300">
                      {payload[0].payload.name.includes('Demand') ? `Contribution: −${payload[0].payload.score.toFixed(1)} pts` : `Score: ${payload[0].payload.score.toFixed(1)}%`}
                    </p>
                  </div>
                ) : null
              }
            />
            <Bar dataKey="score" radius={[0, 4, 4, 0]}>
              {data.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
