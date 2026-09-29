import type { SkillDemandOut } from '../api/client'

interface RecommendationCardsProps {
  skills: SkillDemandOut[]
  title?: string
}

export default function RecommendationCards({ skills, title = 'Prioritize these skills' }: RecommendationCardsProps) {
  if (skills.length === 0) return null

  return (
    <div>
      <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">{title}</h3>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {skills.map((s) => (
          <div
            key={s.skill_id}
            className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/20 p-4 transition-shadow hover:shadow-md"
          >
            <p className="font-medium text-gray-900 dark:text-white">{s.skill_name}</p>
            <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">
              {s.job_count > 0 ? (
                <>Demand: <span className="font-semibold">{s.demand_percentage.toFixed(1)}%</span> · {s.job_count} job{s.job_count !== 1 ? 's' : ''}</>
              ) : (
                <>Typical for this role — prioritize learning</>
              )}
            </p>
            {s.category && (
              <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{s.category}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
