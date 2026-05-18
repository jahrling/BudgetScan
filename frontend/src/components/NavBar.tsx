import { useAuth } from '../hooks/useAuth'

export default function NavBar() {
  const { user, logout } = useAuth()

  if (!user) return null

  return (
    <nav className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
      <span className="text-lg font-semibold text-gray-900">Finance</span>
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-600">{user.username}</span>
        <button
          onClick={() => logout()}
          className="rounded bg-gray-100 px-3 py-1 text-sm text-gray-700 hover:bg-gray-200"
        >
          Log out
        </button>
      </div>
    </nav>
  )
}
