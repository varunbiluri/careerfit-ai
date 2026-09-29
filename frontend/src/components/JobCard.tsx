/**
 * JobCard — individual job listing card with per-job match badge, loading
 * state, and a hover tooltip showing match details.
 */
import { useState } from 'react'
import type { JobListOut, MatchResult } from '../api/client'
import { formatPostedAt } from '../utils/formatPostedAt'
import LoadingSpinner from './LoadingSpinner'

function cleanJobTitle(title?: string | null, fallback?: string | null): string {
  const raw = (title || fallback || '').trim()
  if (!raw) return ''
  // Remove synthetic/demo suffixes like "(Team 1)" / "(Team 2)" for cleaner UI.
  return raw.replace(/\s*\(team\s*\d+\)\s*/gi, ' ').replace(/\s{2,}/g, ' ').trim()
}

function MatchBadge({ score }: { score: number }) {
  const s = Number.isFinite(score) ? Math.min(100, Math.max(0, score)) : 0
  const color =
    s >= 70 ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300' :
    s >= 40 ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300' :
              'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300'
  const label = s < 30 ? 'Starting point' : 'Match'
  return (
    <span className={`shrink-0 text-xs font-bold tabular-nums px-2 py-0.5 rounded-full ${color}`} title={`${label}: ${s.toFixed(0)}%`}>
      {s.toFixed(0)}% {label}
    </span>
  )
}

interface Props {
  job:              JobListOut
  matchResult?:     MatchResult | null
  isLoading:        boolean
  canMatch:         boolean          // false if no resume selected
  onMatch:          () => void
  onOpenModal:      () => void       // open the detailed modal
  /** Learning loop: notify when user opens external job link */
  onJobExternalClick?: () => void
}

export default function JobCard({ job, matchResult, isLoading, canMatch, onMatch, onOpenModal, onJobExternalClick }: Props) {
  const [tooltipVisible, setTooltipVisible] = useState(false)
  const displayTitle = cleanJobTitle(job.title, job.external_id)
  const postedLabel = formatPostedAt(job.posted_at)

  const score = matchResult?.resume_score?.total_score ?? null

  return (
    <li className="relative rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm p-4 flex flex-wrap items-start justify-between gap-3 hover:shadow-md transition-shadow">
      {/* Job info */}
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold text-gray-900 dark:text-white truncate" title={displayTitle || undefined}>
            {displayTitle || 'Job listing'}
          </p>
          {score !== null && (
            <div
              className="relative"
              onMouseEnter={() => setTooltipVisible(true)}
              onMouseLeave={() => setTooltipVisible(false)}
            >
              <button type="button" onClick={onOpenModal} aria-label="View match details">
                <MatchBadge score={score} />
              </button>

              {/* Tooltip */}
              {tooltipVisible && matchResult && (
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-20 w-56 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-xl p-3 text-xs space-y-1.5 pointer-events-none">
                  <p className="font-semibold text-gray-800 dark:text-gray-200">Why this match?</p>
                  {(matchResult.matched_skills?.length ?? 0) > 0 && (
                    <p className="text-gray-600 dark:text-gray-400">
                      Matched: {(matchResult.matched_skills ?? []).slice(0, 3).join(', ')}
                      {(matchResult.matched_skills?.length ?? 0) > 3 ? ` +${(matchResult.matched_skills?.length ?? 0) - 3} more` : ''}
                    </p>
                  )}
                  {(matchResult.missing_skills?.length ?? 0) > 0 && (
                    <p className="text-gray-500 dark:text-gray-500">
                      Missing: {(matchResult.missing_skills ?? []).slice(0, 2).join(', ')}
                      {(matchResult.missing_skills?.length ?? 0) > 2 ? ` +${(matchResult.missing_skills?.length ?? 0) - 2}` : ''}
                    </p>
                  )}
                  <p className="text-indigo-600 dark:text-indigo-400 font-medium">Click to see full breakdown</p>
                </div>
              )}
            </div>
          )}
        </div>

        <p className="text-xs text-gray-500 dark:text-gray-400 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 min-w-0">
          <span className="font-medium text-gray-600 dark:text-gray-300">{job.company?.trim() || 'Company unknown'}</span>
          {job.seniority_level && (
            <>
              <span className="text-gray-300 dark:text-gray-600" aria-hidden>
                ·
              </span>
              <span>{job.seniority_level}</span>
            </>
          )}
          {postedLabel && (
            <>
              <span className="text-gray-300 dark:text-gray-600" aria-hidden>
                ·
              </span>
              <span title={new Date(job.posted_at).toLocaleString()}>Posted {postedLabel}</span>
            </>
          )}
        </p>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 shrink-0">
        {score !== null ? (
          <button
            type="button"
            onClick={onOpenModal}
            className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            View analysis
          </button>
        ) : (
          <button
            type="button"
            onClick={onMatch}
            disabled={isLoading || !canMatch}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading
              ? <><LoadingSpinner className="!h-3 !w-3 !border-white !border-r-transparent" />Matching…</>
              : 'Analyze match'}
          </button>
        )}

        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => onJobExternalClick?.()}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
            title="Open job listing"
          >
            Open
          </a>
        )}
      </div>
    </li>
  )
}
