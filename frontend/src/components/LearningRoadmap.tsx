/**
 * LearningRoadmap — numbered steps with checkbox progress and per-section timeline.
 */

import { useState, useMemo, useCallback } from 'react'

interface Step {
  index:    number
  label:    string
  category: string
  action:   string
  skills:   string[]
}

function parseStep(raw: string, index: number): Step {
  const catMatch = raw.match(/\(([^)]+)\)\s*$/)
  const category = catMatch ? catMatch[1] : 'General'
  const withoutCat = catMatch ? raw.slice(0, raw.lastIndexOf('(')).trim() : raw

  let action = withoutCat
  let skillStr = ''

  const startWith = withoutCat.match(/start with\s+(.+)/)
  if (startWith) {
    skillStr = startWith[1]
    action = withoutCat.split(':')[0].trim()
  } else if (/^Learn\s+/i.test(withoutCat)) {
    skillStr = withoutCat.replace(/^Learn\s+/i, '')
    action = 'Learn'
  } else if (/^Master\s+/i.test(withoutCat)) {
    skillStr = withoutCat.replace(/^Master\s+/i, '')
    action = 'Master'
  } else if (/^Build\s+/i.test(withoutCat)) {
    action = withoutCat
    skillStr = ''
  }

  const skills = skillStr
    .replace(/\(\+\d+\s+more\)/g, '')
    .split(/,\s*|\s+and\s+/)
    .map(s => s.trim())
    .filter(s => s.length > 1)

  return { index, label: raw, category, action, skills }
}

function estimateTimeline(step: Step): string {
  const n = Math.max(step.skills.length, 1)
  if (n <= 2) return 'Est. 1–2 weeks'
  if (n <= 4) return 'Est. 2–4 weeks'
  return 'Est. 4–8 weeks'
}

const STEP_COLORS = [
  'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300',
  'bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300',
  'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300',
  'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300',
  'bg-rose-100 dark:bg-rose-900/40 text-rose-700 dark:text-rose-300',
]

interface Props {
  steps: string[]
}

export default function LearningRoadmap({ steps }: Props) {
  const parsed = useMemo(() => steps.map((s, i) => parseStep(s, i)), [steps])
  const storageKey = useMemo(
    () => `roadmap_done_${parsed.map(p => p.label).join('|').slice(0, 80)}`,
    [parsed],
  )

  const [doneIds, setDoneIds] = useState<Set<number>>(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      if (!raw) return new Set()
      const arr = JSON.parse(raw) as number[]
      return new Set(Array.isArray(arr) ? arr : [])
    } catch {
      return new Set()
    }
  })

  const toggle = useCallback(
    (idx: number) => {
      setDoneIds(prev => {
        const next = new Set(prev)
        if (next.has(idx)) next.delete(idx)
        else next.add(idx)
        try {
          localStorage.setItem(storageKey, JSON.stringify([...next]))
        } catch { /* ignore */ }
        return next
      })
    },
    [storageKey],
  )

  if (!steps.length) return null

  const completed = parsed.filter(s => doneIds.has(s.index)).length
  const total = parsed.length

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Learning roadmap</h2>
        <span className="text-xs font-semibold tabular-nums text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-3 py-1 rounded-full">
          Progress: {completed} / {total}
        </span>
      </div>

      <div className="relative">
        <div className="absolute left-4 top-5 bottom-5 w-0.5 bg-gray-200 dark:bg-gray-700 -z-0" />

        <ol className="space-y-3">
          {parsed.map((step) => {
            const chipColor = STEP_COLORS[step.index % STEP_COLORS.length]
            const isDone = doneIds.has(step.index)
            return (
              <li key={step.index} className="relative flex gap-4 pl-0">
                <div className="flex flex-col items-center shrink-0 z-10">
                  <label className="cursor-pointer select-none flex flex-col items-center gap-1">
                    <input
                      type="checkbox"
                      checked={isDone}
                      onChange={() => toggle(step.index)}
                      className="sr-only peer"
                    />
                    <span
                      className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-indigo-500 ${
                        isDone
                          ? 'bg-emerald-500 border-emerald-500 text-white line-through opacity-80'
                          : `${chipColor} border-transparent`
                      }`}
                    >
                      {isDone ? 'OK' : step.index + 1}
                    </span>
                  </label>
                </div>

                <div
                  className={`flex-1 rounded-xl border px-4 py-3 shadow-sm transition-opacity ${
                    isDone
                      ? 'border-emerald-200 dark:border-emerald-800 bg-emerald-50/30 dark:bg-emerald-900/10 opacity-75'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 flex-wrap">
                    <p className={`text-sm font-semibold text-gray-800 dark:text-gray-200 ${isDone ? 'line-through' : ''}`}>
                      {step.action !== step.label ? step.action : step.label.replace(/\([^)]+\)$/, '').trim()}
                    </p>
                    <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                      <span className={`text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full ${chipColor}`}>
                        {step.category}
                      </span>
                      <span className="text-[10px] font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">
                        {estimateTimeline(step)}
                      </span>
                    </div>
                  </div>

                  {step.skills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {step.skills.slice(0, 4).map(skill => (
                        <span
                          key={skill}
                          className="px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-xs text-gray-600 dark:text-gray-400 font-medium"
                        >
                          {skill}
                        </span>
                      ))}
                      {step.skills.length > 4 && (
                        <span className="px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-xs text-gray-500">
                          +{step.skills.length - 4} more
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </div>
    </div>
  )
}
