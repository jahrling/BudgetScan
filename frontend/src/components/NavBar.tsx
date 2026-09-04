import { useEffect, useRef, useState } from 'react'
import { Monitor, Moon, Sun } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { useTheme } from '../hooks/useTheme'
import { cn } from '../lib/utils'

type ThemePref = "system" | "light" | "dark";

const themeOptions: Array<{ value: ThemePref; label: string; icon: typeof Sun }> = [
  { value: "system", label: "System", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

export default function NavBar() {
  const { user, logout } = useAuth()
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onClick)
    return () => document.removeEventListener("mousedown", onClick)
  }, [open])

  if (!user) return null

  return (
    <nav className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-3">
      <span className="text-lg font-semibold text-gray-900 dark:text-gray-100">Finance</span>
      <div ref={ref} className="relative">
        <button
          onClick={() => setOpen(!open)}
          className="text-sm font-medium text-sky-600 dark:text-sky-400"
        >
          {user.username}
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-2 w-56 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-xl z-50 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
              <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">{user.username}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Signed in</div>
            </div>

            <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
              <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Theme</div>
              <div className="flex rounded-md bg-gray-100 dark:bg-gray-700 p-0.5 gap-0.5">
                {themeOptions.map(({ value, label, icon: Icon }) => (
                  <button
                    key={value}
                    onClick={() => setTheme(value)}
                    className={cn(
                      "flex-1 flex items-center justify-center gap-1 py-1.5 text-xs font-medium rounded transition-colors",
                      theme === value
                        ? "bg-white dark:bg-gray-600 text-gray-900 dark:text-gray-100 shadow-sm"
                        : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="px-4 py-2">
              <button
                onClick={() => { logout(); setOpen(false); }}
                className="w-full text-left text-sm text-red-600 dark:text-red-400 py-1.5"
              >
                Log out
              </button>
            </div>
          </div>
        )}
      </div>
    </nav>
  )
}
