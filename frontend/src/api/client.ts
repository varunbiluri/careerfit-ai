import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

export const api = axios.create({
  baseURL: API_BASE,
  // Default high enough for cold embedding load + heavy list endpoints; gap analysis uses a longer per-call timeout.
  timeout: 180000,
  headers: { 'Content-Type': 'application/json' },
})

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/** Normalise Axios/FastAPI errors into a single display string. */
export function parseApiError(err: unknown): string {
  if (!err || typeof err !== 'object') return 'An unexpected error occurred'
  const e = err as {
    response?: { data?: { detail?: unknown } }
    message?: string
    code?: string
  }
  if (e.code === 'ECONNABORTED' || (e.message?.toLowerCase().includes('timeout')))
    return 'Request timed out before the server finished. Gap analysis can take several minutes (scraping, embeddings, local LLM). Click Analyze again, or set LLM_BASE_URL empty in the API .env to skip AI coach text and speed things up.'
  const detail = e.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((x: unknown) => (x as { msg?: string })?.msg ?? String(x)).join(' ')
  return e.message || 'An error occurred'
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ResumeOut {
  id: number
  filename: string
  candidate_name: string | null
  created_at: string
  skill_names: string[]
  ai_summary?: string | null
}

export interface JobListOut {
  id: number
  external_id: string
  title: string | null
  company: string | null
  seniority_level: string | null
  function: string | null
  source: string
  url?: string | null
  /** ISO timestamp: employer listing time when parsed (e.g. LinkedIn), else last scrape / first ingest. */
  posted_at: string
}

export interface SkillDemandOut {
  skill_id: number
  skill_name: string
  category: string | null
  job_count: number
  demand_percentage: number
}

/** Explainable AI: per-missing-skill score drop and hypothetical score if added */
export interface MissingSkillImpactOut {
  skill_name: string
  score_drop: number
  score_if_added: number
  demand_percentage: number | null
  demand_penalty_impact: number | null
}

/** Structured LLM match advice (JSON output) */
export interface RewrittenBulletOut {
  original: string
  rewritten: string
}

export interface MatchAdviceStructuredOut {
  fit_level: string
  fit_reason: string
  highlights: string[]
  bullet_improvements: string[]
  rewritten_bullets: RewrittenBulletOut[]
  measurable_metrics: string[]
  improve_skills: string[]
  priority?: string[]
  highlight?: string
  next_step?: string
}

/** Structured LLM gap advice (JSON output) */
export interface GapAdviceStructuredOut {
  prioritize: string[]
  highlight_how: string
  next_step: string
  bullet_improvements: string[]
  measurable_metrics: string[]
  priority?: string[]
  highlight?: string
  /** LLM-suggested portfolio builds */
  project_ideas?: string[]
  /** LLM-suggested ordered steps (not the same as top-level ResumeGapOut.learning_path) */
  learning_path?: string[]
}

/** Data quality / freshness metadata returned by the gap analysis endpoint. */
export interface DataQualityMeta {
  jobs_count: number
  freshness_hours: number
  completeness_score: number   // 0–1 fraction of jobs with title + description + company
  is_fresh: boolean
  scraped_at: string | null    // ISO datetime string, null if never scraped
  source: string               // fresh_cache | live_scrape | concurrent_lock | synthetic
  quality_band?: 'high' | 'medium' | 'low'
  demand_source?: 'real' | 'corpus' | 'synthetic'
}

export interface MatchResult {
  job_id: number
  job_external_id: string
  job_title: string | null
  match_percentage: number
  resume_score: {
    total_score: number
    semantic_score: number
    skill_overlap_score: number
    keyword_coverage_score: number
    weights_used?: { semantic: number; skill_overlap: number; keyword_coverage: number; demand_penalty?: number }
    demand_penalty_raw?: number
    demand_penalty_points?: number
    uncertainty_score?: number        // 0 = confident, 30 = sparse reference data
    projected_total_score?: number | null
    projection_message?: string | null
    score_reason?: string
    scoring_mode?: string | null
    scoring_reason?: string | null
    behavior_boost?: number
    behavior_score_normalized?: number
    base_score_before_behavior?: number | null
    profile_role_boost?: number
    confidence?: 'high' | 'medium' | 'low' | null
    why_lines?: string[]
  }
  match_mode?: string | null
  matched_skills: string[]
  missing_skills: string[]
  semantic_similarity: number
  high_demand_missing_skills: SkillDemandOut[]
  missing_skill_impacts?: MissingSkillImpactOut[]
  top_positive_factors?: string[]     // What is driving the score up
  top_negative_factors?: string[]     // What is dragging the score down
  ai_advice?: string | null
  ai_advice_structured?: MatchAdviceStructuredOut | null
  /** Deterministic "why this score" narrative */
  match_explanation?: string
  confidence?: 'high' | 'medium' | 'low' | null
}

export interface ResumeGapOut {
  resume_skills: string[]
  market_skill_count: number
  matched_skills: string[]
  missing_skills: string[]
  high_demand_missing_skills: SkillDemandOut[]
  fit_percentage: number
  gap_percentage: number
  projected_fit_percentage?: number | null
  scrape_summary: {
    total_new: number
    total_cached: number
    portals: Record<string, { new: number; cached: number; links_found: number; error?: string }>
    errors: string[]
    links_parsed_total?: number
    market_scrape_degraded?: boolean
    db_jobs_count?: number
    scrape_health?: { links_found: number; is_degraded: boolean; reason: string }
    synthetic_fallback_inserted?: number
  } | null
  job_title?: string | null
  market_source?: string | null        // scraped | corpus | synthetic
  demand_source?: 'real' | 'corpus' | 'synthetic' | null
  matching_explanation?: string | null
  ai_advice?: string | null
  ai_advice_structured?: GapAdviceStructuredOut | null
  // Phase 3: categorised skill intelligence (backend sends these when available)
  missing_skills_by_category?: Record<string, string[]>
  weakness_summary?: string[]
  learning_path?: string[]
  data_quality?: DataQualityMeta
  job_fetch_notice?: string | null
  target_role?: string | null
  experience_level?: string | null
  experience_years?: number | null
  experience_interpretation?: string | null
  suggested_roles?: string[]
  career_insights?: CareerInsightsOut | null
  confidence?: 'high' | 'medium' | 'low' | null
  best_next_action?: BestNextActionOut | null
  time_aware_insights?: string[]
  relevance_decay_model_note?: string
  predictive_warnings?: string[]
  predictive_opportunities?: string[]
}

export interface CareerInsightsOut {
  headline_closest_role: string
  headline_roi_skill: string
  headline_strongest_domain: string
  headline_ahead_of_peers?: string
  comparison_vs_median?: string
  headline_roi_percent?: string
  headline_improving_vs_peers?: string
  headline_trending_role?: string
  headline_switch_timing?: string
  detail_lines: string[]
}

export interface BestNextActionOut {
  type: 'learn_skill' | 'apply_jobs' | 'switch_role'
  reason: string
  expected_impact_percent: number
}

export interface SuggestedRolesOut {
  roles: string[]
}

/** GET /analysis/suggest-roles — embedding-based role fit vs job corpus */
export interface RoleFitOut {
  role: string
  fit: number
  fit_reason?: string
}

/** POST /analysis/simulate-skills */
export interface SimulationStepOut {
  step: number
  skills: string[]
  fit: number
  weeks_estimate: number
}

export interface SimulateSkillsOut {
  new_fit: number
  previous_fit: number
  improvement: number
  skills_added: string[]
  market_skill_count: number
  steps?: SimulationStepOut[] | null
}

/** Returned by GET /analysis/status/{task_id}. */
export interface TaskStatusResponse {
  task_id: string
  status: 'queued' | 'in_progress' | 'completed' | 'failed' | 'not_found' | string
  message?: string | null
  result?: Record<string, unknown> | null   // ResumeGapOut dict when status === 'completed'
  error?: string | null
}

/** Market trend analytics: time-based skill trend */
export interface SkillTrendOut {
  skill_id: number
  skill_name: string
  category: string | null
  job_count: number
  demand_percentage: number
  weekly_growth_pct: number | null
  volatility_index: number
}

export interface MarketTrendsOut {
  trends: SkillTrendOut[]
  top_emerging: SkillTrendOut[]
  /** Number of distinct weeks with job data; need >= 2 for weekly growth and volatility */
  weeks_with_data: number
}

/** GET /analysis/skill-trends — fastest vs declining */
export interface SkillTrendsEngineOut {
  fastest_growing_skills: SkillTrendOut[]
  declining_skills: SkillTrendOut[]
  weeks_with_data: number
}

export interface RoleTransitionProbOut {
  role: string
  probability: number
}

export interface CareerPathOut {
  current_role: string
  next_roles: string[]
  required_skills: string[]
  role_transitions?: RoleTransitionProbOut[]
}

export interface GlobalInsightsOut {
  top_skills: { name: string; score: number }[]
  emerging_roles: { name: string; score: number }[]
  common_transitions: { from_role: string; to_role: string; weight: number }[]
  fastest_adopted_skills: Record<string, unknown>[]
  trend_weeks_available: number
}

export interface LikelyNextRoleOut {
  role: string
  probability: number
  time_estimate_weeks: number
}

export interface CareerTrajectoryOut {
  current_role: string
  likely_next_roles: LikelyNextRoleOut[]
  risk_of_stagnation: number
}

export interface CareerProgressPointOut {
  snapshot_at: string
  fit_score: number
  skills_count: number
  roles_considered: string[]
}

export interface CareerProgressOut {
  points: CareerProgressPointOut[]
  improvement_rate_per_week: number
  peer_improvement_percentile: number
  insight_lines: string[]
}

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------

export const resumesApi = {
  list: (params?: { skip?: number; limit?: number }) =>
    api.get<ResumeOut[]>('/resumes/', { params }),
  get: (id: number) => api.get<ResumeOut>(`/resumes/${id}`),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<ResumeOut>('/resumes/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,
    })
  },
  generateSummary: (id: number) =>
    api.post<{ id: number; ai_summary: string }>(
      `/resumes/${id}/generate-summary`,
      {},
      { timeout: 90000 },
    ),
  suggestRoles: (id: number) => api.get<SuggestedRolesOut>(`/resumes/${id}/suggest-roles`),
}

