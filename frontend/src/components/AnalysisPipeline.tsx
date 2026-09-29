/**
 * Visual pipeline while gap analysis runs (backend is one request; steps are UX staging).
 */

type Props = {
  steps: readonly string[]
  activeIndex: number
  title?: string
}

export default function AnalysisPipeline({
  steps,
  activeIndex,
  title = 'Running your analysis',
}: Props) {
  return (
    <div
      className="rounded-2xl border border-indigo-200/80 dark:border-indigo-800/80 bg-gradient-to-b from-indigo-50/90 to-white dark:from-indigo-950/40 dark:to-gray-900 p-6 shadow-sm"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex items-center gap-2 mb-5">
        <span className="relative flex h-3 w-3">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500" />
        </span>
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h3>
      </div>
      <ol className="space-y-0">
        {steps.map((label, i) => {
          const done = i < activeIndex
          const current = i === activeIndex
          return (
            <li key={label} className="flex gap-3">
              <div className="flex flex-col items-center shrink-0 w-8">
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-full text-sm border-2 transition-colors ${
                    done
                      ? 'border-emerald-500 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                      : current
                        ? 'border-indigo-500 bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 ring-2 ring-indigo-500/30'
                        : 'border-gray-200 dark:border-gray-600 text-gray-400 dark:text-gray-500'
                  }`}
                  aria-hidden
                >
                  {done ? 'OK' : i + 1}
                </span>
                {i < steps.length - 1 && (
                  <span
                    className={`w-0.5 flex-1 min-h-[12px] my-0.5 rounded ${
                      done ? 'bg-emerald-500/50' : 'bg-gray-200 dark:bg-gray-700'
                    }`}
                  />
                )}
              </div>
              <div className="pb-4 pt-1 min-w-0">
                <p
                  className={`text-sm font-medium leading-snug ${
                    done
                      ? 'text-emerald-800 dark:text-emerald-200'
                      : current
                        ? 'text-indigo-900 dark:text-indigo-100'
                        : 'text-gray-500 dark:text-gray-500'
                  }`}
                >
                  {label}
                </p>
                {current && (
                  <p className="text-xs text-indigo-600/90 dark:text-indigo-400/90 mt-1.5">
                    In progress…
                  </p>
                )}
                {done && (
                  <p className="text-xs text-emerald-600/80 dark:text-emerald-400/70 mt-1">Done</p>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
