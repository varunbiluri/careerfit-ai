import { Link } from 'react-router-dom'
import { useTheme } from '../contexts/ThemeContext'

export default function Landing() {
  const { theme, toggleTheme } = useTheme()

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950">
      <header className="border-b border-gray-200 dark:border-gray-800">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <span className="text-xl font-semibold text-gray-900 dark:text-white">CareerFit AI</span>
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={toggleTheme}
              className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              {theme === 'dark' ? 'Light mode' : 'Dark mode'}
            </button>
            <Link
              to="/app"
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Dashboard
            </Link>
          </div>
        </div>
      </header>

      <section className="max-w-6xl mx-auto px-4 py-20 text-center">
        <h1 className="text-4xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-5xl">
          Build a career plan from live job-market gaps
        </h1>
        <p className="mt-4 text-lg text-gray-600 dark:text-gray-400 max-w-2xl mx-auto">
          Upload your resume, compare it against real job postings, and see which skills to build next with demand data, match scoring, and AI guidance.
        </p>
        <Link
          to="/app"
          className="mt-8 inline-flex items-center rounded-lg bg-indigo-600 px-6 py-3 text-base font-medium text-white hover:bg-indigo-700"
        >
          Upload Resume
        </Link>
      </section>

      <section className="border-t border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/50">
        <div className="max-w-6xl mx-auto px-4 py-16">
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-white text-center mb-10">
            How it works
          </h2>
          <div className="grid sm:grid-cols-3 gap-8">
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 text-center">
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-gray-300 dark:border-gray-600 text-sm font-semibold text-gray-600 dark:text-gray-300">1</div>
              <h3 className="font-medium text-gray-900 dark:text-white">Upload</h3>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">Upload your resume PDF. We extract skills and text securely — no scraping on upload.</p>
            </div>
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 text-center">
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-gray-300 dark:border-gray-600 text-sm font-semibold text-gray-600 dark:text-gray-300">2</div>
              <h3 className="font-medium text-gray-900 dark:text-white">Match & score</h3>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">50% semantic similarity, 30% skill overlap, 20% keyword coverage for a clear resume score.</p>
            </div>
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 text-center">
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-gray-300 dark:border-gray-600 text-sm font-semibold text-gray-600 dark:text-gray-300">3</div>
              <h3 className="font-medium text-gray-900 dark:text-white">Skill demand</h3>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">See which missing skills are in highest demand so you can prioritize learning.</p>
            </div>
          </div>
        </div>
      </section>

      <footer className="border-t border-gray-200 dark:border-gray-800 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
        CareerFit AI · Open source under the MIT License
      </footer>
    </div>
  )
}