export const jobsApi = {
  list: (params?: { skip?: number; limit?: number; resume_id?: number }) =>
    api.get<JobListOut[]>('/jobs/', { params, timeout: 120000 }),
  get: (id: number) => api.get(`/jobs/${id}`),
}

export const analysisApi = {
  match: (jobId: number, resumeId: number) =>
    api.get<MatchResult>('/analysis/match', {
      params: { job_id: jobId, resume_id: resumeId },
      timeout: 300000,
    }),
  skillDemand: () => api.get<SkillDemandOut[]>('/analysis/skill-demand'),
  /** POST /analysis/resume-gap — returns ResumeGapOut (HTTP 200). */
  resumeGap: (
    resumeId: number,
    body?: { target_role?: string; experience_input?: string },
  ) =>
    api.post<ResumeGapOut>(
      '/analysis/resume-gap',
      { resume_id: resumeId, ...body },
      { timeout: 600000 },
    ),
  /**
   * POST /analysis/resume-gap-stream — SSE: log lines, progress (percent + message), then result.
   */
  resumeGapStream: async (
    resumeId: number,
    body: { target_role?: string; experience_input?: string },
    callbacks: {
      onProgress: (ev: { percent: number; message: string }) => void
      onLog: (message: string) => void
      onResult: (data: ResumeGapOut) => void
      onError: (detail: string) => void
    },
  ): Promise<void> => {
    const res = await fetch(`${API_BASE}/analysis/resume-gap-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ resume_id: resumeId, ...body }),
    })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const t = await res.text()
        if (t) {
          try {
            const j = JSON.parse(t) as { detail?: string }
            if (typeof j.detail === 'string') detail = j.detail
            else detail = t.slice(0, 500)
          } catch {
            detail = t.slice(0, 500)
          }
        }
      } catch {
        /* keep default */
      }
      callbacks.onError(detail)
      return
    }
    const reader = res.body?.getReader()
    if (!reader) {
      callbacks.onError('No response body')
      return
    }
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const block of parts) {
        for (const line of block.split('\n')) {
          if (!line.startsWith('data: ')) continue
          let parsed: Record<string, unknown>
          try {
            parsed = JSON.parse(line.slice(6)) as Record<string, unknown>
          } catch {
            continue
          }
          const t = parsed.type
          if (t === 'progress') {
            const percent = Number(parsed.percent)
            const message = String(parsed.message ?? '')
            if (Number.isFinite(percent)) callbacks.onProgress({ percent, message })
          } else if (t === 'log') {
            callbacks.onLog(String(parsed.message ?? ''))
          } else if (t === 'result' && parsed.payload) {
            callbacks.onResult(parsed.payload as ResumeGapOut)
            return
          } else if (t === 'error') {
            callbacks.onError(String(parsed.detail ?? 'Unknown error'))
            return
          }
        }
      }
    }
    callbacks.onError('Stream ended without result')
  },
  /** Poll the status of a background task (legacy; gap analysis is synchronous). */
  getTaskStatus: (taskId: string) =>
    api.get<TaskStatusResponse>(`/analysis/status/${taskId}`),
  marketTrends: (params?: { weeks?: number; top_emerging_n?: number; resume_id?: number }) =>
    api.get<MarketTrendsOut>('/analysis/market-trends', { params, timeout: 120000 }),
  /** Top ~3 roles from resume vs stored jobs (BGE cosine similarity). */
  suggestRolesFromCorpus: (resumeId: number) =>
    api.get<RoleFitOut[]>('/analysis/suggest-roles', { params: { resume_id: resumeId }, timeout: 120000 }),
  simulateSkills: (body: {
    resume_id: number
    skills_to_add: string[]
    target_role?: string | null
    multi_step?: boolean
  }) => api.post<SimulateSkillsOut>('/analysis/simulate-skills', body, { timeout: 120000 }),
  jobFeedback: (body: { resume_id: number; job_id: number; action: 'viewed' | 'clicked' | 'applied' }) =>
    api.post<{ ok: boolean }>('/analysis/job-feedback', body),
  skillTrendsEngine: (params?: { weeks?: number; limit?: number }) =>
    api.get<SkillTrendsEngineOut>('/analysis/skill-trends', { params, timeout: 120000 }),
  careerPath: (params: { resume_id: number; current_role?: string | null }) =>
    api.get<CareerPathOut>('/analysis/career-path', { params, timeout: 120000 }),
  globalInsights: () =>
    api.get<GlobalInsightsOut>('/analysis/global-insights', { timeout: 60000 }),
  careerTrajectory: (params: { resume_id: number; target_role?: string | null }) =>
    api.get<CareerTrajectoryOut>('/analysis/career-trajectory', { params, timeout: 120000 }),
  careerProgress: (resumeId: number) =>
    api.get<CareerProgressOut>('/analysis/career-progress', {
      params: { resume_id: resumeId },
      timeout: 60000,
    }),
}
