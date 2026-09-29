/**
 * CareerOutcomeCard — hero: free-text target role + experience, resume picker,
 * suggested role chips, fit score, and interpreted analysis metadata.
 */
import type { SkillDemandOut, DataQualityMeta, ResumeOut } from '../api/client'
import CircularScore from './CircularScore'
import LoadingSpinner from './LoadingSpinner'

export function getFitMeta(score: number) {
  if (score >= 70) return { label: 'Strong fit',   ring: 'ring-emerald-500', text: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-900/30' }
  if (score >= 40) return { label: 'Moderate fit', ring: 'ring-amber-400',   text: 'text-amber-600 dark:text-amber-400',   bg: 'bg-amber-50 dark:bg-amber-900/30'   }
  return               { label: 'Needs work',   ring: 'ring-red-400',     text: 'text-red-500 dark:text-red-400',      bg: 'bg-red-50 dark:bg-red-900/30'       }
}

function getEffortEstimate(missingCount: number): string {
  if (missingCount === 0) return 'Market ready'
  if (missingCount <= 3)  return '~2 weeks to close gap'
  if (missingCount <= 8)  return '~4–6 weeks to close gap'
  if (missingCount <= 15) return '~2–3 months to close gap'
  return '~3+ months to close gap'
}

function humanDataQuality(dq: DataQualityMeta | undefined): string | null {
  if (!dq) return null
  if (dq.quality_band === 'low') return 'Limited or offline market data — estimated fit only'
  if (dq.completeness_score < 0.4 || dq.jobs_count < 5) return 'Limited market data — results may be less accurate'
  if (!dq.is_fresh) return 'Market data may be outdated — re-analyze for fresh results'
  return `Based on ${dq.jobs_count} live job postings`
}

interface Props {
  resumes:              ResumeOut[]
  selectedResumeId:     number | ''
  /** When true, hide the dropdown and show the active resume filename (single-resume UX). */
  singleResumeMode?:    boolean
  onResumeChange:       (id: number | '') => void
  roleInput:            string
  onRoleInputChange:    (v: string) => void
  experienceInput:      string
  onExperienceInputChange: (v: string) => void
  suggestedRoles:       string[]
  onPickSuggestedRole:  (role: string) => void
  displayTargetRole:    string | null
  roleFromUser:         boolean
  displayExperienceInterpretation: string | null
  fitPercentage:        number | null
  gapPercentage:        number | null
  projectedFitPercentage?: number | null
  highDemandMissing:    SkillDemandOut[]
  missingSkillsCount:   number
  dataQuality:          DataQualityMeta | undefined
  onAnalyze:            () => void
  onUpload:             (e: React.ChangeEvent<HTMLInputElement>) => void
  isAnalyzing:          boolean
  isUploading:          boolean
  pollingMessage:       string | null
  uploadSuccess:        string | null
  uploadError:          string | null
  gapError:             string | null
}

export default function CareerOutcomeCard({
  resumes, selectedResumeId, singleResumeMode = false, onResumeChange,
  roleInput, onRoleInputChange, experienceInput, onExperienceInputChange,
  suggestedRoles, onPickSuggestedRole,
  displayTargetRole, roleFromUser, displayExperienceInterpretation,
  fitPercentage, gapPercentage, projectedFitPercentage, highDemandMissing, missingSkillsCount,
  dataQuality,
  onAnalyze, onUpload, isAnalyzing, isUploading,
  pollingMessage, uploadSuccess, uploadError, gapError,
}: Props) {
  const hasResult  = fitPercentage !== null
  const hasResumes = resumes.length > 0
  const meta       = hasResult ? getFitMeta(fitPercentage!) : null

  const roleLabel =
    displayTargetRole?.trim() ||
    roleInput.trim() ||
    'the current job market'
  const safeDemand = highDemandMissing ?? []
  const top3      = safeDemand.slice(0, 3).map(s => s.skill_name)
  const dataNote  = humanDataQuality(dataQuality)
  /** Low-confidence / thin-data UX when fit is under half the scale (percent 0–100). */
  const showEstimateHeadline = hasResult && fitPercentage !== null && fitPercentage < 50

  return (
    <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm overflow-hidden">
      <div className="flex flex-wrap items-end gap-3 px-6 py-4 border-b border-gray-100 dark:border-gray-800 bg-gray-50/60 dark:bg-gray-800/40">
        <div className="flex flex-col gap-0.5 min-w-[140px] flex-1">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">Target role</label>
          <input
            type="text"
            placeholder="e.g. ML Engineer, Data Scientist"
            value={roleInput}
            onChange={e => onRoleInputChange(e.target.value.slice(0, 100))}
            className="text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 w-full min-w-0"
          />
        </div>

        <div className="flex flex-col gap-0.5 min-w-[140px] flex-1">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">Experience</label>
          <input
            type="text"
            placeholder="e.g. Fresher / 2 years / 5+ years"
            value={experienceInput}
            onChange={e => onExperienceInputChange(e.target.value.slice(0, 100))}
            className="text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 w-full min-w-0"
          />
        </div>

        <div className="flex flex-col gap-0.5 min-w-0 flex-[1.2]">
          <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">Resume</label>
          {singleResumeMode && selectedResumeId !== '' ? (
            <div
              className="text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/80 text-gray-800 dark:text-gray-200 px-3 py-1.5 truncate"
              title={resumes.find(r => r.id === selectedResumeId)?.filename ?? undefined}
            >
              {resumes.find(r => r.id === selectedResumeId)?.filename || `Resume #${selectedResumeId}`}
            </div>
          ) : (
            <select
              value={selectedResumeId}
              onChange={e => onResumeChange(e.target.value ? Number(e.target.value) : '')}
              disabled={!hasResumes || isAnalyzing}
              className="text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 w-full"
            >
              <option value="">{hasResumes ? 'Select a resume…' : 'No resumes — upload one first'}</option>
              {resumes.map(r => <option key={r.id} value={r.id}>{r.filename || `Resume #${r.id}`}</option>)}
            </select>
          )}
        </div>

        <div className="flex items-end gap-2">
          <button
            type="button"
            onClick={onAnalyze}
            disabled={selectedResumeId === '' || isAnalyzing}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isAnalyzing && <LoadingSpinner className="!h-4 !w-4 !border-white !border-r-transparent" />}
            {isAnalyzing ? (pollingMessage ?? 'Analyzing…') : 'Analyze'}
          </button>

          <label className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer transition-colors">
            {isUploading && <LoadingSpinner className="!h-4 !w-4" />}
            {isUploading ? 'Uploading…' : 'Upload PDF'}
            <input type="file" accept=".pdf" className="hidden" onChange={onUpload} disabled={isUploading} />
          </label>
        </div>
      </div>

      {suggestedRoles.length > 0 && (
        <div className="px-6 py-3 mt-2 border-b border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500 mb-2">Suggested roles</p>
          <div className="flex flex-wrap gap-2">
            {suggestedRoles.map(r => (
              <button
                key={r}
                type="button"
                onClick={() => onPickSuggestedRole(r)}
                className="text-xs font-medium rounded-full border border-indigo-200 dark:border-indigo-800 bg-indigo-50/80 dark:bg-indigo-900/30 text-indigo-800 dark:text-indigo-200 px-3 py-1 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors"
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      )}

      {(displayTargetRole || displayExperienceInterpretation) && (
        <div className="px-6 py-2 mt-2 border-b border-gray-100 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
          {displayTargetRole && (
            <p>
              <span className="font-semibold text-gray-700 dark:text-gray-300">Target role:</span> {displayTargetRole}
              {!roleFromUser && (
                <span className="ml-1 text-[11px] text-gray-400 dark:text-gray-500">
                  (recommended based on your resume)
                </span>
              )}
            </p>
          )}
          {displayExperienceInterpretation && (
            <p><span className="font-semibold text-gray-700 dark:text-gray-300">Experience:</span> {displayExperienceInterpretation}</p>
          )}
        </div>
      )}

      {(uploadSuccess || uploadError || gapError) && (
        <div className="px-6 py-2 border-b border-gray-100 dark:border-gray-800 space-y-1">
          {uploadSuccess && <p className="text-xs text-emerald-600 dark:text-emerald-400">{uploadSuccess}</p>}
          {uploadError   && <p className="text-xs text-red-500 dark:text-red-400">{uploadError}</p>}
          {gapError      && <p className="text-xs text-red-500 dark:text-red-400">{gapError}</p>}
        </div>
      )}

      <div className="px-6 py-6 mt-2">
        {isAnalyzing && !hasResult && (
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <div className="relative">
              <div className="w-28 h-28 rounded-full border-4 border-gray-200 dark:border-gray-700 animate-pulse" />
              <div className="absolute inset-0 flex items-center justify-center">
                <LoadingSpinner className="!h-8 !w-8" />
              </div>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">{pollingMessage ?? 'Analyzing your career fit…'}</p>
          </div>
        )}

        {!isAnalyzing && !hasResult && (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <div className="h-16 w-16 rounded-full border-2 border-dashed border-gray-300 dark:border-gray-600" aria-hidden />
            <p className="text-lg font-semibold text-gray-800 dark:text-gray-200">Get your career fit score</p>
            <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm">
              Upload a resume, set your target role, and click Analyze to see how you match the market for {roleLabel}.
            </p>
          </div>
        )}

        {hasResult && meta && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-start">
            <div className="shrink-0 flex flex-col items-center gap-1 sm:items-start">
              {showEstimateHeadline ? (
                <div className="flex flex-col items-center">
                  <div
                    className="flex items-center justify-center rounded-full border-4 border-dashed border-amber-300 dark:border-amber-600 bg-amber-50/40 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200"
                    style={{ width: 120, height: 120 }}
                  >
                    <span className="text-sm font-bold tracking-wide">Est.</span>
                  </div>
                  <span className="text-xs text-gray-500 dark:text-gray-400 mt-2">Market fit</span>
                </div>
              ) : (
                <>
                  <div className="max-w-[110px] mx-auto sm:mx-0">
                    <CircularScore score={fitPercentage!} label="Market fit" size={110} />
                  </div>
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${meta.bg} ${meta.text}`}>
                    {meta.label}
                  </span>
                </>
              )}
            </div>

            <div className="flex-1 space-y-4 max-w-2xl">
              <div className="mt-2">
                {showEstimateHeadline ? (
                  <p className="text-xl font-bold text-gray-900 dark:text-white leading-snug">
                    Starting point — estimating your fit based on current skills for {roleLabel}.
                  </p>
                ) : (
                <p className="text-xl font-bold text-gray-900 dark:text-white leading-snug">
                  Starting point:{' '}
                  <span className={meta.text}>{fitPercentage!.toFixed(0)}% fit</span>
                  {' '}— strong potential to grow for {roleLabel}
                </p>
                )}
                {!showEstimateHeadline && projectedFitPercentage != null &&
                  projectedFitPercentage > fitPercentage! + 0.5 && (
                  <p className="text-sm text-indigo-600 dark:text-indigo-400 mt-2 font-medium">
                    If you learn top skills: up to ~{projectedFitPercentage.toFixed(0)}% fit
                  </p>
                )}
                {!showEstimateHeadline && (
                  <div className="flex flex-col sm:flex-row sm:items-end gap-2 sm:gap-3 mt-2">
                    <p className="text-4xl sm:text-5xl font-extrabold text-indigo-600 dark:text-indigo-400 leading-none">
                      {fitPercentage!.toFixed(0)}%
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400 sm:mb-1">
                      overall market fit for this role
                    </p>
                  </div>
                )}
                {displayTargetRole && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                    Based on your resume vs. skills and demand for "{displayTargetRole}".
                  </p>
                )}
                {!showEstimateHeadline && gapPercentage !== null && gapPercentage > 0 && (
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                    {gapPercentage.toFixed(0)}% gap to close
                  </p>
                )}
              </div>

              {safeDemand.length > 0 && (
                <div className="rounded-2xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/60 dark:bg-emerald-900/20 p-4 mt-6 space-y-1">
                  <p className="text-xs font-semibold text-emerald-800 dark:text-emerald-200 uppercase tracking-wide">Next step focus</p>
                  <p className="text-sm text-emerald-900 dark:text-emerald-100">
                    Top skill to work on: <span className="font-semibold">{safeDemand[0].skill_name}</span>
                  </p>
                  {projectedFitPercentage != null && fitPercentage != null && projectedFitPercentage > fitPercentage && (
                    <p className="text-xs text-emerald-700 dark:text-emerald-300">
                      Estimated impact: up to {Math.round(projectedFitPercentage - fitPercentage)}% higher fit.
                    </p>
                  )}
                </div>
              )}

              {top3.length > 0 && (
                <div className="rounded-2xl bg-indigo-50 dark:bg-indigo-900/25 border border-indigo-100 dark:border-indigo-800 p-4 mt-6 space-y-1 max-w-2xl">
                  <p className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase tracking-wide">Top skills to learn</p>
                  <p className="text-sm text-gray-800 dark:text-gray-200">
                    {top3.join(' · ')}
                  </p>
                </div>
              )}

              <div className="flex flex-wrap gap-4 mt-2 text-xs text-gray-500 dark:text-gray-400">
                <span>{getEffortEstimate(missingSkillsCount)}</span>
                {dataNote && <span>{dataNote}</span>}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
