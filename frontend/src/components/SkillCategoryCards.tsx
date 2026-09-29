/**
 * SkillCategoryCards — missing skills by category with strength bands (0–20 / 20–50 / 50+).
 */

interface CategoryMeta {
  label:   string
  badge:   string
  border:  string
  bg:      string
}

/** Approximate “coverage strength” from missing count (more missing → lower %). */
function approximateStrengthPct(missingCount: number): number {
  return Math.max(0, Math.min(100, 100 - missingCount * 16))
}

function getCategoryMeta(strengthPct: number): CategoryMeta {
  if (strengthPct >= 50) {
    return {
      label:  'Strong (50%+)',
      badge:  'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300',
      border: 'border-emerald-200 dark:border-emerald-800',
      bg:     'bg-emerald-50/40 dark:bg-emerald-900/10',
    }
  }
  if (strengthPct >= 20) {
    return {
      label:  'Moderate (20–50%)',
      badge:  'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300',
      border: 'border-amber-200 dark:border-amber-800',
      bg:     'bg-amber-50/40 dark:bg-amber-900/10',
    }
  }
  return {
    label:  'Critical (0–20%)',
    badge:  'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300',
    border: 'border-red-200 dark:border-red-800',
    bg:     'bg-red-50/40 dark:bg-red-900/10',
  }
}

interface Props {
  categories: Record<string, string[]>
}

export default function SkillCategoryCards({ categories }: Props) {
  const entries = Object.entries(categories)
  if (!entries.length) return null

  const sorted = [...entries].sort((a, b) => b[1].length - a[1].length)

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Skill category insights</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {sorted.map(([category, skills]) => {
          const strengthPct = approximateStrengthPct(skills.length)
          const meta = getCategoryMeta(strengthPct)
          return (
            <div
              key={category}
              className={`rounded-xl border ${meta.border} ${meta.bg} p-4 space-y-2`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-gray-800 dark:text-gray-200">{category}</p>
                <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ${meta.badge}`}>
                  {meta.label}
                </span>
              </div>

              <p className="text-[11px] text-gray-500 dark:text-gray-400 tabular-nums">
                Estimated strength in this bucket: ~{strengthPct}%
              </p>

              <div className="flex flex-wrap gap-1.5">
                {skills.slice(0, 3).map(skill => (
                  <span
                    key={skill}
                    className="px-2 py-0.5 rounded-md bg-white/70 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 text-xs text-gray-700 dark:text-gray-300"
                  >
                    {skill}
                  </span>
                ))}
                {skills.length > 3 && (
                  <span className="px-2 py-0.5 rounded-md bg-white/70 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 text-xs text-gray-500">
                    +{skills.length - 3} more
                  </span>
                )}
              </div>

              <p className="text-xs text-gray-500 dark:text-gray-400">
                {skills.length} skill{skills.length !== 1 ? 's' : ''} missing
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}
