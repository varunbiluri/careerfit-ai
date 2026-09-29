/**
 * Dashboard — AI career advisor experience.
 *
 * Layout order (progressive disclosure):
 *  1. CareerOutcomeCard   — hero: role/level, resume filename + upload (no dropdown), fit score
 *  2. LearningRoadmap     — step-by-step skill plan
 *  3. Top Skills to learn
 *  4. AI Advice           — structured LLM guidance
 *  5. Market Insights     — collapsed by default
 *  6. Job Matches         — filtered job cards + match modal
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  resumesApi, jobsApi, analysisApi, parseApiError,
  type ResumeOut, type JobListOut, type ResumeGapOut,
  type MatchResult, type MarketTrendsOut,
  type RoleFitOut,
  type SkillTrendsEngineOut,
} from '../api/client'

// Existing components (kept unchanged)
import LoadingSpinner from '../components/LoadingSpinner'
import MatchScoreBreakdown from '../components/MatchScoreBreakdown'
import ExplainableDashboard from '../components/ExplainableDashboard'
import MatchAdviceStructured from '../components/MatchAdviceStructured'
import GapAdviceStructured from '../components/GapAdviceStructured'

// New components
import CareerOutcomeCard from '../components/CareerOutcomeCard'
import LearningRoadmap from '../components/LearningRoadmap'
import TopSkillsList from '../components/TopSkillsList'
import JobCard from '../components/JobCard'
import AgentWorkspaceOverlay from '../components/AgentWorkspaceOverlay'
import { mergeSuggestedRoles } from '../utils/suggestedRoles'
import { formatPostedAt } from '../utils/formatPostedAt'

const INITIAL_JOB_LIMIT = 5
const JOB_LIMIT_STEP = 20
const MAX_JOB_LIMIT = 100

function filterJobsByRole(jobs: JobListOut[], roleQuery: string): JobListOut[] {
  const q = roleQuery.trim().toLowerCase()
  if (!q) return jobs
  const tokens = q.split(/\s+/).filter(t => t.length > 2)
  if (tokens.length === 0) return jobs
  return jobs.filter(j => {
    const title = (j.title ?? '').toLowerCase()
    return tokens.some(t => title.includes(t))
  })
}

/** Hide job cards when employer name is missing or a generic placeholder (matches JobCard fallback). */
function hasKnownCompany(job: JobListOut): boolean {
  const c = (job.company ?? '').trim().toLowerCase()
  if (!c) return false
  if (c === 'unknown' || c === 'n/a' || c === 'na' || c === '-' || c === '—') return false
  return true
}

const isLikelyLoginPage = (title: string | null) => {
  if (!title?.trim()) return true
  const l = title.trim().toLowerCase()
  return l === 'sign in' || l === 'log in' || l === 'login' ||
         l.startsWith('sign in ') || l.startsWith('log in ') ||
         l.includes('access denied')
}

function cleanDisplayJobTitle(title?: string | null): string {
  const raw = (title || '').trim()
  if (!raw) return 'Job match'
  return raw.replace(/\s*\(team\s*\d+\)\s*/gi, ' ').replace(/\s{2,}/g, ' ').trim()
}

