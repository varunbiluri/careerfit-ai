import { Outlet, NavLink } from 'react-router-dom'
import { useTheme } from '../contexts/ThemeContext'

export default function Layout() {
  const { theme, toggleTheme } = useTheme()

  return (
    <div className="min-h-screen flex bg-gray-50 dark:bg-gray-950">
      <aside className="w-56 shrink-0 border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 flex flex-col">
        <div className="p-4 border-b border-gray-200 dark:border-gray-800">
          <NavLink to="/" className="text-lg font-semibold text-gray-900 dark:text-white">
            Skill Gap
          </NavLink>
        </div>
        <nav className="p-2 flex flex-col gap-0.5">
          <NavLink
            to="/app"
            end
            className={({ isActive }) =>
              `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
              }`
            }
          >
            Dashboard
          </NavLink>
        </nav>
        <div className="mt-auto p-4">
          <button
            type="button"
            onClick={toggleTheme}
            className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
          >
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
