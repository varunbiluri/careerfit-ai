/**
 * TopSkillsList — top N high-demand missing technical skills with demand bars.
 * Backend filters to learnable technical skills via local Ollama when LLM_BASE_URL is set.
 * Shows 10 by default; remaining items are revealed via "Show more".
 */
import { useState } from 'react'
import type { SkillDemandOut } from '../api/client'

/** Filter out noise: very short strings or overly long phrases */
export function isValidSkill(skill: string): boolean {
  if (!skill?.trim()) return false
  const s = skill.trim()
  if (s.length < 3) return false
  if (s.split(/\s+/).length > 5) return false
  return true
}

function getDemandColor(pct: number): string {
  if (pct >= 50) return 'bg-red-500'
  if (pct >= 25) return 'bg-amber-500'
  return 'bg-indigo-500'
}

interface Props {
  skills:      SkillDemandOut[]
  maxVisible?: number
}

export default function TopSkillsList({ skills, maxVisible = 10 }: Props) {
  const [showAll, setShowAll] = useState(false)

  const filtered = skills.filter(s => isValidSkill(s.skill_name))
  if (!filtered.length) return null

  const visible = showAll ? filtered : filtered.slice(0, maxVisible)
  const hidden  = filtered.length - maxVisible

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Top skills to learn</h2>
      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 mb-4">
        Technical skills from your latest role-filtered live postings (frequency in that slice); when Ollama is
        configured, candidates are verified by your local model.
      </p>

      <div className="space-y-3">
        {visible.map(skill => (
          <div key={skill.skill_id} className="space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-gray-800 dark:text-gray-200">{skill.skill_name}</span>
              <span className="text-xs tabular-nums font-semibold text-gray-500 dark:text-gray-400 shrink-0">
                {skill.demand_percentage > 0 || skill.job_count > 0
                  ? `${skill.demand_percentage.toFixed(0)}% demand`
                  : 'Skill gap'}
              </span>
            </div>
            {/* Demand bar */}
            <div className="h-1.5 w-full rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${getDemandColor(skill.demand_percentage)}`}
                style={{
                  width: `${skill.demand_percentage > 0 ? Math.min(skill.demand_percentage, 100) : 8}%`,
                }}
              />
            </div>
            {skill.category && (
              <p className="text-[10px] text-gray-400 dark:text-gray-500">{skill.category}</p>
            )}
          </div>
        ))}
      </div>

      {hidden > 0 && !showAll && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="mt-4 text-sm text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
        >
          Show {hidden} more skill{hidden !== 1 ? 's' : ''}
        </button>
      )}
      {showAll && filtered.length > maxVisible && (
        <button
          type="button"
          onClick={() => setShowAll(false)}
          className="mt-4 text-sm text-gray-500 dark:text-gray-400 hover:underline"
        >
          Show less
        </button>
      )}
    </div>
  )
}
