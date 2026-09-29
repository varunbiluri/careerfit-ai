/**
 * Full-screen progress while resume uploads or gap analysis runs.
 * Upload: numeric %; gap analysis: SSE percent + ETA + live log lines.
 */
import { useEffect, useId, useRef } from 'react'

type Props = {
  uploading: boolean
  analyzing: boolean
  uploadPercent: number
  /** Ring fill 0–100 from SSE `percent` milestones. */
  analyzePercent: number
  /** Estimated seconds remaining from elapsed / percent; null if unknown. */
  analyzeEtaSeconds: number | null
  statusLine: string | null
  logs: readonly string[]
}

export default function AgentWorkspaceOverlay({
  uploading,
  analyzing,
  uploadPercent,
  analyzePercent,
  analyzeEtaSeconds,
  statusLine,
  logs,
}: Props) {
  const gid = useId().replace(/:/g, '')
  const gradId = `pg-${gid}`
  const logRef = useRef<HTMLDivElement>(null)
  const uploadPhase = uploading && !analyzing
  const percent = uploadPhase ? uploadPercent : analyzePercent
  const ringR = 88
  const circumference = 2 * Math.PI * ringR
  const dashOffset = circumference * (1 - Math.min(1, percent / 100))

  useEffect(() => {
    const el = logRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [logs])

  const title = uploadPhase ? 'Uploading resume' : 'Running gap analysis'
  const etaLine =
    !uploadPhase && analyzeEtaSeconds != null && analyzeEtaSeconds > 0
      ? `~${analyzeEtaSeconds}s left (estimate)`
      : null
  const subtitle = uploadPhase
    ? 'Sending your PDF to the API…'
    : [statusLine || 'Waiting for server…', etaLine].filter(Boolean).join(' · ')

  return (
    <div
      className="fixed inset-0 z-[200] overflow-y-auto bg-slate-950"
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-busy="true"
      aria-label={title}
    >
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-1/2 -left-1/4 w-[80%] h-[80%] rounded-full bg-indigo-600/10 blur-3xl" />
        <div className="absolute -bottom-1/3 -right-1/4 w-[70%] h-[70%] rounded-full bg-cyan-600/8 blur-3xl" />
      </div>

      <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-2xl flex-col justify-center px-4 py-10">
        <header className="mb-8 text-center">
          <h2 className="text-xl font-semibold text-white sm:text-2xl">{title}</h2>
          <p className="mt-2 text-sm text-slate-400">{subtitle}</p>
        </header>

        <div className="relative mx-auto mb-10 w-[min(100%,260px)]">
          <svg className="w-full -rotate-90 drop-shadow-[0_0_24px_rgba(99,102,241,0.35)]" viewBox="0 0 200 200" aria-hidden>
            <defs>
              <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#818cf8" />
                <stop offset="100%" stopColor="#22d3ee" />
              </linearGradient>
            </defs>
            <circle cx="100" cy="100" r={ringR} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="14" />
            <circle
              cx="100"
              cy="100"
              r={ringR}
              fill="none"
              stroke={`url(#${gradId})`}
              strokeWidth="14"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              className="transition-[stroke-dashoffset] duration-500 ease-out"
            />
          </svg>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            {uploadPhase ? (
              <>
                <span className="text-5xl font-bold tabular-nums tracking-tight text-white sm:text-6xl">{uploadPercent}</span>
                <span className="text-sm font-medium text-slate-500">%</span>
              </>
            ) : (
              <>
                <span className="text-5xl font-bold tabular-nums tracking-tight text-white sm:text-6xl">
                  {analyzePercent === 0 ? '·' : Math.min(100, Math.round(analyzePercent))}
                </span>
                <span className="text-sm font-medium text-slate-500">%</span>
              </>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-black/50 shadow-inner">
          <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
            <span className="relative flex h-2 w-2 rounded-full bg-emerald-500/90">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Activity</span>
            <span className="ml-auto text-[10px] text-slate-600">
              {analyzing ? 'Server-Sent Events' : 'Client'}
            </span>
          </div>
          <div
            ref={logRef}
            className="max-h-[min(40vh,320px)] overflow-y-auto px-3 py-3 font-mono text-[11px] leading-relaxed text-slate-300 sm:text-xs"
          >
            {logs.length === 0 ? (
              <p className="text-slate-600">Waiting…</p>
            ) : (
              logs.map((line, i) => (
                <p key={`${i}-${line.slice(0, 32)}`} className="text-left break-words border-l-2 border-transparent pl-2 hover:border-slate-700">
                  <span className="text-slate-600">{line}</span>
                </p>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
