import type { GapAdviceStructuredOut } from '../api/client'

interface GapAdviceStructuredProps {
  data: GapAdviceStructuredOut
}

/** Strip duplicate "1." if the model numbered inside the string. */
function cleanBulletLine(s: string): string {
  return s.replace(/^\s*\d+\s*[\.\)]\s*/, '').trim()
}

/** Render simple **bold** from model output as real bold (no full markdown dep). */
function InlineBold({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
          return (
            <strong key={i} className="font-semibold text-gray-900 dark:text-gray-100">
              {part.slice(2, -2)}
            </strong>
          )
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

/** Drop malformed LLM lines that echo JSON keys into priority bullets. */
function isGarbagePriorityLine(s: string): boolean {
  const t = String(s).trim().toLowerCase()
  if (!t) return true
  return t === 'highlight_how'
}

export default function GapAdviceStructured({ data }: GapAdviceStructuredProps) {
  const rawPriority = (data.priority?.length ? data.priority : data.prioritize) ?? []
  const priorityList = rawPriority.filter(p => p && !isGarbagePriorityLine(String(p)))
  const highlightText = (data.highlight?.trim() ? data.highlight : data.highlight_how) ?? ''
  const nextStep = data.next_step?.trim() ?? ''

  const projectIdeas = data.project_ideas ?? []
  const llmLearning = (data.learning_path ?? []).filter(Boolean)

  const hasContent =
    priorityList.length ||
    highlightText ||
    nextStep ||
    data.bullet_improvements?.length ||
    data.measurable_metrics?.length ||
    projectIdeas.length > 0 ||
    llmLearning.length > 0

  if (!hasContent) return null

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {priorityList.length > 0 && (
        <div className="rounded-xl border border-indigo-200/90 dark:border-indigo-800 bg-gradient-to-br from-white to-indigo-50/40 dark:from-gray-900/90 dark:to-indigo-950/30 p-4 shadow-sm ring-1 ring-indigo-500/5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-indigo-700 dark:text-indigo-300 mb-3">
            What to tackle first
          </p>
          <ul className="space-y-3 text-sm text-gray-800 dark:text-gray-200 leading-snug">
            {priorityList.slice(0, 6).map((p, i) => (
              <li key={i} className="flex gap-3">
                <span
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-[11px] font-bold text-white shadow-sm"
                  aria-hidden
                >
                  {i + 1}
                </span>
                <span className="min-w-0">
                  <InlineBold text={cleanBulletLine(p)} />
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {highlightText && (
        <div className="rounded-xl border border-violet-200/90 dark:border-violet-800 bg-gradient-to-br from-violet-50/80 to-white dark:from-violet-950/25 dark:to-gray-900/80 p-4 shadow-sm ring-1 ring-violet-500/10">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-violet-700 dark:text-violet-300 mb-2">
            Your interview story
          </p>
          <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed">
            <InlineBold text={highlightText} />
          </p>
        </div>
      )}
      {nextStep && (
        <div className="rounded-xl border border-emerald-200/90 dark:border-emerald-800 bg-gradient-to-br from-emerald-50/70 to-white dark:from-emerald-950/20 dark:to-gray-900/80 p-4 shadow-sm ring-1 ring-emerald-500/10 sm:col-span-2 lg:col-span-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-300 mb-2">
            Do this next
          </p>
          <p className="text-sm text-gray-900 dark:text-gray-100 font-medium leading-snug">
            <InlineBold text={nextStep} />
          </p>
        </div>
      )}
      {(projectIdeas.length > 0 || llmLearning.length > 0) && (
        <div className="sm:col-span-2 lg:col-span-3 grid sm:grid-cols-2 gap-4">
          {projectIdeas.length > 0 && (
            <div className="rounded-xl border border-sky-200/90 dark:border-sky-800 bg-sky-50/50 dark:bg-sky-950/20 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-sky-800 dark:text-sky-300 mb-3">
                Portfolio projects
              </p>
              <ul className="space-y-2.5 text-sm text-gray-800 dark:text-gray-200 leading-snug">
                {projectIdeas.slice(0, 6).map((p, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-sky-500" aria-hidden />
                    <span>
                      <InlineBold text={cleanBulletLine(p)} />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {llmLearning.length > 0 && (
            <div className="rounded-xl border border-teal-200/90 dark:border-teal-800 bg-teal-50/40 dark:bg-teal-950/15 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-teal-800 dark:text-teal-300 mb-3">
                Learning roadmap
              </p>
              <ol className="space-y-2.5 text-sm text-gray-800 dark:text-gray-200 leading-snug list-none">
                {llmLearning.slice(0, 8).map((step, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="text-teal-600 dark:text-teal-400 font-mono text-xs tabular-nums w-5 shrink-0 pt-0.5">
                      {i + 1}.
                    </span>
                    <span>
                      <InlineBold text={cleanBulletLine(step)} />
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
      {(data.bullet_improvements?.length || data.measurable_metrics?.length) && (
        <div className="sm:col-span-2 lg:col-span-3 grid sm:grid-cols-2 gap-4">
          {data.bullet_improvements && data.bullet_improvements.length > 0 && (
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/90 dark:bg-gray-800/50 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400 mb-3">
                Resume lines to upgrade
              </p>
              <ul className="space-y-2 text-sm text-gray-800 dark:text-gray-200 leading-snug">
                {data.bullet_improvements.map((b, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-gray-400 dark:text-gray-500 mt-0.5">→</span>
                    <span>
                      <InlineBold text={cleanBulletLine(b)} />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.measurable_metrics && data.measurable_metrics.length > 0 && (
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/90 dark:bg-gray-800/50 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400 mb-3">
                Metrics recruiters can scan
              </p>
              <ul className="space-y-2 text-sm text-gray-800 dark:text-gray-200 leading-snug">
                {data.measurable_metrics.map((m, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-amber-500 dark:text-amber-400 mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500/80" aria-hidden />
                    <span>
                      <InlineBold text={cleanBulletLine(m)} />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