// ── Skeleton loader ──────────────────────────────────────────────────────────
function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-gray-700 ${className}`} />
}

// ─────────────────────────────────────────────────────────────────────────────
export default function Dashboard() {
  // ── Data ────────────────────────────────────────────────────────────────────
  const [resumes, setResumes]   = useState<ResumeOut[]>([])
  const [jobs,    setJobs]      = useState<JobListOut[]>([])
  const [dataLoading, setDataLoading] = useState(true)

  // ── Career filters ───────────────────────────────────────────────────────────
  const [selectedResumeId, setSelectedResumeId] = useState<number | ''>('')
  const [roleInput,        setRoleInput]        = useState('')
  const [experienceInput,  setExperienceInput]  = useState('')
  const [roleSuggestions,  setRoleSuggestions]  = useState<string[]>([])

  // ── Upload ──────────────────────────────────────────────────────────────────
  const [uploading,     setUploading]     = useState(false)
  const [uploadError,   setUploadError]   = useState<string | null>(null)
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null)

  // ── Gap analysis ────────────────────────────────────────────────────────────
  const [gapResult,       setGapResult]       = useState<ResumeGapOut | null>(null)
  const [gapLoading,      setGapLoading]       = useState(false)
  const [gapError,        setGapError]         = useState<string | null>(null)
  const [gapPollingMsg,   setGapPollingMsg]    = useState<string | null>(null)
  /** Gap analysis progress 0–100 from SSE `percent`; 0 = waiting for first milestone. */
  const [gapAnalyzePercent, setGapAnalyzePercent] = useState(0)
  const [gapAnalyzeStartedAt, setGapAnalyzeStartedAt] = useState<number | null>(null)
  const [etaTick, setEtaTick] = useState(0)
  /** Terminal-style lines for the full-screen progress view (upload + gap phases). */
  const [progressLogs, setProgressLogs] = useState<string[]>([])
  const [uploadPercent, setUploadPercent] = useState(0)

  // ── Job match — per-job results ──────────────────────────────────────────────
  const [matchResults,  setMatchResults]  = useState<Map<number, MatchResult>>(new Map())
  const [activeMatchId, setActiveMatchId] = useState<number | null>(null)
  const [loadingJobId,  setLoadingJobId]  = useState<number | null>(null)
  const [matchError,    setMatchError]    = useState<string | null>(null)

  // ── Market trends ───────────────────────────────────────────────────────────
  const [marketTrends,        setMarketTrends]        = useState<MarketTrendsOut | null>(null)
  const [marketTrendsLoading, setMarketTrendsLoading] = useState(false)
  const [marketTrendsError,   setMarketTrendsError]   = useState<string | null>(null)
  const [marketExpanded,      setMarketExpanded]      = useState(false)

  const [corpusRoleFits, setCorpusRoleFits] = useState<RoleFitOut[]>([])
  const [skillEngineTrends, setSkillEngineTrends] = useState<SkillTrendsEngineOut | null>(null)

  /** Jobs list fetch size; use “View more jobs” to increase (up to API max). */
  const [jobFetchLimit, setJobFetchLimit] = useState(INITIAL_JOB_LIMIT)

  const isMountedRef = useRef(true)
  const viewedMatchFeedback = useRef<Set<number>>(new Set())
  useEffect(() => () => { isMountedRef.current = false }, [])

  useEffect(() => {
    if (activeMatchId === null || selectedResumeId === '') return
    if (viewedMatchFeedback.current.has(activeMatchId)) return
    viewedMatchFeedback.current.add(activeMatchId)
    void analysisApi.jobFeedback({
      resume_id: Number(selectedResumeId),
      job_id: activeMatchId,
      action: 'viewed',
    }).catch(() => {})
  }, [activeMatchId, selectedResumeId])

  useEffect(() => {
    if (!marketExpanded) return
    void analysisApi.skillTrendsEngine({ weeks: 8, limit: 12 }).then(r => {
      if (isMountedRef.current) setSkillEngineTrends(r.data)
    }).catch(() => {
      if (isMountedRef.current) setSkillEngineTrends(null)
    })
  }, [marketExpanded])

  // ── Data loading ─────────────────────────────────────────────────────────────
  const loadData = useCallback(() => {
    setDataLoading(true)
    const jobParams =
      selectedResumeId === ''
        ? { limit: jobFetchLimit }
        : { limit: jobFetchLimit, resume_id: Number(selectedResumeId) }
    Promise.all([
      resumesApi.list().then(r => setResumes(r.data)).catch(() => setResumes([])),
      jobsApi.list(jobParams).then(r => setJobs(r.data)).catch(() => setJobs([])),
    ]).finally(() => setDataLoading(false))
  }, [selectedResumeId, jobFetchLimit])

  const loadMarketTrends = useCallback((resumeId?: number) => {
    setMarketTrendsError(null)
    setMarketTrendsLoading(true)
    analysisApi
      .marketTrends({ weeks: 8, top_emerging_n: 15, resume_id: resumeId })
      .then(r => setMarketTrends(r.data))
      .catch(() => setMarketTrendsError('Failed to load market trends'))
      .finally(() => setMarketTrendsLoading(false))
  }, [])

  useEffect(() => { loadData() }, [loadData])

  /** Upload-only UX: always bind to the newest resume when none selected or selection is stale. */
  useEffect(() => {
    if (resumes.length === 0) return
    if (selectedResumeId !== '' && resumes.some(r => r.id === selectedResumeId)) return
    const newest = [...resumes].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0]
    setSelectedResumeId(newest.id)
  }, [resumes, selectedResumeId])

  useEffect(() => {
    if (!gapLoading) {
      setGapAnalyzePercent(0)
      setGapAnalyzeStartedAt(null)
    }
  }, [gapLoading])

  useEffect(() => {
    if (!gapLoading) return
    const id = window.setInterval(() => setEtaTick(t => t + 1), 1000)
    return () => window.clearInterval(id)
  }, [gapLoading])

  /** Indeterminate-style upload bar while PDF is in flight. */
  useEffect(() => {
    if (!uploading) {
      setUploadPercent(0)
      return
    }
    const tick = window.setInterval(() => {
      setUploadPercent(p => (p >= 90 ? p : p + 2))
    }, 100)
    return () => window.clearInterval(tick)
  }, [uploading])

  useEffect(() => {
    if (selectedResumeId === '') { setMarketTrends(null); return }
    loadMarketTrends(Number(selectedResumeId))
  }, [selectedResumeId, loadMarketTrends])

  useEffect(() => {
    if (selectedResumeId === '') {
      setRoleSuggestions([])
      setCorpusRoleFits([])
      return
    }
    resumesApi
      .suggestRoles(Number(selectedResumeId))
      .then(r => setRoleSuggestions(r.data.roles ?? []))
      .catch(() => setRoleSuggestions([]))
    analysisApi
      .suggestRolesFromCorpus(Number(selectedResumeId))
      .then(r => setCorpusRoleFits(r.data))
      .catch(() => setCorpusRoleFits([]))
  }, [selectedResumeId])

  // ── Gap analysis ─────────────────────────────────────────────────────────────
  const runGapAnalysis = useCallback(
    async (resumeIdOverride?: number, opts?: { appendGapStartLog?: boolean }): Promise<boolean> => {
    const resumeId = resumeIdOverride ?? (selectedResumeId === '' ? null : Number(selectedResumeId))
    if (!resumeId) { setGapError('Please select a resume first.'); return false }

    setGapError(null); setGapResult(null); setGapLoading(true); setGapPollingMsg('Connecting…')
    setGapAnalyzePercent(0)
    setGapAnalyzeStartedAt(Date.now())
    setEtaTick(0)
    const t0 = new Date().toLocaleTimeString(undefined, {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
    const startLine = `${t0} [gap] POST /analysis/resume-gap-stream (SSE)`
    if (opts?.appendGapStartLog) {
      setProgressLogs(prev => [...prev, startLine])
    } else {
      setProgressLogs([startLine])
    }

    const effectiveRole = roleInput.trim() || undefined
    let success = false
    try {
      await analysisApi.resumeGapStream(
        resumeId,
        {
          target_role: effectiveRole,
          experience_input: experienceInput.trim() || undefined,
        },
        {
          onProgress: ev => {
            setGapAnalyzePercent(ev.percent)
            setGapPollingMsg(ev.message)
            const ts = new Date().toLocaleTimeString(undefined, {
              hour12: false,
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })
            setProgressLogs(prev => [...prev, `${ts} ${ev.message}`])
          },
          onLog: message => {
            const ts = new Date().toLocaleTimeString(undefined, {
              hour12: false,
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })
            setProgressLogs(prev => [...prev, `${ts} ${message}`])
          },
          onResult: data => {
            success = true
            setGapResult(data)
            loadData()
            setGapLoading(false)
            setGapPollingMsg(null)
            setGapAnalyzeStartedAt(null)
          },
          onError: detail => {
            setGapError(detail)
            setGapLoading(false)
            setGapPollingMsg(null)
          },
        },
      )
    } catch (err) {
      setGapError(parseApiError(err))
      setGapLoading(false)
      setGapPollingMsg(null)
      return false
    }
    return success
  },
  [selectedResumeId, loadData, roleInput, experienceInput, roleSuggestions],
  )

  // ── Upload ───────────────────────────────────────────────────────────────────
  const handleResumeUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setUploadError(null); setUploadSuccess(null); setUploading(true)
    setProgressLogs([
      `${new Date().toLocaleTimeString(undefined, { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })} [upload] POST /resumes (multipart PDF)`,
    ])

    try {
      const res = await resumesApi.upload(file)
      const { id, skill_names, ai_summary } = res.data
      const count = skill_names?.length ?? 0
      const tu = new Date().toLocaleTimeString(undefined, {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
      setProgressLogs(prev => [
        ...prev,
        `${tu} [upload] OK — resume_id=${id}, ${count} skills${ai_summary ? ', AI summary' : ''}`,
      ])
      setUploadPercent(100)
      setSelectedResumeId(id)
      loadData()
      setUploadSuccess(`${count} skills extracted${ai_summary ? ' · AI summary ready' : ''}. Analyzing…`)
      const ok = await runGapAnalysis(id, { appendGapStartLog: true })
      setUploadSuccess(ok ? `Analysis complete · ${count} skills found` : `Uploaded · analyzing your resume...`)
      loadData()
    } catch (err) { setUploadError(parseApiError(err)) }
    finally       { setUploading(false) }
  }

  // ── Job match ────────────────────────────────────────────────────────────────
  const runMatch = async (jobId: number, _jobTitle: string | null) => {
    if (selectedResumeId === '') { setMatchError('Select a resume first.'); return }
    setMatchError(null); setLoadingJobId(jobId)
    try {
      const res = await analysisApi.match(jobId, selectedResumeId as number)
      setMatchResults(prev => new Map(prev).set(jobId, res.data))
      setActiveMatchId(jobId)
    } catch (err) { setMatchError(parseApiError(err)); setActiveMatchId(jobId) }
    finally       { setLoadingJobId(null) }
  }

  const closeModal = () => { setActiveMatchId(null); setMatchError(null) }

  // ── Derived data ─────────────────────────────────────────────────────────────
  const visibleJobs = filterJobsByRole(
    jobs.filter(j => !isLikelyLoginPage(j.title) && hasKnownCompany(j)),
    roleInput,
  )
  const hasResume = selectedResumeId !== ''

  const displaySuggestedRoles = useMemo(
    () => mergeSuggestedRoles(roleInput, roleSuggestions, gapResult?.suggested_roles),
    [roleInput, roleSuggestions, gapResult?.suggested_roles],
  )

  const canLoadMoreJobs =
    !dataLoading && jobs.length >= jobFetchLimit && jobFetchLimit < MAX_JOB_LIMIT

  const showAgentWorkspace = uploading || gapLoading

  const analyzeEtaSeconds = useMemo(() => {
    if (!gapLoading || gapAnalyzePercent < 3 || gapAnalyzePercent >= 99 || gapAnalyzeStartedAt == null)
      return null
    const elapsed = Date.now() - gapAnalyzeStartedAt
    const totalEst = (elapsed * 100) / gapAnalyzePercent
    return Math.max(0, Math.round((totalEst - elapsed) / 1000))
  }, [gapLoading, gapAnalyzePercent, gapAnalyzeStartedAt, etaTick])

  // Dedicated full-screen workspace (not a translucent layer over the dashboard).
  const analyzePercent = Math.min(100, Math.max(0, gapAnalyzePercent))

  if (showAgentWorkspace) {
    return (
      <AgentWorkspaceOverlay
        uploading={uploading}
        analyzing={gapLoading}
        uploadPercent={uploadPercent}
        analyzePercent={analyzePercent}
        analyzeEtaSeconds={analyzeEtaSeconds}
        statusLine={gapPollingMsg}
        logs={progressLogs}
      />
    )
  }

  const handleResumeSelectionChange = (id: number | '') => {
    setSelectedResumeId(id)
    if (id === '') {
      setGapResult(null)
      setRoleSuggestions([])
      setJobs([])
    }
  }

  const activeMatch = activeMatchId !== null ? matchResults.get(activeMatchId) ?? null : null
  const activeModalJob = activeMatchId !== null ? jobs.find(j => j.id === activeMatchId) : undefined
  const modalCompany = activeModalJob?.company?.trim() ?? ''
  const modalPostedLabel = activeModalJob ? formatPostedAt(activeModalJob.posted_at) : null

  // ─────────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6 pb-16">
      {!hasResume && (
        <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-8 flex flex-col items-center justify-center text-center py-12">
          <p className="text-lg font-semibold text-gray-900 dark:text-white">
            Upload your resume to get started
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Analyze your skills and match with the job market
          </p>
          <label className="mt-5 inline-flex items-center gap-1.5 rounded-lg border border-gray-300 dark:border-gray-600 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer transition-colors">
            {uploading && <LoadingSpinner className="!h-4 !w-4" />}
            {uploading ? 'Uploading…' : 'Upload PDF'}
            <input type="file" accept=".pdf" className="hidden" onChange={handleResumeUpload} disabled={uploading} />
          </label>
          {uploadSuccess && <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-3">{uploadSuccess}</p>}
          {uploadError && <p className="text-xs text-red-500 dark:text-red-400 mt-3">{uploadError}</p>}
        </div>
      )}

      {hasResume && (
      <>
      {/* ── 1. HERO ──────────────────────────────────────────────────────────── */}
      <CareerOutcomeCard
        resumes={resumes}
        selectedResumeId={selectedResumeId}
        singleResumeMode
        onResumeChange={handleResumeSelectionChange}
        roleInput={roleInput}
        onRoleInputChange={setRoleInput}
        experienceInput={experienceInput}
        onExperienceInputChange={setExperienceInput}
        suggestedRoles={displaySuggestedRoles}
        onPickSuggestedRole={setRoleInput}
        displayTargetRole={gapResult?.target_role ?? null}
        roleFromUser={!!roleInput.trim()}
        displayExperienceInterpretation={gapResult?.experience_interpretation ?? null}
        fitPercentage={gapResult?.fit_percentage ?? null}
        gapPercentage={gapResult?.gap_percentage ?? null}
        projectedFitPercentage={gapResult?.projected_fit_percentage ?? null}
        highDemandMissing={gapResult?.high_demand_missing_skills ?? []}
        missingSkillsCount={gapResult?.missing_skills?.length ?? 0}
        dataQuality={gapResult?.data_quality}
        onAnalyze={() => runGapAnalysis()}
        onUpload={handleResumeUpload}
        isAnalyzing={gapLoading}
        isUploading={uploading}
        pollingMessage={gapPollingMsg}
        uploadSuccess={uploadSuccess}
        uploadError={uploadError}
        gapError={gapError}
      />

      {corpusRoleFits.length > 0 && (
        <div className="rounded-2xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50/40 dark:bg-indigo-900/20 p-5">
          <h3 className="text-sm font-semibold text-indigo-900 dark:text-indigo-200 mb-3">
            Recommended roles for you
          </h3>
          <ul className="space-y-3">
            {corpusRoleFits.map((r) => (
              <li
                key={r.role}
                className="rounded-xl border border-indigo-200/80 dark:border-indigo-800/80 bg-white/90 dark:bg-gray-900/80 px-3 py-2.5"
              >
                <button
                  type="button"
                  onClick={() => setRoleInput(r.role)}
                  className="text-left w-full"
                >
                  <span className="text-sm font-medium text-indigo-900 dark:text-indigo-100">
                    {r.role}
                  </span>
                  <span className="ml-2 tabular-nums text-sm text-indigo-500 dark:text-indigo-400">
                    {r.fit}% fit
                  </span>
                </button>
                {r.fit_reason ? (
                  <p className="text-xs text-gray-600 dark:text-gray-400 mt-1.5 leading-relaxed pl-0.5">
                    {r.fit_reason}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── 2–5. ANALYSIS RESULTS ────────────────────────────────────────────── */}
      {gapResult && (
        <>
          {(gapResult.job_fetch_notice ||
            gapResult.data_quality?.quality_band === 'low') && (
            <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/80 dark:bg-amber-900/25 px-4 py-3 text-sm text-amber-950 dark:text-amber-100">
              {gapResult.job_fetch_notice ||
                'Limited live data — results are estimated.'}
            </div>
          )}

          {gapResult.best_next_action && (
            <div className="rounded-2xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/20 p-5 space-y-2">
              <h3 className="text-sm font-semibold text-emerald-900 dark:text-emerald-200">Recommended next step</h3>
              <p className="text-xs font-medium uppercase tracking-wide text-emerald-700/80 dark:text-emerald-300/80">
                {gapResult.best_next_action.type.replace(/_/g, ' ')}
              </p>
              <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed">
                {gapResult.best_next_action.reason}
              </p>
              <p className="text-xs text-emerald-800 dark:text-emerald-300 tabular-nums">
                Estimated impact: up to ~{gapResult.best_next_action.expected_impact_percent}% fit lift (heuristic)
              </p>
            </div>
          )}

          {/* 2. Learning Roadmap */}
          {(gapResult.learning_path?.length ?? 0) > 0 && (
            <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
              <LearningRoadmap steps={gapResult.learning_path!} />
            </div>
          )}

          {(gapResult.learning_path?.length ?? 0) === 0 &&
            (gapResult.high_demand_missing_skills?.length ?? 0) === 0 &&
            typeof gapResult.fit_percentage === 'number' && (
            <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 text-sm text-gray-700 dark:text-gray-300">
              <p className="font-medium text-gray-900 dark:text-white mb-1">Analysis summary</p>
              <p>
                Market fit <strong className="tabular-nums">{Math.round(gapResult.fit_percentage)}%</strong>
                {gapResult.gap_percentage != null && (
                  <> — gap to close <span className="tabular-nums">{Math.round(gapResult.gap_percentage)}%</span></>
                )}
                .
              </p>
              {(gapResult.missing_skills?.length ?? 0) > 0 && (
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  {(gapResult.missing_skills ?? []).slice(0, 10).join(', ')}
                  {(gapResult.missing_skills?.length ?? 0) > 10 ? '…' : ''}
                </p>
              )}
            </div>
          )}

          {/* 3. Top skills to learn (demand-weighted) */}
          {(gapResult.high_demand_missing_skills?.length ?? 0) > 0 && (
            <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
              <TopSkillsList skills={gapResult.high_demand_missing_skills ?? []} maxVisible={10} />
            </div>
          )}

          {/* 4. AI Advice */}
          {(gapResult.ai_advice_structured || gapResult.ai_advice) && (
            <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">AI career advice</h2>
              {gapResult.ai_advice_structured
                ? <GapAdviceStructured data={gapResult.ai_advice_structured} />
                : <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{gapResult.ai_advice}</p>
              }
            </div>
          )}
        </>
      )}

      {/* ── 5. MARKET INSIGHTS (collapsible) ──────────────────────────────────── */}
      <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
        <button
          type="button"
          onClick={() => setMarketExpanded(x => !x)}
          className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
        >
          <span className="text-base font-semibold text-gray-900 dark:text-white">
            Market insights
          </span>
          <span className="text-gray-400 text-sm">{marketExpanded ? 'Hide' : 'Show'}</span>
        </button>

        {marketExpanded && (
          <div className="px-6 pb-6 border-t border-gray-100 dark:border-gray-800 pt-4">
            {skillEngineTrends && (skillEngineTrends.fastest_growing_skills.length > 0 || skillEngineTrends.declining_skills.length > 0) && (
              <div className="grid sm:grid-cols-2 gap-4 mb-6">
                {skillEngineTrends.fastest_growing_skills.length > 0 && (
                  <div>
                    <p className="text-sm font-semibold text-emerald-700 dark:text-emerald-400 mb-2">Fastest-growing skills</p>
                    <ul className="text-xs space-y-1 text-gray-700 dark:text-gray-300">
                      {skillEngineTrends.fastest_growing_skills.slice(0, 8).map(s => (
                        <li key={s.skill_id}>{s.skill_name} <span className="text-emerald-600">+{s.weekly_growth_pct ?? 0}%</span></li>
                      ))}
                    </ul>
                  </div>
                )}
                {skillEngineTrends.declining_skills.length > 0 && (
                  <div>
                    <p className="text-sm font-semibold text-red-600 dark:text-red-400 mb-2">Declining (week-over-week)</p>
                    <ul className="text-xs space-y-1 text-gray-700 dark:text-gray-300">
                      {skillEngineTrends.declining_skills.slice(0, 8).map(s => (
                        <li key={s.skill_id}>{s.skill_name} <span className="text-red-500">{s.weekly_growth_pct}%</span></li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {marketTrendsLoading && (
              <div className="flex items-center gap-2 text-sm text-gray-500"><LoadingSpinner /><span>Loading trends…</span></div>
            )}
            {marketTrendsError && <p className="text-sm text-red-500">{marketTrendsError}</p>}

            {!marketTrends && !marketTrendsLoading && (
              <p className="text-sm text-gray-400 dark:text-gray-500">Run gap analysis to see market trends for your skills.</p>
            )}

            {marketTrends && !marketTrendsLoading && (
              <div className="space-y-5">
                {/* Summary cards */}
                {marketTrends.trends.length > 0 && (() => {
                  const withGrowth = marketTrends.trends.filter(s => s.weekly_growth_pct != null)
                  const avgGrowth  = withGrowth.length > 0
                    ? (withGrowth.reduce((a, s) => a + (s.weekly_growth_pct ?? 0), 0) / withGrowth.length).toFixed(1)
                    : null
                  const avgVol = (marketTrends.trends.reduce((a, s) => a + s.volatility_index, 0) / marketTrends.trends.length).toFixed(1)
                  const weeks  = marketTrends.weeks_with_data ?? 0
                  return (
                    <div className="grid sm:grid-cols-2 gap-4">
                      <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/20 p-4">
                        <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 mb-1">Weekly growth</p>
                        <p className="text-2xl font-bold text-emerald-700 dark:text-emerald-300 tabular-nums">
                          {avgGrowth != null ? `${Number(avgGrowth) >= 0 ? '+' : ''}${avgGrowth}%` : '—'}
                        </p>
                        <p className="text-xs text-emerald-600/70 dark:text-emerald-400/70 mt-1">
                          {weeks >= 2 ? `${withGrowth.length}/${marketTrends.trends.length} skills have data` : `Need ≥ 2 weeks (have ${weeks})`}
                        </p>
                      </div>
                      <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/20 p-4">
                        <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-1">Volatility</p>
                        <p className="text-2xl font-bold text-amber-700 dark:text-amber-300 tabular-nums">{avgVol}</p>
                        <p className="text-xs text-amber-600/70 dark:text-amber-400/70 mt-1">Avg variation in weekly demand</p>
                      </div>
                    </div>
                  )
                })()}

                {/* Emerging skills chips */}
                {marketTrends.top_emerging.length > 0 && (
                  <div>
                    <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Top emerging skills</p>
                    <div className="flex flex-wrap gap-2">
                      {marketTrends.top_emerging.map(s => (
                        <span key={s.skill_id} className="inline-flex items-center rounded-full bg-emerald-100 dark:bg-emerald-900/40 px-3 py-1 text-xs font-medium text-emerald-800 dark:text-emerald-200">
                          {s.skill_name}
                          <span className="ml-1.5 text-emerald-600 dark:text-emerald-400">+{s.weekly_growth_pct ?? 0}%</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Trends table — top 15 */}
                {marketTrends.trends.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm border-collapse">
                      <thead>
                        <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                          <th className="py-2 pr-3 font-medium">Skill</th>
                          <th className="py-2 px-2 text-right font-medium">Demand %</th>
                          <th className="py-2 px-2 text-right font-medium">Growth</th>
                          <th className="py-2 pl-2 text-right font-medium">Volatility</th>
                        </tr>
                      </thead>
                      <tbody>
                        {marketTrends.trends.slice(0, 15).map(s => (
                          <tr key={s.skill_id} className="border-b border-gray-100 dark:border-gray-800 last:border-0">
                            <td className="py-2 pr-3 text-gray-800 dark:text-gray-200 font-medium">{s.skill_name}</td>
                            <td className="py-2 px-2 text-right tabular-nums text-gray-600 dark:text-gray-400">{s.demand_percentage.toFixed(1)}%</td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {s.weekly_growth_pct != null
                                ? <span className={s.weekly_growth_pct >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-500'}>
                                    {s.weekly_growth_pct >= 0 ? '+' : ''}{s.weekly_growth_pct}%
                                  </span>
                                : <span className="text-gray-400">—</span>
                              }
                            </td>
                            <td className="py-2 pl-2 text-right tabular-nums text-amber-600 dark:text-amber-400">{s.volatility_index.toFixed(1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {marketTrends.trends.length > 15 && (
                      <p className="text-xs text-gray-400 mt-2">Showing top 15 of {marketTrends.trends.length} skills</p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 6. JOB MATCHES ───────────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Job matches</h2>
          <div className="flex items-center gap-2 flex-wrap">
            {roleInput.trim() !== '' && (
              <span className="text-xs text-gray-400 dark:text-gray-500">
                Filtered to “{roleInput.trim()}” · {visibleJobs.length} job{visibleJobs.length !== 1 ? 's' : ''}
              </span>
            )}
            {!dataLoading && visibleJobs.some(j => j.url?.trim()) && (
              <button
                type="button"
                onClick={() => {
                  const urls = visibleJobs.map(j => j.url?.trim()).filter(Boolean) as string[]
                  if (
                    !window.confirm(
                      `Open ${urls.length} job link(s) in new tabs? Your browser may block pop-ups.`,
                    )
                  )
                    return
                  urls.forEach((u) => window.open(u, '_blank', 'noopener,noreferrer'))
                }}
                className="text-xs font-semibold rounded-lg border border-indigo-300 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-800 dark:text-indigo-200 px-3 py-1.5 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors"
              >
                Apply to all
              </button>
            )}
          </div>
        </div>

        {dataLoading && (
          <div className="space-y-3">
            {[1,2,3].map(i => <Skeleton key={i} className="h-16 rounded-xl" />)}
          </div>
        )}

        {!dataLoading && visibleJobs.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <div className="h-12 w-12 rounded-lg border border-dashed border-gray-300 dark:border-gray-600" aria-hidden />
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">No job listings yet</p>
            <p className="text-xs text-gray-400 dark:text-gray-500 max-w-xs">
              {jobs.length === 0
                ? (gapResult?.demand_source === 'corpus' || gapResult?.market_source === 'corpus'
                    ? 'No live job URLs yet — market skills come from the curated corpus. Try scraping later or browse general job boards.'
                    : 'No live jobs found. Try re-running analysis or adjusting role.')
                : roleInput.trim()
                  ? `No jobs matching “${roleInput.trim()}” in titles. Try different keywords in your target role.`
                  : 'No jobs match the current filters.'}
            </p>
          </div>
        )}

        {!dataLoading && visibleJobs.length > 0 && (
          <>
            <ul className="space-y-3">
              {visibleJobs.map(j => (
                <JobCard
                  key={j.id}
                  job={j}
                  matchResult={matchResults.get(j.id) ?? null}
                  isLoading={loadingJobId === j.id}
                  canMatch
                  onMatch={() => runMatch(j.id, j.title)}
                  onOpenModal={() => setActiveMatchId(j.id)}
                  onJobExternalClick={() => {
                    void analysisApi.jobFeedback({
                      resume_id: selectedResumeId,
                      job_id: j.id,
                      action: 'clicked',
                    }).catch(() => {})
                  }}
                />
              ))}
            </ul>
            {canLoadMoreJobs && (
              <div className="flex justify-center pt-5 border-t border-gray-100 dark:border-gray-800 mt-5">
                <button
                  type="button"
                  onClick={() =>
                    setJobFetchLimit(n => Math.min(n + JOB_LIMIT_STEP, MAX_JOB_LIMIT))
                  }
                  className="text-sm font-semibold rounded-xl border border-indigo-300 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-950/40 text-indigo-800 dark:text-indigo-200 px-5 py-2.5 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors"
                >
                  View more jobs
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Match modal ──────────────────────────────────────────────────────── */}
      {activeMatchId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm" onClick={closeModal}>
          <div
            className="relative rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl space-y-5"
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  {cleanDisplayJobTitle(activeMatch?.job_title ?? activeModalJob?.title)}
                </h3>
                {activeModalJob && (modalCompany || modalPostedLabel) && (
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                    {modalCompany ? (
                      <span className="font-medium text-gray-600 dark:text-gray-300">{modalCompany}</span>
                    ) : null}
                    {modalCompany && modalPostedLabel ? <span className="text-gray-300 dark:text-gray-600"> · </span> : null}
                    {modalPostedLabel ? (
                      <span title={new Date(activeModalJob.posted_at).toLocaleString()}>Posted {modalPostedLabel}</span>
                    ) : null}
                  </p>
                )}
                {activeMatch && (
                  <div className="text-sm text-gray-500 dark:text-gray-400 mt-0.5 space-y-1">
                    <p>
                      Starting point:{' '}
                      <span className="font-semibold text-gray-800 dark:text-gray-200">
                        {activeMatch.resume_score.total_score.toFixed(1)}%
                      </span>
                      {' '}fit — strong potential to grow
                    </p>
                    {(activeMatch.resume_score.projection_message ||
                      (activeMatch.resume_score.projected_total_score != null &&
                        activeMatch.resume_score.projected_total_score > activeMatch.resume_score.total_score)) && (
                      <p className="text-indigo-600 dark:text-indigo-400 font-medium">
                        {activeMatch.resume_score.projection_message ??
                          `If you learn top skills: up to ~${activeMatch.resume_score.projected_total_score!.toFixed(0)}% fit`}
                      </p>
                    )}
                  </div>
                )}
              </div>
              <button type="button" onClick={closeModal} className="shrink-0 text-sm font-medium text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 px-2 py-1">Close</button>
            </div>

            {matchError && <p className="text-sm text-red-500">{matchError}</p>}

            {activeMatch && (
              <>
                {/* Score breakdown */}
                <MatchScoreBreakdown
                  totalScore={activeMatch.resume_score.total_score}
                  semanticScore={activeMatch.resume_score.semantic_score}
                  skillOverlapScore={activeMatch.resume_score.skill_overlap_score}
                  keywordCoverageScore={activeMatch.resume_score.keyword_coverage_score}
                  weights={activeMatch.resume_score.weights_used}
                  demandPenaltyRaw={activeMatch.resume_score.demand_penalty_raw}
                  demandPenaltyPoints={activeMatch.resume_score.demand_penalty_points}
                  uncertaintyScore={activeMatch.resume_score.uncertainty_score}
                />

                {(activeMatch.match_explanation || (activeMatch.resume_score.why_lines?.length ?? 0) > 0) && (
                  <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/40 p-4">
                    <p className="text-xs font-bold uppercase tracking-wide text-slate-600 dark:text-slate-400 mb-2">Why this score?</p>
                    {activeMatch.match_explanation ? (
                      <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed">{activeMatch.match_explanation}</p>
                    ) : (
                      <ul className="text-sm text-gray-700 dark:text-gray-300 list-disc list-inside space-y-1">
                        {(activeMatch.resume_score.why_lines ?? []).map((line, i) => (
                          <li key={i}>{line}</li>
                        ))}
                      </ul>
                    )}
                    {(activeMatch.resume_score.behavior_boost ?? 0) > 0 && (
                      <p className="text-xs text-violet-600 dark:text-violet-400 mt-2">
                        Behavior learning loop: +{activeMatch.resume_score.behavior_boost?.toFixed(1)} pts from jobs you engaged with
                        {activeMatch.resume_score.base_score_before_behavior != null
                          ? ` (base ${activeMatch.resume_score.base_score_before_behavior.toFixed(1)}%)`
                          : ''}
                      </p>
                    )}
                  </div>
                )}

                {/* Positive / negative factors */}
                {(activeMatch.top_positive_factors?.length || activeMatch.top_negative_factors?.length) && (
                  <div className="grid grid-cols-2 gap-3">
                    {activeMatch.top_positive_factors?.length && (
                      <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-800 p-3 space-y-1">
                        <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">What's working</p>
                        {activeMatch.top_positive_factors.map((f, i) => (
                          <p key={i} className="text-xs text-gray-700 dark:text-gray-300 flex gap-1.5"><span className="text-emerald-500 font-medium">+</span>{f}</p>
                        ))}
                      </div>
                    )}
                    {activeMatch.top_negative_factors?.length && (
                      <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800 p-3 space-y-1">
                        <p className="text-xs font-semibold text-red-600 dark:text-red-400">What's dragging score</p>
                        {activeMatch.top_negative_factors.map((f, i) => (
                          <p key={i} className="text-xs text-gray-700 dark:text-gray-300 flex gap-1.5"><span className="text-red-400 font-medium">−</span>{f}</p>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Matched / missing */}
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Matched skills</p>
                    <p className="text-gray-800 dark:text-gray-200">
                      {activeMatch.matched_skills.length
                        ? activeMatch.matched_skills.slice(0, 8).join(', ') + (activeMatch.matched_skills.length > 8 ? '…' : '')
                        : '—'}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Missing skills</p>
                    <p className="text-gray-800 dark:text-gray-200">
                      {activeMatch.missing_skills.length
                        ? activeMatch.missing_skills.slice(0, 8).join(', ') + (activeMatch.missing_skills.length > 8 ? '…' : '')
                        : '—'}
                    </p>
                  </div>
                </div>

                {/* Explainable AI */}
                {activeMatch.missing_skill_impacts && activeMatch.missing_skill_impacts.length > 0 && (
                  <ExplainableDashboard
                    currentScore={activeMatch.resume_score.total_score}
                    missingSkillImpacts={activeMatch.missing_skill_impacts}
                  />
                )}

                {/* Match advice */}
                {(activeMatch.ai_advice_structured || activeMatch.ai_advice) && (
                  <>
                    {activeMatch.ai_advice_structured
                      ? <MatchAdviceStructured data={activeMatch.ai_advice_structured} />
                      : <div className="rounded-xl border border-indigo-100 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-900/20 p-4">
                          <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{activeMatch.ai_advice}</p>
                        </div>
                    }
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
      </>
      )}

    </div>
  )
}
