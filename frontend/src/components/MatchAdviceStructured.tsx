import type { MatchAdviceStructuredOut } from '../api/client'

interface MatchAdviceStructuredProps {
  data: MatchAdviceStructuredOut
}

export default function MatchAdviceStructured({ data }: MatchAdviceStructuredProps) {
  const priorityList = data.priority?.length ? data.priority : (data.improve_skills ?? [])
  const highlightText = (data.highlight?.trim() || data.highlights?.[0]?.trim() || '')
  const nextStep = (data.next_step?.trim() || data.bullet_improvements?.[0]?.trim() || '')

  const hasContent =
    data.fit_reason ||
    priorityList.length > 0 ||
    highlightText ||
    nextStep ||
    (data.highlights?.length ?? 0) > 0 ||
    (data.bullet_improvements?.length ?? 0) > 0 ||
    (data.rewritten_bullets?.length ?? 0) > 0 ||
    (data.measurable_metrics?.length ?? 0) > 0

  if (!hasContent) return null

  return (
    <div className="space-y-3">
      {(data.fit_level || data.fit_reason) && (
        <div className="rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50/40 dark:bg-indigo-900/20 px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-widest text-indigo-600 dark:text-indigo-400 mb-1">Fit</p>
          {data.fit_level && (
            <span className="capitalize text-sm font-semibold text-indigo-800 dark:text-indigo-200">
              {data.fit_level.replace(/_/g, ' ')}
            </span>
          )}
          {data.fit_reason && (
            <p className="text-sm text-gray-700 dark:text-gray-300 mt-1">{data.fit_reason}</p>
          )}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {priorityList.length > 0 && (
          <div className="rounded-xl border border-indigo-200 dark:border-indigo-800 bg-white dark:bg-gray-900/80 p-4 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-widest text-indigo-600 dark:text-indigo-400 mb-2">Priority</p>
            <ul className="space-y-2 text-sm text-gray-800 dark:text-gray-200">
              {priorityList.slice(0, 6).map((p, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-indigo-500 font-mono text-xs tabular-nums">{i + 1}.</span>
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {highlightText && (
          <div className="rounded-xl border border-violet-200 dark:border-violet-800 bg-violet-50/50 dark:bg-violet-900/15 p-4 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-widest text-violet-600 dark:text-violet-400 mb-2">Highlight</p>
            <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed">{highlightText}</p>
          </div>
        )}
        {nextStep && (
          <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/15 p-4 shadow-sm sm:col-span-2 lg:col-span-1">
            <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-600 dark:text-emerald-400 mb-2">Next step</p>
            <p className="text-sm text-gray-800 dark:text-gray-200 font-medium">{nextStep}</p>
          </div>
        )}
      </div>

      {data.highlights && data.highlights.length > 1 && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/40 p-4">
          <p className="text-[10px] font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400 mb-2">More highlights</p>
          <ul className="list-disc list-inside space-y-1 text-sm text-gray-700 dark:text-gray-300">
            {data.highlights.slice(1).map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      )}

      {data.bullet_improvements && data.bullet_improvements.length > 1 && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/40 p-4">
          <p className="text-[10px] font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400 mb-2">More bullet improvements</p>
          <ul className="list-disc list-inside space-y-1 text-sm text-gray-700 dark:text-gray-300">
            {data.bullet_improvements.slice(1).map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      {data.rewritten_bullets && data.rewritten_bullets.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400 mb-2">Resume bullets rewritten</p>
          <div className="space-y-2">
            {data.rewritten_bullets.map((rb, i) => (
              <div key={i} className="rounded-lg border border-indigo-100 dark:border-indigo-800 bg-white/60 dark:bg-indigo-950/30 p-2">
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">Original</p>
                <p className="text-gray-700 dark:text-gray-300">{rb.original}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5 mb-0.5">Rewritten</p>
                <p className="text-indigo-800 dark:text-indigo-200 font-medium">{rb.rewritten}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.measurable_metrics && data.measurable_metrics.length > 0 && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/40 p-4">
          <p className="text-[10px] font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400 mb-2">Suggested measurable metrics</p>
          <ul className="list-disc list-inside space-y-1 text-sm text-gray-700 dark:text-gray-300">
            {data.measurable_metrics.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
