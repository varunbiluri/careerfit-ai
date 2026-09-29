interface CircularScoreProps {
  score: number
  label?: string
  size?: number
  strokeWidth?: number
}

export default function CircularScore({ score, label = 'Score', size = 120, strokeWidth = 8 }: CircularScoreProps) {
  const r = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * r
  const offset = circumference - (score / 100) * circumference
  const color = score >= 70 ? 'rgb(34, 197, 94)' : score >= 40 ? 'rgb(234, 179, 8)' : 'rgb(239, 68, 68)'

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-gray-200 dark:text-gray-700"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-700"
        />
      </svg>
      <span className="mt-2 text-2xl font-bold text-gray-900 dark:text-white">{Math.round(score)}</span>
      <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
    </div>
  )
}
